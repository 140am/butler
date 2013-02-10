""" Task Router

The primary function is it to route Tasks between the front and Backend socket end points and
provide Service Discovery of provided Worker functions. The seperate Sockets allow to bridge
internal / external networks.

Example Usage:

router = butler.Router()
router.frontend.bind("tcp://*:5555")
router.backend.bind("tcp://*:5556")
router.run()
"""

import time
import datetime
import gevent
import logging
import zmq.green as zmq

HEARTBEAT_INTERVAL = 1000  # msec between heartbeats sent out
HEARTBEAT_LIVENESS = 3  # seconds until heartbeat is expected / worker is considered dead

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
        self.updated_at = datetime.datetime.now()
        self.name = name
        self.requests = []
        self.waiting = []

    def __repr__(self):
        return '<Service - %s>' % self.name


class Worker(object):
    """an idle or active Worker instance"""

    address = None  # routing address
    expiry = None  # expires at this point - unless heartbeat
    service = None  # owning service name if known

    def __init__(self, address, hearbeat_expiration):
        self.address = address
        self.expiry = time.time() + hearbeat_expiration

    def __repr__(self):
        return '<Worker - %s>' % self.address


class Router(object):

    heart = None

    def __init__(self):

        self.services = {}  # `Worker` objects grouped by Service to allow for faster discovery

        self.workers = {}  # index of all `Worker` objects by address

        self.waiting = []  # direct access to check heartbeat status of Workers

        self.heartbeat_timeout = HEARTBEAT_LIVENESS

        self.heartbeat_at = time.time() + 1e-3 * self.heartbeat_timeout

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

        log.debug('Setup Heartbeat')

        heartbeat_socket = self.context.socket(zmq.PUSH)
        heartbeat_socket.connect('tcp://localhost:5556')

        while True:

            if time.time() < self.heartbeat_at:
                gevent.sleep(0.1)
                continue

            log.debug('attempting to ping %i worker' % len(self.waiting))

            self.purge_workers()

            for worker in self.waiting:

                msg = [PPP_REPLY, worker.address, PPP_HEARTBEAT]
                heartbeat_socket.send_multipart(msg)

            self.heartbeat_at = time.time() + 1e-3 * HEARTBEAT_INTERVAL

    def poll_sockets(self):

        while True:

            # ignore FE / client requests if no workers are connected to the backend (no PPP_READY received)
            if not len(self.workers):
                log.warn('No Worker available - Waiting for Worker to join on BE')
                poller = self.pull_backends
            else:
                poller = self.poll_both

            gevent.sleep(0)

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

    def run(self):

        # setup router Heartbeat
        gevent.spawn(self.setup_heartbeat)

        gevent.spawn(self.poll_sockets).join()

    def process_worker(self):
        """Process Service Worker Message"""

        # read request from BE
        frames = self.backend.recv_multipart()

        assert len(frames) >= 1

        log.debug('process worker msg: %s' % frames)

        # parse response
        worker_uuid = frames[0]
        msg = frames[1:]

        # worker control message received
        if not msg:
            log.debug('empty response')
            return

        command = msg.pop(0)

        # fires via `Worker.__init__`
        if command == PPP_READY:

            # worker had been registered already / active session open
            worker_registered = worker_uuid in self.workers

            # not first command after startup
            if worker_registered:
                worker = self.workers[worker_uuid]
                log.critical('Late PPP_READY received - de-register Worker: %s' % worker)
                self.delete_worker(worker, disconnect = True)
                return

            service = msg.pop(0)

            log.debug('PPP_READY received from "%s" worker: %s' % (
                service, worker_uuid
            ))

            # create `Worker` object
            worker = self.require_worker(worker_uuid)

            # attach worker to service and mark as idle
            worker.service = self.require_service(service)

            self.worker_waiting(worker)

        elif command == PPP_HEARTBEAT:

            # worker had been registered already / active session open
            worker_registered = worker_uuid in self.workers

            log.debug('PPP_HEARTBEAT received from worker: %s' % worker_uuid)

            if not worker_registered:

                log.warn('PPP_REPLY received but Worker not registered yet: %s' % worker_uuid)
                self.disconnect_worker( worker_uuid )

            else:

                worker = self.workers[worker_uuid]

                worker.expiry = time.time() + self.heartbeat_timeout

        elif command == PPP_REPLY:

            # worker had been registered already / active session open
            worker_registered = worker_uuid in self.workers

            # PPP_REPLY came from worker server
            if worker_registered:

                worker = self.workers[worker_uuid]

                log.debug('Worker PPP_REPLY received from %s - forward to Client %s' % (
                    worker_uuid, msg
                ))

                self.frontend.send_multipart(msg)

                self.worker_waiting(worker)

            # PPP_REPLY should go to a registered Worker server
            elif frames[2] in self.workers:

                worker = self.workers[frames[2]]

                log.debug('Route PPP_REPLY to Worker: %s' % msg)

                self.backend.send_multipart(msg)

            else:
                log.warn('Unknown PPP_REPLY received - attempting: %s' % msg)

                # send message to both FE and BE
                self.frontend.send_multipart(msg)
                self.backend.send_multipart(msg)

        elif msg:

            log.info('Unknown Backend Request received: %s' % msg)

    def process_client(self):

        # read request as multi part message from FE router socket
        frames = self.frontend.recv_multipart()

        assert len(frames) >= 2  # service name + request body

        log.debug('process client request: %s' % frames)

        # parse request
        ident, null, request_id, service_name, request_expiration, request = frames

        # discared if request is expired
        if int(request_expiration) < int(round((time.time() * 1000))):
            log.warn('request expired at: %s' % request_expiration)
            return

        if service_name.startswith('mmi.'):

            log.debug('internal service call')
            self.service_lookup(frames)

        else:
            log.info('new request: %s | %s' % (service_name, request_id))

            self.dispatch_request(
                self.require_service(service_name), frames
            )

    def dispatch_request(self, service, msg):

        assert (service is not None)

        self.purge_workers()

        if service.waiting:
            log.debug("dispatch request: %s" % service.waiting)
        else:
            log.warn('no Worker available for "%s" - discarding request' % service)
            empty_msg = msg[:2] + ['404', ]
            return self.frontend.send_multipart(empty_msg)

        if msg is not None:  # queue message in memory
            service.requests.append(msg)

        while service.waiting and service.requests:

            msg = service.requests.pop(0)

            new_worker = service.waiting.pop(0)

            log.debug('forwarding Client request Worker BE: %s' % new_worker)

            # add the Worker address to the request to route the message
            msg.insert(0, new_worker.address)

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

    def require_worker(self, worker_uuid):
        """ Find or create `Worker` record
        """
        assert (worker_uuid is not None)
        worker = self.workers.get(worker_uuid)

        if not worker:  # create new `Worker`
            worker = Worker(worker_uuid, self.heartbeat_timeout)
            self.workers[worker_uuid] = worker

            log.info("registering new Worker: %s | %s" % ( worker.address, worker ))

        return worker

    def worker_waiting(self, worker):
        """This worker is now waiting for work.
        """
        log.debug('worker ready for work call: %s | %i' % (
                worker, len(self.waiting)
            ))

        # Queue to router and service waiting lists
        if worker not in self.waiting:
            self.waiting.append(worker)

        if worker not in worker.service.waiting:
            worker.service.updated_at = datetime.datetime.now()
            worker.service.waiting.append(worker)

        worker.expiry = time.time() + self.heartbeat_timeout

    def purge_workers(self):
        """ Look for & kill expired workers.
        Workers are oldest to most recent.
        """

        for worker in self.waiting:
            if worker.expiry < time.time():
                log.warning("deleting expired worker: %s" % worker.address)
                self.waiting.remove(worker)
                self.delete_worker(worker, False)

        for service_name in self.services.keys():
            if not self.services[service_name].waiting:
                if self.services[service_name].updated_at <= (
                    datetime.datetime.now() - datetime.timedelta(hours = 1)
                ):
                    log.warn('deleting expired Service: %s' % service_name)
                    self.services.pop(service_name)

    def disconnect_worker(self, worker_address):

        log.warn('sent Worker PPP_RECONNECT to: %s' % worker_address)

        control_socket = self.context.socket(zmq.PUSH)
        control_socket.connect('tcp://localhost:5556')
        msg = [PPP_REPLY, worker_address, PPP_RECONNECT]
        control_socket.send_multipart(msg)
        control_socket.close()

    def delete_worker(self, worker, disconnect = False):
        """Deletes worker from all data structures, and deletes worker."""

        assert worker is not None

        if worker.service is not None:
            if worker in worker.service.waiting:
                worker.service.waiting.remove(worker)

        while True:
            if worker in self.waiting:
                self.waiting.remove(worker)
            else: break

        # remove from registry
        self.workers.pop(worker.address)

        if disconnect:  # send re-connect msg to worker
            self.disconnect_worker(worker.address)
