""" Task Result Sink

Provides a PULL zeromq socket to receive Worker messages/events

Example Usage:

sink = butler.Sink('tcp://*:5558')
while True:
    msg = sink.get_message()
    log.info('MSG received: %s' % msg)

worker = butler.Service("tcp://localhost:5556", 'image.validate')
worker.sink.send('task received')
"""

import logging
import zmq.green as zmq

log = logging.getLogger(__name__)


class Sink(object):

    context = None
    poller = None
    sink = None

    bind_host = None

    def __init__(self, bind_host = '*:5558'):

        self.context = zmq.Context(1)
        self.poller = zmq.Poller()

        # PULL socket to receive broadcast/flow messages on
        self.sink = self.context.socket(zmq.PULL)

        # setting an identity so worker will buffer outgoing messages in case of downtime
        self.sink.setsockopt(zmq.IDENTITY, 'sink')

        self.sink.bind(bind_host)

        self.setup_polling()

    def setup_polling(self):

        self.poller.register(self.sink, zmq.POLLIN)

    def get_message(self):

        msg = ''

        socks = dict(self.poller.poll())

        if self.sink in socks and socks[self.sink] == zmq.POLLIN:
            msg = self.sink.recv()

        return msg
