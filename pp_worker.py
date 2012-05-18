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
    worker.sink.connect('tcp://localhost:5558')

    reply = None

    while True:

        # poll broker through worker server
        request = worker.recv(reply)
        if request is None:
            break  # worker was interrupted
        reply = request  # echo

        log.info('got request: %s' % request)

        # decode json request response
        response = cjson.decode(reply[5])

        # modify request body to have updated attributes
        response['worker'] = worker.identity

        # encode data structure to string
        reply[5] = cjson.encode(response)

        #log.info('wooork')
        #time.sleep(10)  # Do some heavy work

