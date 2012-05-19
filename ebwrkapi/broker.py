""" The Job Broker accepts messages from the `Client` and shall prepend a message part containing
the identity of the originating peer to the message before passing it to the `Worker`.

Example Usage:

broker = ebwrkapi.EBBroker()
broker.frontend.bind("tcp://*:5555")
broker.backend.bind("tcp://*:5556")
broker.run()
"""

import time
import logging
import zmq
import cjson
import collections
import binascii

HEARTBEAT_LIVENESS = 3     # 3..5 is reasonable
HEARTBEAT_INTERVAL = 1   # Seconds
REQUEST_LIFESPAN = 1  # seconds

PPP_READY = "\x01"  # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat
PPP_BUSY = "\x03"  # Signals worker busy state

log = logging.getLogger(__name__)


class Service(object):
    """a single Service"""

    name = None  # Service name
    requests = None  # List of client requests
    waiting = None  # List of waiting workers

    def __init__(self, name):
        self.name = name
        self.requests = []
        self.waiting = []


class Worker(object):
    """an idle or active Worker instance"""

    identity = None  # hex Identity of worker
    address = None  # routing address
    expiry = None  # expires at this point - unless heartbeat
    service = None  # owning service name if known

    def __init__(self, identity, address):
        self.identity = identity
        self.address = address
        self.expiry = time.time() + 1e-3 * HEARTBEAT_LIVENESS


class WorkerQueue(object):
    """ Fast Queue of `ready` Workers which can be retrived in a Leased Recently Used order.
    """

    def __init__(self):
        self.queue = {}

    def ready(self, worker, service):

        if not service in self.queue:  # init
            self.queue[service] = collections.OrderedDict()
        # remove the address if it happend to be set already
        self.queue[service].pop(worker.address, None)
        # register `Worker` object
        self.queue[service][worker.address] = worker

    def purge(self):
        """Look for & kill expired workers."""
        t = time.time()

        expired = []
        for address, worker in self.queue.iteritems():
            if t < worker.expiry:  # Worker is alive (seen recently)
                break
            expired.append(address)

        # update the queue with the result
        for address in expired:
            log.warn("Idle worker expired: %s" % address)
            self.queue.pop(address, None)

    def next(self):  # return oldest entry in list
        address, worker = self.queue.popitem(False)
        log.info('using WorkerServer: %s | %s | %s' % (address, worker, len(self.queue)))
        return address


