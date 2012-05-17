import logging
import time
import random
import zmq

HEARTBEAT_LIVENESS = 3  # seconds until heartbeat is expected from router
HEARTBEAT_INTERVAL = 1
INTERVAL_INIT = 1
INTERVAL_MAX = 32

PPP_READY = "\x01"      # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat

logging.basicConfig( format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s' )
log = logging.getLogger('worker')
log.setLevel(logging.DEBUG)


def setup_worker_socket(context, poller):
    """Helper function that returns a new configured socket
       connected to the queue"""

    # create client/connection UUID
    identity = "%04X-%04X" % (random.randint(0, 0x10000), random.randint(0, 0x10000))

    # create DEALER socket
    worker = context.socket(zmq.XREQ)

    # set the `identity` UUID as the worker identify
    worker.setsockopt(zmq.IDENTITY, identity)

    # register worker socket with poller
    poller.register(worker, zmq.POLLIN)

    # connec to ROUTER socket
    worker.connect("tcp://localhost:5556")

    # send `PPP_READY` message to Router
    log.info('sent PPP_READY')
    worker.send(PPP_READY)

    return worker

context = zmq.Context(1)

poller = zmq.Poller()

liveness = HEARTBEAT_LIVENESS
interval = INTERVAL_INIT

heartbeat_at = time.time() + HEARTBEAT_INTERVAL

# DEALER socket to get jobs from/to
worker = setup_worker_socket(context, poller)

# PUSH socket to send broadcast/flow messages to
sink = context.socket(zmq.PUSH)
sink.connect("tcp://localhost:5558")

cycles = 0
while True:

    socks = dict(poller.poll(HEARTBEAT_INTERVAL * 1000))

    # Handle worker activity on backend
    if socks.get(worker) == zmq.POLLIN:

        #  Get message
        #  - 3-part envelope + content = client request
        #  - 1-part HEARTBEAT = heartbeat

        frames = worker.recv_multipart()

        if not frames:
            log.critical('empty msg')
            break  # Interrupted

        if len(frames) == 6:

            ident, x, service, function, expiration, request = frames

            log.info("New Request: %s" % frames)

            # send response to ACK accepted request/task
            worker.send_multipart(frames)

            time.sleep(60)  # Do some heavy work

            # send call back to response sink
            sink.send('COMPLETED Job: %s' % request)

            # reset heartbeat timeout
            liveness = HEARTBEAT_LIVENESS

        elif len(frames) == 1 and frames[0] == PPP_HEARTBEAT:

            log.debug("Queue heartbeat RECEIVED")
            liveness = HEARTBEAT_LIVENESS

        else:
            log.critical("Invalid message: %s" % frames)

        interval = INTERVAL_INIT

    else:  # no response received from router socket

        liveness -= 1
        if liveness == 0:
            log.warn("Heartbeat DEAD (%i seconds) - Reconnecting to Router in %0.2fs" % (
                HEARTBEAT_LIVENESS, interval
            ))
            time.sleep(interval)

            if interval < INTERVAL_MAX:
                interval *= 2
            else:
                interval = INTERVAL_INIT

            poller.unregister(worker)
            worker.setsockopt(zmq.LINGER, 0)
            worker.close()

            worker = setup_worker_socket(context, poller)

            liveness = HEARTBEAT_LIVENESS

    # send max 1 heartbeat per second
    if time.time() > heartbeat_at:

        heartbeat_at = time.time() + HEARTBEAT_INTERVAL
        log.debug("Worker heartbeat SENT")
        worker.send(PPP_HEARTBEAT)

