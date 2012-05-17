import time
import sys
import logging
import random
import cjson
import zmq

import EBP

logging.basicConfig(
    format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    level = logging.DEBUG
)
log = logging.getLogger('client')
log.setLevel(logging.INFO)

if __name__ == '__main__':

    client = EBP.EBClient('tcp://127.0.0.1:5555')
    client.timeout = 1000  # 1 sec
    client.retires = 1  # attempt only once

    for i in range(100):

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

        resp = client.send( 'video.cut', request )

        if resp:
            log.info('Sent Request #%i - Response: %s | %s' % (
                (i + 1),
                request['source_uri'],
                cjson.decode(resp)['source_uri'])
            )

