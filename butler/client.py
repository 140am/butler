""" Encoding Booth - Worker Broker Client

A 0MQ socket of type ZMQ_REQ is used by a client to send requests to and receive replies from a service.
Each request sent is round-robined among all broker services and each reply received is matched with the
last issued request.
"""

import time
import logging
import json
import uuid
import butler
import gevent
import zmq.green as zmq

from client_rpc_proxy import RPCProxy

REQUEST_RETRIES = 1
REQUEST_TIMEOUT = 2500

log = logging.getLogger(__name__)


class Client(object):

    broker = None  # 0MQ address - example: tcp://127.0.0.1:5555
    context = None  # zmq.Context
    client = None  # zmq.Socket
    poller = None  # zmq.Poller

    retries = REQUEST_RETRIES  # count - number of request retries

    timeout = REQUEST_TIMEOUT * 1e-3

    sequence = 0

    persistent = True

    response = {}

    def __init__(self, bind_address):

        self.uuid = str(uuid.uuid4())

        self.bind_address = bind_address

        self.context = zmq.Context(1)

        self.poller = zmq.Poller()

        self.connect_to_broker()

    def connect_to_broker(self):

        # close existing socket
        if self.client:
            self.client.close()
            self.poller.unregister(self.client)

        # create a ZMQ_REQ socket to send requests / receive replies
        self.client = self.context.socket(zmq.DEALER)
        self.client.setsockopt(zmq.HWM, 0)
        self.client.setsockopt(zmq.LINGER, 1)
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

        # will hold the response
        reply = None

        # convert python dict request to JSON structure
        if isinstance(request, dict):
            request = json.dumps(request)

        # request expiration time in milliseconds for `call`
        request_expiration = int(
                round(time.time() + (self.timeout * REQUEST_RETRIES)) * 1000
            )

        # unix time at which the polling should end (`request timeout`)
        call_time_end = time.time() + (self.timeout * REQUEST_RETRIES)

        # number of attempts to re-send request in case of no service available
        request_retries = REQUEST_RETRIES

        # attempt to get a response from router up to REQUEST_RETRIES times
        while request_retries > 0:

            """ Request Message Format:

            Frame 0: Empty (zero bytes)
            Frame 1: "EBv1:%i" (string, representing version and unique request ID)
            Frame 2: Service name (printable string)
            Frame 3: Expiration Time (unix time in future)
            Frame 4: Request body (opaque binary, converted to JSON string)
            """

            request_id = str(uuid.uuid4())

            msg = [
                '',
                '%s:%s' % (butler.__version__, request_id),
                str(service),
                str(request_expiration),
                str(request)
            ]

            # in case persistent is disabled re-send and connect on each retry attempt
            if self.persistent and request_retries == REQUEST_RETRIES:
                self.client.send_multipart(msg)
            elif not self.persistent:
                self.client.send_multipart(msg)

            log.debug('sending request [%s | %s]: %s' % (
                service, request_id, json.loads(request)['method']
            ))

            # after dispatching the request poll up to max timeout for response
            response_poll = gevent.spawn(
                self.poll_for_reply, request_id, call_time_end
            )

            # at same time look for the per process stored response
            response_reply = gevent.spawn(
                    self.find_local_reply, request_id, call_time_end, response_poll
                )

            gevent.joinall(
                [ response_poll, response_reply ]
            )

            reply = response_reply.value

            request_retries -= 1

        return reply

    def rpc(self, service_name):

        self.rpc_proxy = RPCProxy(
            self, service_name
        )
        return self.rpc_proxy

    def poll_for_reply(self, orig_request_id, time_expiration):

        while time.time() < time_expiration:

            gevent.sleep(0.001)

            socks = dict(self.poller.poll(1000))

            if socks.get(self.client) == zmq.POLLIN:

                # receive its response
                frames = self.client.recv_multipart()

                if not frames:
                    log.warn('got empty reply back from `Broker`')
                    continue

                if len(frames) > 2:

                    # ensure the msg can be understood / protocol API version
                    if frames[1].startswith(butler.__version__):

                        log.debug('API %s msg received: %s' % (
                            butler.__version__, frames
                        ))

                        # ident, service_name, function, expiration, request_body = frames
                        x, api_call, request_body = frames

                        # take the API version / request sequence apart
                        request_id = api_call.split('%s:' % butler.__version__)[1]

                        self.response[request_id] = request_body

                        if orig_request_id == request_id:
                            break
                    else:
                        log.warn('Invalid API msg received: %s' % frames)
                else:
                    log.warn('raw response received: %s' % frames)
            else:
                log.debug('no response from router')

    def find_local_reply(self, orig_request_id, time_expiration, response_poll):

        while time.time() < time_expiration:
            reply = None
            if orig_request_id in self.response:
                reply = self.response.pop(orig_request_id)
                response_poll.kill()
                break
            gevent.sleep(0.001)

        return reply

    def close(self):

        self.client.close()
        self.poller.unregister(self.client)
        self.context.term()
