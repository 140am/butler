import logging
import EBP

logging.basicConfig(
    format = '%(asctime)s - %(levelname)s - %(threadName)s - %(message)s',
    level = logging.INFO
)
log = logging.getLogger('broker')
log.setLevel(logging.INFO)

if __name__ == '__main__':

    broker = EBP.EBBroker()
    broker.frontend.bind("tcp://*:5555")
    broker.backend.bind("tcp://*:5556")
    broker.run()