class EBBroker(object):

    def __init__(self):

        self.services = {}  # `Worker` objects grouped by Service to allow for faster discovery
        self.workers = {}  # index of all `Worker` objects by address
        self.waiting = []  # direct access to check heartbeat status of Workers
        self.heartbeat_at = time.time() + 1e-3 * HEARTBEAT_INTERVAL

        self.context = zmq.Context(1)

        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.linger = 0

        self.frontend = self.context.socket(zmq.ROUTER)  # Front End
        self.frontend.setsockopt(zmq.HWM, 0)

        self.backend = self.context.socket(zmq.ROUTER)  # Back End
        self.backend.setsockopt(zmq.HWM, 0)

        self.pull_backends = zmq.Poller()
        self.pull_backends.register(self.backend, zmq.POLLIN)

        self.poll_both = zmq.Poller()
        self.poll_both.register(self.frontend, zmq.POLLIN)
        self.poll_both.register(self.backend, zmq.POLLIN)

    def run(self):

        while True:

            # ignore FE / client requests if no workers are connected to the backend (no PPP_READY received)
            if not len(self.workers):
                log.warn('No Worker available - Waiting for Worker to join on BE')
                poller = self.pull_backends
            else:
                poller = self.poll_both

            try:  # poll socket for request message
                socks = dict(poller.poll(HEARTBEAT_INTERVAL * 1000))
            except KeyboardInterrupt:
                break  # Keyboard Interrupted

            # handle worker activity on backend
            if socks.get(self.backend) == zmq.POLLIN:

                log.debug('worker BE activity')
                self.process_worker()

            # Client request received - forward it to the backend router
            if socks.get(self.frontend) == zmq.POLLIN:

                log.debug('client FE activity')
                self.process_client()

            self.send_heartbeats()

            self.purge_workers()

    def process_worker(self):
        """Process Worker Message"""

        # read request from BE
        frames = self.backend.recv_multipart()
        assert len(frames) >= 1

        # parse response
        address = frames[0]
        msg = frames[1:]

        # worker had been registered already / active session open
        worker_ready = binascii.hexlify(address) in self.workers

        # create `Worker` object
        worker = self.require_worker(address)

        # worker control message received
        if len(msg) in [1, 2]:

            command = msg.pop(0)

            # fires via `Worker.__init__`
            if command == PPP_READY:

                # not first command after startup
                if worker_ready:
                    log.critical('Late PPP_READY received')
                    return

                service = msg.pop(0)

                log.info('PPP_READY received from "%s" worker: %s' % (
                    service, address
                ))

                # attach worker to service and mark as idle
                worker.service = self.require_service(service)

                self.worker_waiting(worker)

            elif command == PPP_HEARTBEAT:

                log.info('PPP_HEARTBEAT received from worker: %s' % address)
                if worker_ready:
                    worker.expiry = time.time() + 1e-3 * HEARTBEAT_INTERVAL

                self.worker_waiting(worker)

                self.dispatch_request(worker.service, [PPP_HEARTBEAT])

            else:
                log.critical("Invalid message from worker: %s" % address)

        else:  # custom response

            log.info('forwarding Worker (%s) response to Front End: %s' % (address, msg))
            self.frontend.send_multipart(msg)

    def process_client(self):

        # read request as multi part message from FE router socket
        frames = self.frontend.recv_multipart()
        assert len(frames) >= 2  # service name + request body

        # parse request
        ident, x, service, function, expiration, request = frames

        # discared if request is expired
        request_age = int(time.time()) - int(expiration)
        if request_age >= REQUEST_LIFESPAN:
            log.debug('request expired %i seconds ago' % request_age)
            return

        if function.startswith('mmi.'):

            log.debug('internal service call')
            self.service_lookup(frames)

        else:

            log.debug('new request: %s | %s (from: %s)' % (service, function, ident))
            self.dispatch_request( self.require_service(service), frames )

    def dispatch_request(self, service, msg):

        assert (service is not None)

        log.info('dispatch_request: %s | %s' % (service, msg))

        if msg is not None:  # queue message if any so nothing gets lost
            service.requests.append(msg)

        self.purge_workers()

        while service.waiting and service.requests:
            msg = service.requests.pop(0)
            new_worker = service.waiting.pop(0)

            # add the destination Worker Identity to the client request
            msg.insert(0, new_worker.address)

            log.info('forwarding Client request (%s) to Worker BE: %s' % (msg, new_worker))

            # send message to backend
            self.backend.send_multipart(msg)

    def service_lookup(self, msg):

        service_name = msg[3].replace('mmi.', '')

        returncode = '501'
        returncode = '200' if service_name in self.services else '400'

        msg = msg[:2] + [service_name, returncode]

        # send response to client Front End router
        self.frontend.send_multipart(msg)

    def send_heartbeats(self):

        log.info('send_heartbeats: %s worker' % len(self.waiting))

        # Send heartbeats to idle workers if it's time
        if time.time() >= self.heartbeat_at:

            for worker in self.waiting:
                log.info('PING: %s' % worker)
                msg = [worker.address, PPP_HEARTBEAT]
                self.backend.send_multipart(msg)

            self.heartbeat_at = time.time() + 1e-3 * HEARTBEAT_INTERVAL

    def require_service(self, name):
        """ Locates the service (registers if necessary)
        """
        assert (name is not None)
        service = self.services.get(name)
        if (service is None):
            service = Service(name)
            self.services[name] = service
        return service

    def require_worker(self, address):
        """ Find or create `Worker` record
        """
        assert (address is not None)
        identity = binascii.hexlify(address)
        worker = self.workers.get(address)
        if not worker:
            worker = Worker( identity, address )
            self.workers[address] = worker
            log.info("I: registering new worker: %s | %s" % (
                address, worker
            ))

        return worker

    def worker_waiting(self, worker):
        """This worker is now waiting for work.
        """
        log.info('worker waiting call: %s' % worker)

        # Queue to broker and service waiting lists
        self.waiting.append(worker)
        worker.service.waiting.append(worker)

        worker.expiry = time.time() + 1e-3 * HEARTBEAT_LIVENESS

        self.dispatch_request(worker.service, None)

    def purge_workers(self):
        """ Look for & kill expired workers.
        Workers are oldest to most recent, so we stop at the first alive worker.
        """
        while self.waiting:
            w = self.waiting[0]
            log.info('purge check: %s' % w)
            if w.expiry < time.time():
                logging.info("I: deleting expired worker: %s", w.identity)
                self.waiting.pop(0)
            else:
                break

