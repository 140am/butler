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
import collections
import binascii
import threading

HEARTBEAT_INTERVAL = 1000  # msec between heartbeats sent out
HEARTBEAT_LIVENESS = 3  # seconds until heartbeat is expected / worker is considered dead
REQUEST_LIFESPAN = 1  # seconds

PPP_READY = "\x01"  # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat
PPP_RECONNECT = "\x03"  # Signals worker re-connect

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
        self.expiry = time.time() + HEARTBEAT_LIVENESS


class EBBroker(object):

    heart = None

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

    def setup_heartbeat(self):

        log.info('setup_heartbeat')

        while True:

            log.debug('attempting to ping %i worker' % len(self.waiting))

            self.purge_workers()

            for worker in self.waiting:
                log.debug('PING sent: %s' % worker)
                msg = [worker.address, PPP_HEARTBEAT]
                self.backend.send_multipart(msg)

            self.heartbeat_at = time.time() + 1e-3 * HEARTBEAT_INTERVAL

            time.sleep(1e-3 * HEARTBEAT_INTERVAL)

    def run(self):

        # setup Broker Heartbeat

        self.heart = threading.Thread(target=self.setup_heartbeat)
        self.heart.daemon = True
        self.heart.start()

        while True:

            # ignore FE / client requests if no workers are connected to the backend (no PPP_READY received)
            if not len(self.workers):
                log.warn('No Worker available - Waiting for Worker to join on BE')
                poller = self.pull_backends
            else:
                poller = self.poll_both

            try:  # poll socket for request message
                socks = dict(poller.poll(HEARTBEAT_INTERVAL))
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

    def process_worker(self):
        """Process Worker Message"""

        # read request from BE
        frames = self.backend.recv_multipart()
        assert len(frames) >= 1

        # parse response
        address = frames[0]
        msg = frames[1:]

        # worker had been registered already / active session open
        worker_ready = address in self.workers

        # create `Worker` object
        worker = self.require_worker(address)

        # worker control message received
        if len(msg) in [1, 2]:

            command = msg.pop(0)

            # fires via `Worker.__init__`
            if command == PPP_READY:

                # not first command after startup
                if worker_ready:
                    log.critical('Late PPP_READY received - de-register Worker')
                    self.delete_worker(worker, True)
                    return

                service = msg.pop(0)

                log.info('PPP_READY received from "%s" worker: %s' % (
                    service, address
                ))

                # attach worker to service and mark as idle
                worker.service = self.require_service(service)

                self.worker_waiting(worker)

            elif command == PPP_HEARTBEAT:

                log.debug('PPP_HEARTBEAT / PING received from worker: %s' % address)

                if worker_ready:  # update expiration date
                    log.debug('update expiry')
                    worker.expiry = time.time() + HEARTBEAT_LIVENESS
                else:
                    self.delete_worker(worker, True)

            else:
                log.critical("Invalid message from worker: %s" % address)

        else:  # custom response

            log.debug('forwarding Worker (%s) response to Front End: %s' % (address, msg))
            self.frontend.send_multipart(msg)

            self.worker_waiting(worker)

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

            log.info('new request: %s | %s (from: %s)' % (service, function, ident))
            self.dispatch_request( self.require_service(function), frames )

    def dispatch_request(self, service, msg):

        assert (service is not None)

        if msg is not None:  # queue message in memory
            service.requests.append(msg)

        self.purge_workers()

        while service.waiting and service.requests:
            msg = service.requests.pop(0)
            new_worker = service.waiting.pop(0)

            # add the destination Worker Identity to the client request
            msg.insert(0, new_worker.address)

            log.debug('forwarding Client request (%s) to Worker BE: %s' % (msg, new_worker))

            self.waiting.remove(new_worker)

            # send message to backend
            self.backend.send_multipart(msg)

    def service_lookup(self, msg):

        service_name = msg[3].replace('mmi.', '')

        returncode = '501'
        returncode = '200' if service_name in self.services else '400'

        msg = msg[:2] + [service_name, returncode]

        # send response to client Front End router
        self.frontend.send_multipart(msg)

    def require_service(self, name):
        """ Locates the service (registers if necessary)
        """
        assert (name is not None)
        service = self.services.get(name)

        if not service:
            service = Service(name)
            self.services[name] = service
        return service

    def require_worker(self, address):
        """ Find or create `Worker` record
        """
        assert (address is not None)
        identity = binascii.hexlify(address)
        worker = self.workers.get(address)

        if not worker:  # create new `Worker`
            worker = Worker( identity, address )
            self.workers[address] = worker

            log.info("registering new worker: %s | %s" % (
                address, worker
            ))

        return worker

    def worker_waiting(self, worker):
        """This worker is now waiting for work.
        """
        log.debug('worker ready for work call: %s | %i' % (
                worker, len(self.waiting)
            ))

        # remove if its still on queue to be `ready`
        """
        if self.waiting:
            try:
                worker_idx = self.waiting.index(worker)
            except ValueError: pass
            else:  # continiue
                self.waiting.pop(worker_idx)
        """

        # Queue to broker and service waiting lists
        self.waiting.append(worker)
        worker.service.waiting.append(worker)

        worker.expiry = time.time() + HEARTBEAT_LIVENESS

        #self.dispatch_request(worker.service, None)

    def purge_workers(self):
        """ Look for & kill expired workers.
        Workers are oldest to most recent, so we stop at the first alive worker.
        """
        while self.waiting:
            w = self.waiting[0]
            log.debug('purge check: %s' % w)
            if w.expiry < time.time():
                log.warning("deleting expired worker: %s", w.address)
                self.waiting.pop(0)
                self.delete_worker(w, False)
            else:
                break

    def delete_worker(self, worker, disconnect):
        """Deletes worker from all data structures, and deletes worker."""
        assert worker is not None

        if disconnect:  # send re-connect msg to worker
            msg = [worker.address, PPP_RECONNECT]
            self.backend.send_multipart(msg)

        if worker.service:  # unregister from `Service` queue
            worker.service.waiting.remove(worker)

        if worker in self.waiting:
            self.waiting.remove(worker)

        # remove from registry
        self.workers.pop(worker.address)


