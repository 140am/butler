""" Encoding Booth - Worker Broker Client

A 0MQ socket of type ZMQ_REQ is used by a client to send requests to and receive replies from a service.
Each request sent is round-robined among all broker services and each reply received is matched with the
last issued request.
"""

import time
import sys
import logging
import random
import json
import zmq

import ebwrkapi

REQUEST_RETRIES = 1
REQUEST_TIMEOUT = 1500

log = logging.getLogger(__name__)


class EBClient(object):

    broker = None  # string - example: tcp://127.0.0.1:5555
    context = None  # zmq.Context
    client = None  # zmq.Socket
    poller = None  # zmq.Poller

    retries = REQUEST_RETRIES  # count - number of request retries

    sequence = 0

    def __init__(self, bind_address):

        self.bind_address = bind_address

        self.context = zmq.Context(1)

        self.poller = zmq.Poller()

        self.connect_to_broker()

    def connect_to_broker(self):

        # close existing socket
        if self.client:
            self.poller.unregister(self.client)
            self.client.close()

        # create a ZMQ_REQ socket to send requests / receive replies
        self.client = self.context.socket(zmq.REQ)
        self.client.setsockopt(zmq.LINGER, 0)
        self.client.setsockopt(zmq.HWM, 0)

        # register socket with poller
        self.poller.register(self.client, zmq.POLLIN)

        # connect to `Router` socket
        self.client.connect(self.bind_address)

    def send(self, service, request):
        """
        Returns the reply message or None if there was no reply within timeout limit
        The maximum total blocking time for this method is REQUEST_RETRIES*REQUEST_TIMEOUT in msec
        """
        time_s = time.time()

        reply = None

        # convert request body dict to json structure
        if isinstance(request, dict):
            request = json.dumps(request)

        """ Request Layout:

        Frame 0: Empty (zero bytes, invisible to REQ application)
        Frame 1: "EBv1:%i" (string, representing version and request sequence number)
        Frame 2: Service name (printable string)
        Frame 3: Expiration Time (unix time in future)
        Frames 4+: Request body (opaque binary, will be converted to json string)
        """

        # request timeout
        timeout = int(round((time.time() * 1000))) + REQUEST_TIMEOUT

        msg = [
            '%s:%i' % (ebwrkapi.__version__, self.sequence),
            str(service),
            str(timeout),
            str(request)
        ]

        # send the request
        self.client.send_multipart(msg)

        socks = dict(self.poller.poll(int(REQUEST_TIMEOUT)))

        if socks.get(self.client) == zmq.POLLIN:

            # receive its response
            frames = self.client.recv_multipart()

            if not frames:
                log.warn('got empty reply back from `Broker`')
                return

            log.debug('got reply: %s' % frames)

            if len(frames) > 2:

                if frames[2].startswith(ebwrkapi.__version__):

                    # parse response
                    ident, service_name, function, expiration, request_body = frames

                    reply = request_body

                    # Don't try to handle errors, just assert noisily
                    # assert len(msg) >= 3
                    # compares request sequence id to be in order
                    if int(service_name.split(':')[1]) == self.sequence:
                        self.retries = REQUEST_RETRIES
                        return
                    else:
                        log.error("Malformed reply from server: %s / %s" % (
                            self.sequence, service_name.split(':')[1]
                        ))

                        self.retries -= 1
                        reply = None

            else:
                log.debug('got service response: %s' % frames)
                reply = frames

        else:

            log.debug('no response from router - aborting')

        return reply

    def destroy(self):
        self.context.term()

