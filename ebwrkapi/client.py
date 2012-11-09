""" Encoding Booth - Worker Broker Client

A 0MQ socket of type ZMQ_REQ is used by a client to send requests to and receive replies from a service.
Each request sent is round-robined among all broker services and each reply received is matched with the
last issued request.
"""

import time
import logging
import json
import uuid
from gevent_zeromq import zmq

import ebwrkapi

REQUEST_RETRIES = 1
REQUEST_TIMEOUT = 2500

log = logging.getLogger(__name__)


class EBClient(object):

    broker = None  # 0MQ address - example: tcp://127.0.0.1:5555
    context = None  # zmq.Context
    client = None  # zmq.Socket
    poller = None  # zmq.Poller

    retries = REQUEST_RETRIES  # count - number of request retries

    timeout = REQUEST_TIMEOUT * 1e-3

    sequence = 0

    persistent = True

    def __init__(self, bind_address):

        self.uuid = str(uuid.uuid4())

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
        self.client.setsockopt(zmq.HWM, 0)
        self.client.linger = 1
        self.client.setsockopt(zmq.IDENTITY, self.uuid)

        # register socket with poller
        self.poller.register(self.client, zmq.POLLIN)

        # connect to `Router` socket
        self.client.connect(self.bind_address)

    def call(self, service, request):
        """
        Returns the reply message or None if there was no reply within timeout limit
        The maximum total blocking time for this method is REQUEST_RETRIES*REQUEST_TIMEOUT in msec
        """

        reply = None

        # convert python dict request to JSON structure
        if isinstance(request, dict):
            request = json.dumps(request)

        """ Request Layout:

        Frame 0: Empty (zero bytes, invisible to REQ application)
        Frame 1: "EBv1:%i" (string, representing version and request sequence number)
        Frame 2: Service name (printable string)
        Frame 3: Expiration Time (unix time in future)
        Frames 4+: Request body (opaque binary, will be converted to json string)
        """

        # request expiration time in milliseconds
        request_expiration = int(
                round(time.time() * 1000) + (REQUEST_TIMEOUT * REQUEST_RETRIES)
            )

        # attempt to get a response from router up to REQUEST_RETRIES times
        while self.retries:

            self.sequence += 1

            msg = [
                '%s:%s' % (ebwrkapi.__version__, self.sequence),
                str(service),
                str(request_expiration),
                str(request)
            ]

            # in case persistent is disabled re-send and connect on each retry attempt
            if self.persistent and self.retries == REQUEST_RETRIES:
                self.client.send_multipart(msg)
            elif not self.persistent and self.retries != REQUEST_RETRIES:
                self.client.send_multipart(msg)

            socks = dict(self.poller.poll(int(self.timeout * 1000)))

            if socks.get(self.client) == zmq.POLLIN:

                # receive its response
                frames = self.client.recv_multipart()

                if not frames:
                    log.warn('got empty reply back from `Broker`')
                    return reply

                if len(frames) > 2:

                    # ensure the msg can be understood / protocol API version
                    if frames[2].startswith(ebwrkapi.__version__):

                        log.debug('API %s msg received: %s' % (
                            ebwrkapi.__version__, frames
                        ))

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
                            log.error('Malformed reply from server: %s / %s' % (
                                self.sequence, service_name.split(':')[1]
                            ))

                            self.retries -= 1
                            reply = None
                    else:
                        log.warn('Invalid API msg received: %s' % frames)
                        reply = frames

                else:
                    log.debug('raw response received: %s' % frames)
                    reply = frames

                break
            else:

                if self.retries:
                    log.debug('no response from router - re-attempting')
                    self.retries -= 1

                    if not self.persistent:
                        self.connect_to_broker()
                else:
                    log.debug('no response from router - aborting')

        return reply
