""" ebwrkapi - Encoding Booth Workflow Protocol

The EB module aims to offer a reliable service-oriented request-reply dialog between
a set of client applications, a broker and a set of worker applications. Features:

- Request / Reply to create Client requests
- Service Discovery by adding `mmi.` as prefix to function names

Its based on 0MQ (http://www.zeromq.org/)

Design Inspired by:
- http://rfc.zeromq.org/spec:9
Service Discovery (MMI - Majordomo Management Interface)
- http://rfc.zeromq.org/spec:8
"""

from client import EBClient
from broker import EBBroker
from worker import EBWorker

__version__ = 'EBv1'
