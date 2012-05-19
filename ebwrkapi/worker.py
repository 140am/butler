"""
Example Usage:

worker = ebwrkapi.EBWorker("tcp://localhost:5556", 'video.cut')

reply = None
while True:
    request = worker.recv(reply)
    if not request:
        break  # worker was interrupted / stopped
"""

import logging
import time
import random
import zmq

HEARTBEAT_LIVENESS = 3  # seconds until heartbeat is expected / queue is considered disconnected
HEARTBEAT_INTERVAL = 1
INTERVAL_INIT = 1
INTERVAL_MAX = 32

PPP_READY = "\x01"      # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat

log = logging.getLogger(__name__)


class EBWorker(object):

    broker = None
    context = None
    poller = None
    service = None
    worker = None
    identity = None

    liveness = HEARTBEAT_LIVENESS
    interval = INTERVAL_INIT

    expect_reply = False
    reply_to = None

    heartbeat_at = time.time() + HEARTBEAT_INTERVAL

    def __init__(self, broker, service = 'echo'):

        self.context = zmq.Context(1)
        self.poller = zmq.Poller()
        self.service = service
        self.broker = broker

        # PUSH socket to send broadcast/flow messages to
        self.sink = self.context.socket(zmq.PUSH)
        #self.sink.connect('tcp://localhost:5558')

        # create client/connection UUID
        self.identity = "%04X-%04X" % (random.randint(0, 0x10000), random.randint(0, 0x10000))

        # DEALER socket to get jobs from/to
        self.setup_worker_socket()

    def setup_worker_socket(self):
        """Helper function that returns a new configured socket
           connected to the queue"""

        # close existing socket
        if self.worker:
            self.poller.unregister(self.worker)
            self.worker.close()

        # create DEALER socket
        self.worker = self.context.socket(zmq.XREQ)

        # set the `identity` UUID as the worker identify
        self.worker.setsockopt(zmq.IDENTITY, self.identity)
        self.worker.setsockopt(zmq.LINGER, 0)
        self.worker.setsockopt(zmq.HWM, 0)

        # register worker socket with poller
        self.poller.register(self.worker, zmq.POLLIN)

        # connec to ROUTER socket
        self.worker.connect(self.broker)

        # send `PPP_READY` message to Router
        log.info('sent PPP_READY - register: %s' % self.service)
        self.worker.send_multipart([PPP_READY, self.service])

    def recv(self, reply=None):
        """Send reply, if any, to broker and wait for next request."""
        assert reply is not None or not self.expect_reply

        if reply is not None:
            # send response to ACK accepted request/task
            assert self.reply_to is not None
            reply = [self.reply_to, ''] + reply
            self.worker.send_multipart(reply)

        self.expect_reply = True

        while True:

            try:  # poll broker socket for a reply
                socks = dict(self.poller.poll(HEARTBEAT_INTERVAL * 1000))
            except KeyboardInterrupt:
                log.warn('Keyboard Interrupted')
                break  # interrupted

            # Handle worker activity on backend
            if socks.get(self.worker) == zmq.POLLIN:

                #  Get message
                #  - 3-part envelope + content = client request
                #  - 1-part HEARTBEAT = heartbeat

                frames = self.worker.recv_multipart()

                # reset heartbeat timeout
                self.liveness = HEARTBEAT_LIVENESS
                self.interval = INTERVAL_INIT

                if len(frames) == 1 and frames[0] == PPP_HEARTBEAT:

                    log.debug("Queue heartbeat RECEIVED")

                elif len(frames) == 6:

                    ident, x, service, function, expiration, request = frames

                    log.debug("New Request: %s" % frames)

                    self.reply_to = ident

                    # send call back to response sink
                    self.sink.send('ACCEPTED Job: %s' % request)

                    return frames

                else:
                    log.critical("Invalid message: %s" % frames)
                    break

            else:  # no response received from router socket

                self.liveness -= 1
                if self.liveness == 1:

                    log.warn("Heartbeat DEAD (%i seconds) - Reconnecting to Router in %0.2fs" % (
                        HEARTBEAT_LIVENESS, self.interval
                    ))
                    time.sleep(self.interval)

                    if self.interval < INTERVAL_MAX:
                        self.interval *= 2
                    else:
                        self.interval = INTERVAL_INIT

                    # create new socket to broker
                    self.setup_worker_socket()

                    # reset heartbeat timeout
                    self.liveness = HEARTBEAT_LIVENESS

            # send max 1 heartbeat per second
            if time.time() > self.heartbeat_at:

                self.worker.send(PPP_HEARTBEAT)
                log.debug("Worker heartbeat SENT")
                self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL

        log.warn('Keyboard Interrupt received, killing worker')
        return None

