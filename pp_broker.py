""" The Job Broker accepts messages from the `Client` and shall prepend a message part containing the identity of the originating peer to the message before passing it to the `Worker`.

It listens on TCP Port:

    5555 : Client Connections to send Commands
    5556 : Workerserver
"""

from collections import OrderedDict
import time
import logging
import zmq
import cjson

HEARTBEAT_LIVENESS = 3     # 3..5 is reasonable
HEARTBEAT_INTERVAL = 1.0   # Seconds
REQUEST_LIFESPAN = 1  # seconds

PPP_READY = "\x01"  # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat
PPP_BUSY = "\x03"  # Signals worker busy state

logging.basicConfig( format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s' )
log = logging.getLogger('broker')
log.setLevel(logging.DEBUG)


class Worker(object):
    def __init__(self, address):
        self.address = address
        self.expiry = time.time() + HEARTBEAT_INTERVAL * HEARTBEAT_LIVENESS


class WorkerQueue(object):
    """ Queue which registered WorkerServer gets added to and
    retrieved from. Using the Least Recently Used algorithm via a python dict.
    """

    def __init__(self):
        self.queue = OrderedDict()

    def ready(self, worker):
        self.queue.pop(worker.address, None)
        self.queue[worker.address] = worker

    def purge(self):
        """Look for & kill expired workers."""
        t = time.time()

        expired = []
        for address, worker in self.queue.iteritems():
            if t < worker.expiry:  # Worker is alive (seen recently)
                break
            expired.append(address)

        for address in expired:
            log.warn("Idle worker expired: %s" % address)
            self.queue.pop(address, None)

    def next(self):  # return oldest entry in list
        address, worker = self.queue.popitem(False)
        log.info('using WorkerServer: %s | %s | %s' % (address, worker, len(self.queue)))
        return address


context = zmq.Context(1)

frontend = context.socket(zmq.ROUTER)  # Front End
frontend.setsockopt(zmq.HWM, 0)
frontend.bind("tcp://*:5555")  # For clients

backend = context.socket(zmq.ROUTER)  # Back End
backend.setsockopt(zmq.HWM, 0)
backend.bind("tcp://*:5556")  # For workers

pull_backends = zmq.Poller()
pull_backends.register(backend, zmq.POLLIN)

poll_both = zmq.Poller()
poll_both.register(frontend, zmq.POLLIN)
poll_both.register(backend, zmq.POLLIN)

# Least Recently Used WorkerServer queue
workers = WorkerQueue()

heartbeat_at = time.time() + HEARTBEAT_INTERVAL

""" TODO: put into thread
# Send heartbeats to idle workers if it's time
if time.time() >= heartbeat_at:
    for worker in workers.queue:
        msg = [worker, PPP_HEARTBEAT]
        backend.send_multipart(msg)
    heartbeat_at = time.time() + HEARTBEAT_INTERVAL
"""

while True:

    # ignore FE / client requests if no workers are connected to the backend (no PPP_READY received)
    if not len(workers.queue):
        log.warn('No Worker available - Waiting for Worker to join on BE')
        poller = pull_backends
    else:
        poller = poll_both

    socks = dict(poller.poll(HEARTBEAT_INTERVAL * 1000))

    # Handle worker activity on backend
    if socks.get(backend) == zmq.POLLIN:

        log.debug('worker BE activity')

        frames = backend.recv_multipart()
        if not frames:
            log.critical('worker BE - empty request received - SHUTTING DOWN')
            continue

        # Get Worker Identity
        address = frames[0]

        # Validate control message, or echo request to client
        msg = frames[1:]

        # control message received
        if len(msg) == 1:

            if msg[0] == PPP_READY:
                workers.ready(Worker(address))
                log.info('PPP_READY received from worker: %s' % address)

                msg = [address, PPP_HEARTBEAT]
                backend.send_multipart(msg)

            elif msg[0] == PPP_HEARTBEAT:
                workers.ready(Worker(address))
                log.info('PPP_HEARTBEAT received from worker: %s' % address)

                msg = [address, PPP_HEARTBEAT]
                backend.send_multipart(msg)

            else:
                log.critical("Invalid message from worker: %s" % address)

        # client request / echo request to frontend
        else:
            # decode json request response
            response = cjson.decode(msg[5])

            # modify request body to have updated attributes
            response['worker'] = address

            # encode data structure to string
            msg[5] = cjson.encode(response)

            log.info('forwarding Worker (%s) response to Front End: %s' % (address, msg))
            frontend.send_multipart(msg)

    # Client request received - forward it to the backend router
    if socks.get(frontend) == zmq.POLLIN:

        log.debug('client FE activity')

        # read request as multi part message
        frames = frontend.recv_multipart()
        if not frames:
            log.critical('Invalid Client request')
            break

        # parse request
        ident, x, service, function, expiration, request = frames

        # discared if request expired
        request_age = int(time.time()) - int(expiration)
        if request_age >= REQUEST_LIFESPAN:
            log.warning('request expired %i seconds ago' % request_age)
            continue

        log.debug('new request: %s | %s (from: %s)' % (service, function, ident))

        # get worker from queue
        new_worker = workers.next()

        # add the destination Worker Identity to the client request
        frames.insert(0, new_worker)

        log.info('forwarding Client request (%s) to Worker BE: %s' % (frames, new_worker))

        # send message to backend
        backend.send_multipart(frames)

    workers.purge()

