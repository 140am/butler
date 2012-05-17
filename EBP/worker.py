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

log = logging.getLogger(__name__)


class EBWorker(object):

    HEARTBEAT_LIVENESS = 3

    broker = None
    context = None
    service = None

    liveness = HEARTBEAT_LIVENESS
    interval = INTERVAL_INIT

    worker = None  # socket to broker
    heartbeat_at = time.time() + HEARTBEAT_INTERVAL

    def __init__(self, broker):

        self.context = zmq.Context(1)
        self.poller = zmq.Poller()

        # PUSH socket to send broadcast/flow messages to
        self.sink = self.context.socket(zmq.PUSH)
        self.sink.connect(broker)

        # DEALER socket to get jobs from/to
        self.setup_worker_socket()

    def setup_worker_socket(self):
        """Helper function that returns a new configured socket
           connected to the queue"""

        # create client/connection UUID
        identity = "%04X-%04X" % (random.randint(0, 0x10000), random.randint(0, 0x10000))

        # create DEALER socket
        self.worker = self.context.socket(zmq.XREQ)

        # set the `identity` UUID as the worker identify
        self.worker.setsockopt(zmq.IDENTITY, identity)

        # register worker socket with poller
        self.poller.register(self.worker, zmq.POLLIN)

        # connec to ROUTER socket
        self.worker.connect("tcp://localhost:5556")

        # send `PPP_READY` message to Router
        log.info('sent PPP_READY')
        self.worker.send(PPP_READY)

    def run(self):

        while True:

            socks = dict(self.poller.poll(HEARTBEAT_INTERVAL * 1000))

            # Handle worker activity on backend
            if socks.get(self.worker) == zmq.POLLIN:

                #  Get message
                #  - 3-part envelope + content = client request
                #  - 1-part HEARTBEAT = heartbeat

                frames = self.worker.recv_multipart()

                if not frames:
                    log.critical('empty msg')
                    break  # Interrupted

                if len(frames) == 6:

                    ident, x, service, function, expiration, request = frames

                    log.info("New Request: %s" % frames)

                    # send response to ACK accepted request/task
                    self.worker.send_multipart(frames)

                    time.sleep(10)  # Do some heavy work

                    # send call back to response sink
                    self.sink.send('COMPLETED Job: %s' % request)

                    self.liveness = HEARTBEAT_LIVENESS

                elif len(frames) == 1 and frames[0] == PPP_HEARTBEAT:

                    log.debug("Queue heartbeat RECEIVED")

                else:
                    log.critical("Invalid message: %s" % frames)

                self.interval = INTERVAL_INIT

            else:  # no response received from router socket

                self.liveness -= 1
                if self.liveness == 0:

                    log.warn("Heartbeat DEAD (%i seconds) - Reconnecting to Router in %0.2fs" % (
                        HEARTBEAT_LIVENESS, self.interval
                    ))
                    time.sleep(self.interval)

                    if self.interval < INTERVAL_MAX:
                        self.interval *= 2
                    else:
                        self.interval = INTERVAL_INIT

                    # unregister and close socket
                    self.poller.unregister(self.worker)
                    self.worker.setsockopt(zmq.LINGER, 0)
                    self.worker.close()

                    # create new socket to broker
                    self.worker = self.setup_worker_socket()

            # reset heartbeat timeout
            self.liveness = HEARTBEAT_LIVENESS

            # send max 1 heartbeat per second
            if time.time() > self.heartbeat_at:

                self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL
                log.debug("Worker heartbeat SENT")
                self.worker.send(PPP_HEARTBEAT)

