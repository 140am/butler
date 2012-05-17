""" Encoding Booth Broker Client

A zeromq socket of type ZMQ_REQ is used by a client to send requests to and receive replies from a service.
Each request sent is round-robined among all services, and each reply received is matched with the
last issued request.
"""

import time
import sys
import logging
import random
import cjson
import zmq

logging.basicConfig( format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s' )
log = logging.getLogger('client')
log.setLevel(logging.INFO)

# the maximum total `send` blocking time is REQUEST_RETRIES*REQUEST_TIMEOUT in msec
REQUEST_RETRIES = 3
REQUEST_TIMEOUT = 1500


class EBClient(object):

    identity = None
    broker = None  # example: tcp://127.0.0.1:5555
    context = None
    client = None
    poller = None
    retries = REQUEST_RETRIES  # count - number of request retries
    timeout = REQUEST_TIMEOUT  # msec - request timeout
    sequence = 0

    def __init__(self, broker):

        self.identity = "client-%04X-%04X" % ( random.randint(0, 0x10000), random.randint(0, 0x10000) )
        self.broker = broker
        self.context = zmq.Context(1)
        self.poller = zmq.Poller()
        self.connect_to_broker()

    def connect_to_broker(self):

        # close existing socket
        if self.client:
            self.poller.unregister(self.client)
            self.client.setsockopt(zmq.LINGER, 0)
            self.client.close()

        # create a ZMQ_REQ socket to send requests / receive replies
        self.client = self.context.socket(zmq.REQ)

        # set the `identity` to retrieve responses on disconnect
        self.client.setsockopt(zmq.IDENTITY, self.identity)
        self.client.setsockopt(zmq.HWM, 0)

        # register socket with poller
        self.poller.register(self.client, zmq.POLLIN)

        # connect to `Router` socket
        self.client.connect(self.broker)

    def send(self, service, request):
        """
        Returns the reply message or None if there was no reply within timeout limit
        """
        time_s = time.time()

        reply = None

        self.sequence += 1

        while self.retries:

            # request timeout
            #timeout = int(time.time()) + int(REQUEST_TIMEOUT / 1000)
            timeout = int(time.time()) + 1

            # convert request body dict to json structure
            if isinstance(request, dict):
                request = cjson.encode(request)

            """ Request Layout:

            Frame 0: Empty (zero bytes, invisible to REQ application)
            Frame 1: "EB1:%i" (3+ bytes, representing version and request sequence number)
            Frame 2: Service name (printable string)
            Frame 3: Expiration Time (unix time in future)
            Frames 4+: Request body (opaque binary, will be converted to json string)
            """

            msg = [
                'EBv1:%i' % self.sequence,
                str(service),
                str(timeout),
                str(request)
            ]

            resp = self.client.send_multipart(msg)

            try:
                socks = dict(self.poller.poll(self.timeout))
            except KeyboardInterrupt:
                self.shutdown()
                break

            if socks.get(self.client) == zmq.POLLIN:

                reply = self.client.recv()
                response = self.client.recv()
                timeout = self.client.recv()
                config = self.client.recv()

                # Don't try to handle errors, just assert noisily
                # assert len(msg) >= 3
                if not reply:
                    log.warn('got empty reply back from `Broker`')
                    break

                # compares request sequence id to be in order
                if int(reply.split(':')[1]) == self.sequence:
                    reply = config
                    self.retries = REQUEST_RETRIES
                    break
                else:
                    log.error("Malformed reply from server: %s / %s" % (self.sequence, reply.split(':')[1]))
                    reply = None
                    break

            else:

                self.retries -= 1

                self.connect_to_broker()

                # wait up to REQUEST_RETRIES*buffer-timeout for acceptance of the request
                if self.retries >= 1:
                    log.debug('no response from router - re-attempting request')
                else:
                    log.debug('no response from router - giving up')
                    self.retries = REQUEST_RETRIES
                    break

        # messure request time and ensure request takes at least REQUEST_TIMEOUT
        if not reply:
            runtime = time.time() - time_s
            runtime = runtime * 100000  # conver to msec
            if runtime < REQUEST_TIMEOUT:
                time.sleep((REQUEST_TIMEOUT - runtime) / 1000)

        return reply

    def shutdown(self):
        self.context.term()

