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
import threading
import zmq

HEARTBEAT_INTERVAL = 1  # seconds between a PPP_HEARTBEAT is send to the broker
HEARTBEAT_LIVENESS = 3  # 3 seconds until PPP_HEARTBEAT is expected from broker or considered dead

INTERVAL_INIT = 1
INTERVAL_MAX = 32

PPP_READY = "\x01"  # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat
PPP_RECONNECT = "\x03"  # Signals worker re-connect

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

    heartbeat_at = None

    heart = None

    sink = None

    def __init__(self, broker, service = 'echo'):

        self.context = zmq.Context(1)
        self.poller = zmq.Poller()
        self.service = service
        self.broker = broker

        # create client/connection UUID
        self.identity = "%04X-%04X" % (random.randint(0, 0x10000), random.randint(0, 0x10000))

        # PUSH socket to send broadcast/flow messages to
        self.sink = self.context.socket(zmq.PUSH)
        self.sink.connect('tcp://localhost:5558')

        # DEALER socket to get jobs from/to
        self.setup_worker_socket()

        self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL

        # init heartbeat
        self.heart = threading.Thread(target=self.setup_heartbeat)
        self.heart.daemon = True
        self.heart.start()

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

    def setup_heartbeat(self):

        log.info('setup_heartbeat')

        time_run = 0

        while True:

            # sync the time between pings due the GIL
            last_ping = time.time() - time_run
            if last_ping < HEARTBEAT_INTERVAL:
                time_sleep = HEARTBEAT_INTERVAL - last_ping
            else:
                time_sleep = HEARTBEAT_INTERVAL

            time.sleep(time_sleep)

            time_run = time.time()

            if not self.worker:
                log.warn('NO Worker to sent PPP_HEARTBEAT to')
                continue

            self.worker.send(PPP_HEARTBEAT)

            self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL

            log.debug("Worker heartbeat SENT")

    def recv(self, reply=None):
        """Send reply, if any, to broker and wait for next request."""
        assert reply is not None or not self.expect_reply

        if reply is not None:
            # send response to client
            assert self.reply_to is not None
            reply = [self.reply_to, ''] + reply
            self.worker.send_multipart(reply)

        self.expect_reply = True

        loop = 0

        while True:
            loop += 1

            try:  # poll broker socket
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

                log.debug('FE request')

                # reset heartbeat timeout
                self.liveness = HEARTBEAT_LIVENESS
                self.interval = INTERVAL_INIT

                if len(frames) == 1 and frames[0] == PPP_HEARTBEAT:

                    log.debug("Queue heartbeat RECEIVED")

                elif len(frames) == 1 and frames[0] == PPP_RECONNECT:

                    log.warning("Queue re-connect RECEIVED")

                    self.reconnect_broker()

                elif len(frames) == 6:

                    ident, x, service, function, expiration, request = frames

                    log.debug("New Request: %s" % frames)

                    self.reply_to = ident

                    return frames

                else:
                    log.critical("Invalid message: %s" % frames)
                    break

            else:  # no response received from router socket

                log.warning('NO response / heartbeat')

                self.liveness -= 1
                if self.liveness <= 1:

                    log.warn("Heartbeat DEAD (%i seconds) - Reconnecting to Router in %0.2fs" % (
                        HEARTBEAT_LIVENESS, self.interval
                    ))
                    time.sleep(self.interval)

                    if self.interval < INTERVAL_MAX:
                        self.interval *= 2
                    else:
                        self.interval = INTERVAL_INIT

                    self.reconnect_broker()

        log.warn('Keyboard Interrupt received, killing worker')
        return None

    def reconnect_broker(self):

        # create new socket to broker
        self.setup_worker_socket()

        # reset heartbeat timeout
        self.liveness = HEARTBEAT_LIVENESS

