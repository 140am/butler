import logging
import time
import random
import zmq

import EBP

logging.basicConfig(
    format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    level = logging.DEBUG
)
log = logging.getLogger('worker')
log.setLevel(logging.DEBUG)

if __name__ == '__main__':

    worker = EBP.EBWorker("tcp://localhost:5555")
    worker.run()

