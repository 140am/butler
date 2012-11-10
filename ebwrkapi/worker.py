"""
Example Usage:

worker = ebwrkapi.EBWorker("tcp://localhost:5556", 'video.cut')

reply = None
while True:
    request = worker.recv(reply)
    if not request:
        break  # worker was interrupted / stopped
"""

import time
import uuid
import json
import sys
import cPickle
import gevent
import logging

from gevent_zeromq import zmq

HEARTBEAT_INTERVAL = 1  # seconds between a PPP_HEARTBEAT is send to the broker
HEARTBEAT_LIVENESS = 3  # 3 seconds until PPP_HEARTBEAT is expected from broker or considered dead

INTERVAL_INIT = 0
INTERVAL_MAX = 32

PPP_READY = "\x01"  # Signals worker is ready
PPP_HEARTBEAT = "\x02"  # Signals worker heartbeat
PPP_RECONNECT = "\x03"  # Signals worker re-connect
PPP_REPLY = "\x04"  # Signals worker reply

log = logging.getLogger(__name__)


class EBWorker(object):

    broker = None
    context = None
    poller = None
    service = None
    worker = None

    liveness = HEARTBEAT_LIVENESS
    interval = INTERVAL_INIT

    expect_reply = False
    reply_to = None

    heartbeat_at = None

    heart = None

    sink = None

    def __init__(self, bind_address, service = 'echo'):

        self.context = zmq.Context(1)

        self.poller = zmq.Poller()

        self.service = service

        self.bind_address = bind_address

        self.uuid = str(uuid.uuid4())

        self.rpc_registry = {}

        # PUSH socket to send broadcast/flow messages to
        self.sink = self.context.socket(zmq.PUSH)
        self.sink.connect('tcp://localhost:5558')

        # DEALER socket to get jobs from/to
        self.setup_worker_socket()

        # init heartbeat
        self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL

    def setup_worker_socket(self):
        """Helper function that returns a new configured socket
           connected to the queue"""

        # close existing socket
        if self.worker:
            log.warn('re-connect socket')
            self.poller.unregister(self.worker)
            self.worker.close()

        # create DEALER socket
        self.worker = self.context.socket(zmq.DEALER)
        self.worker.setsockopt(zmq.HWM, 0)

        self.worker.setsockopt(zmq.IDENTITY, self.uuid)

        # register worker socket with poller
        self.poller.register(self.worker, zmq.POLLIN)

        # connec to ROUTER socket
        self.worker.connect(self.bind_address)

        # send `PPP_READY` message to Router
        self.signal_ready()

    def setup_heartbeat(self):

        log.info('setup_heartbeat with %s' % self.bind_address)

        time_run = 0

        heartbeat_socket = self.context.socket(zmq.PUSH)
        heartbeat_socket.connect(self.bind_address)

        while True:

            # sync the time between pings due the GIL
            last_ping = time.time() - time_run
            if last_ping < HEARTBEAT_INTERVAL:
                time_sleep = HEARTBEAT_INTERVAL - last_ping
            else:
                time_sleep = HEARTBEAT_INTERVAL
            time_run = time.time()
            gevent.sleep(time_sleep)

            # send the msg together with Worker UUID to Router
            heartbeat_socket.send_multipart(
                    [ PPP_HEARTBEAT, self.uuid ]
                )

            self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL

            log.debug('Worker heartbeat SENT')

    def signal_heartbeat(self):

        if time.time() > self.heartbeat_at:

            # send the msg together with Worker UUID to Router
            self.worker.send_multipart(
                    [ PPP_HEARTBEAT ]
                )

            self.heartbeat_at = time.time() + HEARTBEAT_INTERVAL

            log.debug('signal_heartbeat - SENT')
        else:
            log.debug('signal_heartbeat - NOT DUE yet (%s)' % (
                    time.time() - self.heartbeat_at
                ))

    def signal_ready(self):
        """ Signals that the Worker is ready to accept work (async job load) """
        # send `PPP_READY` message to Router
        log.info('sent PPP_READY - register: %s | %s' % (self.service, self.uuid))

        self.worker.send_multipart(
                [ PPP_READY, self.service ]
            )

    def send(self, message):
        """ Send replies to the Client """
        assert self.reply_to is not None

        #if isinstance(message, str):
        #    message = [self.reply_to, message, ]

        msg = [PPP_REPLY, self.reply_to, '', message]
        log.debug('sending reply: %s' % msg)
        self.worker.send_multipart(msg)

    def recv(self, reply=None):
        """Send reply, if any, to broker and wait for next request."""

        if reply is not None:
            self.send(reply)

        # poll broker socket - expecting a reply within HEARTBEAT_INTERVAL seconds
        socks = dict(self.poller.poll(HEARTBEAT_INTERVAL * 1000))

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

            if frames and frames[0] == PPP_HEARTBEAT:

                log.debug('Queue heartbeat RECEIVED')

            elif frames and frames[0] == PPP_RECONNECT:

                log.warning("Queue re-connect RECEIVED")

                self.reconnect_broker()

            elif len(frames) == 6:

                # parse client request
                client_ident, x, api_version, service_name, expiration, request = frames

                log.debug("New Request: %s" % frames)

                self.reply_to = client_ident

                return request

            else:
                log.critical("Invalid message: %s" % frames)

        else:  # no response received from router socket
            log.debug('no response from Router')

            self.liveness -= 1
            if self.liveness <= 1:

                log.warn("Heartbeat DEAD (%i seconds) - Reconnecting to Router in %0.2fs" % (
                    HEARTBEAT_LIVENESS, self.interval
                ))
                gevent.sleep(self.interval)

                if not self.interval:
                    self.interval = 1
                elif self.interval < INTERVAL_MAX:
                    self.interval *= 2
                else:
                    self.interval = INTERVAL_INIT

                self.reconnect_broker()

        self.signal_heartbeat()

    def reconnect_broker(self):

        # create new socket to broker
        self.setup_worker_socket()

        # reset heartbeat timeout
        self.liveness = HEARTBEAT_LIVENESS
    def register_function(self, function_callback, function_name = None):
        """ registers a python RPC function """

        if not function_name:
            function_name = function_callback.func_name

        log.debug('RPC register_function: %s as "%s"' % (
            function_callback, function_name
        ))
        self.rpc_registry[function_name] = function_callback

    def run(self):
        reply = None

        while True:

            log.debug('polling for work (reply: %s)' % reply)

            request = self.recv(reply)
            reply = None

            if not request:
                log.debug('empty `request` received')
                continue

            log.debug('got RPC request to process: %s' % request)

            rpc_request = json.loads(request)

            if rpc_request['method'] in self.rpc_registry:
                try:
                    reply = self.rpc_registry[rpc_request['method']](
                            *rpc_request['args'],
                            **rpc_request['kwargs']
                        )
                except:
                    reply = '500:exception:%s' % cPickle.dumps(
                        sys.exc_info()[1]
                    )
            else:
                reply = '404'
