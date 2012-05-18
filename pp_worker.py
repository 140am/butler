import logging
import time
import random
import cjson
import zmq

import EBP

logging.basicConfig(
    format = '%(asctime)s - %(levelname)s - %(name)s - %(threadName)s - %(message)s',
    level = logging.INFO
)
log = logging.getLogger('pp_worker')

if __name__ == '__main__':

    worker = EBP.EBWorker("tcp://localhost:5556", 'video.cut')

    reply = None
    while True:

        # poll broker through worker server
        request = worker.recv(reply)
        if not request:
            break  # worker was interrupted

        log.info('got request: %s' % request)

        # parse and return an updated client `request`
        reply = request

        # update json request body
        response = cjson.decode(reply[5])
        response['worker'] = worker.identity
        reply[5] = cjson.encode(response)

