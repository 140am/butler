import time
import sys
import logging
import random
import cjson
import zmq

import ebwrkapi

logging.basicConfig(
    format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    level = logging.INFO
)
log = logging.getLogger('client')

if __name__ == '__main__':

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')

    for i in range(1000):

        request = {
            'source_uri' : 'http://www.path.to/mp4/test_%i.mp4' % random.randint(10000, 90000),
            'profile_name' : 0,
            'thumb_count' : 0,
            'thumb_type' : '',
            'thumb_format' : '%s.jpg',
            'thumb_size' : '0x0',
            'output_destination' : '',
            'notes' : ''
        }

        log.info('Sending - Request #%i' % (i + 1))

        resp = client.send( 'video.cut', request )

        log.info('Response - Request #%i: %s' % ( (i + 1), resp ))

