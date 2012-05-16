""" The Client (Task Ventilator) will get pending "Jobs" requests from DB backend and send to the Job Broker

A socket of type ZMQ_REQ is used by a client to send requests to and receive replies from a service. Each request sent is round-robined among all services, and each reply received is matched with the last issued request.
"""

import time
import sys
import logging
import random
import cjson
import zmq

SERVER_ENDPOINT = 'tcp://127.0.0.1:5555'

REQUEST_TIMEOUT = 2500
REQUEST_RETRIES = 5
REQUEST_LIFESPAN = 5  # seconds

PPP_BUSY = "\x03"  # Signals worker busy state

logging.basicConfig( format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s' )
log = logging.getLogger('client')
log.setLevel(logging.DEBUG)

context = zmq.Context(1)

poll = zmq.Poller()

sequence = 0
retries_left = REQUEST_RETRIES


def setup_router_socket(context, poller):

    identity = "%04X-%04X" % (random.randint(0, 0x10000), random.randint(0, 0x10000))

    # create a ZMQ_REQ socket to send requests / receive replies
    client = context.socket(zmq.REQ)

    # set the `identity` UUID as the worker identify
    client.setsockopt(zmq.IDENTITY, identity)
    client.setsockopt(zmq.HWM, 0)

    poll.register(client, zmq.POLLIN)

    # connect to `Router` socket
    client.connect(SERVER_ENDPOINT)

    return client


client = setup_router_socket(context, poll)


while retries_left:
    sequence += 1

    """ Request Layout:

    Frame 0: Empty (zero bytes, invisible to REQ application)
    Frame 1: "MDPC01" (six bytes, representing MDP/Client v0.1 or Worker etc)
    Frame 2: Service name (printable string)
    Frame 3: Expiration Time (unix time in future)
    Frames 4+: Request body (opaque binary)
    """

    request = [
        'MDPC01:%s' % str(sequence),
        'video.cut',
        str(int(time.time()) + REQUEST_LIFESPAN),
        cjson.encode({
            'source_uri' : 'http://www.path.to/mp4/test_%i.mp4' % random.randint(10000, 90000),
            'profile_name' : 0,
            'thumb_count' : 0,
            'thumb_type' : '',
            'thumb_format' : '%s.jpg',
            'thumb_size' : '0x0',
            'output_destination' : '',
            'notes' : ''
        })
    ]

    log.info("Attempting Request #%i (%s)" % (sequence, request))

    client.send_multipart(request)

    # attempt to send request until reply received or REQUEST_RETRIES timeout
    expect_reply = True
    while expect_reply:

        socks = dict(poll.poll(REQUEST_TIMEOUT))

        if socks.get(client) == zmq.POLLIN:

            reply = client.recv()
            response = client.recv()
            timeout = client.recv()
            config = client.recv()

            if not reply:
                log.warn('got empty reply back from `Broker`')
                break

            # compares request sequenze id to be in order
            if int(reply.split(':')[1]) == sequence:
                log.info("Server replied OK: %s / %s / %s" % (reply, response, config))

                # TODO: update db record here with status, worker server etc

                retries_left = REQUEST_RETRIES
                expect_reply = False  # continue with next request
            else:
                log.error("Malformed reply from server: %s / %s" % (sequence / reply))
                break
        else:

            # wait up to REQUEST_RETRIES*buffer-timeout for acceptance of the request
            retries_left -= 1
            if retries_left == 0:

                # Socket is confused. Close and remove it.
                client.setsockopt(zmq.LINGER, 0)
                client.close()
                poll.unregister(client)

                # Create new connection
                client = setup_router_socket(context, poll)

                retries_left = REQUEST_RETRIES
                break

context.term()

