import logging
import zmq

logging.basicConfig(
    format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    level = logging.INFO
)
log = logging.getLogger('sink')

if __name__ == '__main__':

    context = zmq.Context(1)

    sink = context.socket(zmq.PULL)

    # setting an identity so worker will buffer outgoing messages in case of downtime
    sink.setsockopt(zmq.IDENTITY, 'sink')
    sink.bind("tcp://*:5558")

    poller = zmq.Poller()
    poller.register(sink, zmq.POLLIN)

    log.info('sink running')

    while True:
        socks = dict(poller.poll())

        if sink in socks and socks[sink] == zmq.POLLIN:
            msg = sink.recv()
            log.debug('MSG received: %s' % msg)

