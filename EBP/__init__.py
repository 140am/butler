""" EBwrkapi - Encoding Booth Workflow Protocol

The EB module reliable service-oriented request-reply dialog between a set of client applications,
a broker and a set of worker applications.

- Request / Reply to create Client requests
- Service Discovery by adding `mmi.` as prefix to function names

Design Inspired by:
- http://rfc.zeromq.org/spec:9
Service Discovery (MMI - Majordomo Management Interface)
- http://rfc.zeromq.org/spec:8
"""

from client import EBClient
from broker import EBBroker
from worker import EBWorker

__version__ = 'EBv1'

