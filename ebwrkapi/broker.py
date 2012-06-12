""" Task Router

The primary function is it to route Tasks between the front and Backend socket end points and
provide Service Discovery of provided Worker functions. The seperate Sockets allow to bridge
internal / external networks.

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
PPP_REPLY = "\x04"  # Signals worker message

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

    uuid = None
    identity = None  # hex Identity of worker
    address = None  # routing address
    expiry = None  # expires at this point - unless heartbeat
    service = None  # owning service name if known

    def __init__(self, identity, address, uuid):
        self.identity = identity
        self.address = address
        self.uuid = uuid
        self.expiry = time.time() + HEARTBEAT_LIVENESS


class EBBroker(object):

    heart = None

    def __init__(self):

        self.services = {}  # `Worker` objects grouped by Service to allow for faster discovery

        self.workers = {}  # index of all `Worker` objects by address

        self.waiting = []  # direct access to check heartbeat status of Workers

        self.heartbeat_at = time.time() + 1e-3 * HEARTBEAT_INTERVAL

        self.context = zmq.Context(1)

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

        heartbeat_socket = self.context.socket(zmq.PUSH)

        heartbeat_socket.connect('tcp://localhost:5556')

        while True:

            if self.heartbeat_at and time.time() < self.heartbeat_at:
                time.sleep(0.001)
                continue

            log.debug('attempting to ping %i worker' % len(self.waiting))

            self.purge_workers()

            for worker in self.waiting:

                log.debug('sending PPP_HEARTBEAT as PPP_REPLY to Worker %s' % worker)

                msg = [PPP_REPLY, worker.uuid, worker.address, PPP_HEARTBEAT]

                heartbeat_socket.send_multipart(msg)

            self.heartbeat_at = time.time() + 1e-3 * HEARTBEAT_INTERVAL

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

            # poll socket for request message up to HEARTBEAT_INTERVAL seconds
            socks = dict(poller.poll(HEARTBEAT_INTERVAL))

            # handle worker activity on backend
            if self.backend in socks and socks[self.backend] == zmq.POLLIN:

                log.debug('worker BE activity')
                self.process_worker()

            # Client request received - forward it to the backend router
            if self.frontend in socks and socks[self.frontend] == zmq.POLLIN:

                log.debug('client FE activity')
                self.process_client()

    def process_worker(self):
        """Process Worker Message"""

        # read request from BE
        frames = self.backend.recv_multipart()

        assert len(frames) >= 1

        log.debug('process worker msg: %s' % frames)

        # parse response
        address = frames[0]
        worker_uuid = frames[2]
        msg = frames[1:]

        # worker had been registered already / active session open
        worker_registered = worker_uuid in self.workers

        # worker control message received
        if not msg:
            log.debug('empty response')
            return

        command = msg.pop(0)
        worker_uuid = msg.pop(0)

        # fires via `Worker.__init__`
        if command == PPP_READY:

            # not first command after startup
            if worker_registered:
                log.critical('Late PPP_READY received - de-register Worker')
                #self.disconnect_worker( address, worker_uuid )
                worker = self.workers[worker_uuid]
                worker.address = address
                self.worker_waiting(worker)
                return

            service = msg.pop(0)

            log.info('PPP_READY received from "%s" worker: %s' % (
                service, worker_uuid
            ))

            # create `Worker` object
            worker = self.require_worker(
                address, worker_uuid
            )

            # attach worker to service and mark as idle
            worker.service = self.require_service(service)

            self.worker_waiting(worker)

        elif command == PPP_HEARTBEAT:

            log.debug('PPP_HEARTBEAT received from worker: %s' % worker_uuid)

            # go by boardcasted address
            #worker.address = msg.pop(0)

            if not worker_registered:

                log.warn('PPP_HEARTBEAT received but Worker not ready yet')
                self.disconnect_worker( address, worker_uuid )

            else:

                worker = self.workers[worker_uuid]
                worker.expiry = time.time() + HEARTBEAT_LIVENESS

        elif command == PPP_REPLY:

            if not worker_registered:

                log.warn('PPP_REPLY received but Worker not registered yet')
                self.disconnect_worker( address, worker_uuid )

            else:

                worker = self.workers[worker_uuid]

                log.debug('Route PPP_REPLY to Worker: %s' % msg)

                self.backend.send_multipart(msg)

        elif msg:

            log.warn('Invalid worker message received - attempt to send to client: %s' % msg)

            self.frontend.send_multipart(msg)

    def process_client(self):

        # read request as multi part message from FE router socket
        frames = self.frontend.recv_multipart()

        assert len(frames) >= 2  # service name + request body

        log.debug('process_client: %s' % frames)

        # parse request
        ident, x, service, function, expiration, request = frames

        # discared if request is expired
        if int(expiration) < int(round((time.time() * 1000))):
            log.warn('request expired at: %s' % expiration)
            return

        if function.startswith('mmi.'):

            log.debug('internal service call')
            self.service_lookup(frames)

        else:

            log.info('new request: %s | %s' % (function, service))
            self.dispatch_request( self.require_service(function), frames )

    def dispatch_request(self, service, msg):

        assert (service is not None)

        self.purge_workers()

        if service.waiting:
            log.debug("dispatch request: %s" % service.waiting)
        else:
            log.warn('no Worker waiting for Worker - discarding request')

            return self.frontend.send_multipart(msg)

        if msg is not None:  # queue message in memory
            service.requests.append(msg)

        while service.waiting and service.requests:

            msg = service.requests.pop(0)

            new_worker = service.waiting.pop(0)

            log.debug('forwarding Client request (%s) to Worker BE: %s' % (msg, new_worker))

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
            log.info('registering new Service: %s' % name)
            service = Service(name)
            self.services[name] = service
        return service

    def require_worker(self, address, worker_uuid):
        """ Find or create `Worker` record
        """
        assert (address is not None)
        worker = self.workers.get(worker_uuid)

        if not worker:  # create new `Worker`
            worker = Worker(
                binascii.hexlify(address),
                address,
                worker_uuid
            )
            self.workers[worker_uuid] = worker

            log.info("registering new Worker: %s | %s" % ( worker.uuid, worker ))

        return worker

    def worker_waiting(self, worker):
        """This worker is now waiting for work.
        """
        log.debug('worker ready for work call: %s | %i' % (
                worker, len(self.waiting)
            ))

        # Queue to broker and service waiting lists
        if worker not in self.waiting:
            self.waiting.append(worker)

        if worker not in worker.service.waiting:
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
                log.warning("deleting expired worker: %s", w.uuid)
                self.waiting.pop(0)
                self.delete_worker(w, False)
            else:
                break

    def disconnect_worker(self, worker_address, worker_uuid):

        log.warn('send Worker PPP_RECONNECT to %s' % [worker_address, ])

        control_socket = self.context.socket(zmq.PUSH)
        control_socket.connect('tcp://localhost:5556')
        msg = [PPP_REPLY, worker_uuid, worker_address, PPP_RECONNECT]
        control_socket.send_multipart(msg)
        control_socket.close()

    def delete_worker(self, worker, disconnect = False):
        """Deletes worker from all data structures, and deletes worker."""
        assert worker is not None

        if disconnect:  # send re-connect msg to worker
            self.disconnect_worker(
                    worker.address, worker.uuid
                )

        # unregister from `Service` queue
        if worker.service:
            worker.service.waiting.remove(worker)

        while True:
            if worker in self.waiting:
                self.waiting.remove(worker)
            else: break

        # remove from registry
        self.workers.pop(worker.uuid)

