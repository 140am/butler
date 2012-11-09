# ebwrkapi - ØMQ based Service Worker Framework

The EB service worker framework aims to offer a simple but high performance and 
reliable service-oriented request-reply API between large number of client applications, 
a broker and worker applications using ØMQ sockets.

Requires <http://www.python.org/> and <http://www.zeromq.org/>


## Features

- Service Registration for Worker
- Request / Reply broker for Client requests
- Heartbeat between Workers and Router (both direction)
- Service Discovery by adding `mmi.` as prefix to service calls
- Extensible in 28 programming languages through `ØMQ` sockets

---

## Components

### Provided Network Services

- 5555/tcp - Client Frontend
- 5556/tcp - Worker Backend
- 5558/tcp - Worker Result Sink


### Request-Reply Broker

Provides a Client Frontend and Worker Backend.

    broker = ebwrkapi.EBBroker()
    broker.frontend.bind("tcp://*:5555")
    broker.backend.bind("tcp://*:5556")
    broker.run()


### Worker

Register a Service Worker for a specific function and process requests / messages:

    service = ebwrkapi.EBWorker('tcp://127.0.0.1:5556', 'api.resize_image')
    reply = None
    while True:
        request = service.recv(reply)
        reply = None  # reset state
        if not request:
            continue
        # do work
        reply = 'hello world'


### Client Requests

Send a request to a registered service and receive its response.

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')
    response = client.call( 'api.resize_image', {
        'uri' : 'test.jpeg',
        'size' : '150x180'
    })

The default `EBClient.timeout` will wait max `2500` msec (2.5 second) for the request to be accepted by a `Worker` Server and return a response. The Client can also re-connect and attempt to get 1+ `EBClient.retries` if required.


### Client - Service Discovery

To see if a `Service Worker` is available to handle the named function add the `mmi.` prefix to any function calls. Will return `200` if OK or `400` if Service is not available.

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'mmi.api.resize_image' )
    if response[1] == '200':
        print 'someone is around to handle %s' % response[0]


### Task Result Sink

Optional extension to receive event / messages from Service Worker

    sink = ebwrkapi.EBSink('tcp://*:5558')
    while True:
        msg = sink.get_message()
        log.info('MSG received: %s' % msg)

---

## Spec

* Client : REQ ->
* Broker : ROUTER <-> ROUTER
* Worker : DEALER ->
* Sink : PULL


### Message Format

* Client Requests
ident, x, service, function, expiration, request = frames

* Worker Request
address, command, worker_uuid, msg (service) = frames


### Client

- Request/Reply transaction with `Broker`
- Client can control sync / asynchronous behavior via `EBClient.timeout` and `EBClient.retries`
- Optional Request Sequence numbering to enforce Request -> Reply pattern


### Request-Reply Broker

* bind two ROUTER sockets on `frontend` and `backend`
* two Poller: `pull_backends` or `pull_both`
* start via `EBBroker().run()`

* `setup_heartbeat` in seperate green thread (greenlet)
    * send PPP_HEARTBEAT via PUSH socket to `backend`
    * `self.purge_workers()` all `self.waiting` records
    * go over all worker records in `self.waiting`
    * send PPP_HEARTBEAT to each worker record using PPP_REPLY

* endless loop - `pull_backends` if no self.workers otherwise `pull_both`

* response on `frontend`: self.process_client()

    * `function` starts with `mmi.`
        * service_name in self.services
        * self.frontend.send_multipart([service_name, returncode])

    * otherwise
    self.dispatch_request( self.require_service(function), frames )
        * self.purge_workers()
            * check Worker.expiry time of each Worker
            * self.delete_worker()
                * remove from `worker.service.waiting`
                * remove from `self.workers`
        * ensure Worker available in `service.waiting`
        * go over all `service.requests` `msg` records
            * add `service.waiting.address` into msg at 0
            * remove Worker from `self.waiting`
            * self.backend.send_multipart(msg)

* response on `backend`: self.process_worker()

    * Process message

        * Incoming ROUTER Msg: `[PPP_REPLY, worker_uuid, worker_address, PPP_RECONNECT]`
        * ROUTER adds source `address` at beginning of message
        * Outgoing ROUTER Msg: address, command, worker_uuid, msg
            * address = Client
            * command = PPP_REPLY
            * worker_uuid = worker_uuid
            * msg = [worker_address, PPP_RECONNECT]

    * Process message based on `command`
        * PPP_READY : register Worker
            * if `worker_registered`
                * send `[PPP_REPLY, worker_uuid, worker_address, PPP_RECONNECT]`

            * self.require_worker -> self.workers[worker_uuid]
            * self.require_service -> self.services[Service.name]
            * self.worker_waiting ->
                * add to `self.waiting`
                * add to `worker.service.waiting`
                * update `worker.expiry`

        * PPP_HEARTBEAT : update Worker.expiry
            * if not registered -> self.disconnect_worker()
                * send `[PPP_REPLY, worker_uuid, worker_address, PPP_RECONNECT]`

            * update `worker.expiry`

        * PPP_REPLY : route PPP_REPLY msg to Worker
            * if not registered -> self.disconnect_worker()
                * send `[PPP_REPLY, worker_uuid, worker_address, PPP_RECONNECT]`

            * lookup worker in `self.workers`
            * self.backend.send_multipart(msg)

        * any : forward to client via `frontend` socket
            * self.frontend.send_multipart(msg)


### Service Worker

- Connects to `Broker` socket via `ØMQ` socket
- Sends `PPP_READY` Message to `Broker` BE
- Goes into polling state calling #recv on the `Broker` BE socket
- `Worker` running in while loop until empty/invalid Response received OR keyboard interrupt signal
- processes each received `request` messages
    - Broker will not receive any Heartbeats until Worker is done
    - Broker will not issue new Tasks to the Worker
- send a `reply` to the Client by going through one loop cycle before timeout

---

## ØMQ Glossary

### REQ
REQ sockets prepend an empty message frame to every message you send and removes the empty message frame from each message you receive. It also imposes a strict send / receive cycle.

### ROUTER
Prepends an envelope with reply address to each message it receives, before passing it to the application. It also chops off the envelope (the first message frame) from each message it sends and uses that reply address to decide which peer the message should go to. It is how a ØMQ network with no state can create round-trip request-reply dialogs.

### DEALER
Just deals out the messages you send to all connected peers (aka "round-robin"), and deals in (aka "fair queuing") the messages it receives.

### PULL
Messages are fair-queued from among all connected upstream nodes.

---

## Inspiration

- http://zguide.zeromq.org/page:all
- http://rfc.zeromq.org/spec:7
- http://rfc.zeromq.org/spec:8
- http://rfc.zeromq.org/spec:9
- Code Snippets from Min RK <benjaminrk@gmail.com>
- Java example by Arkadiusz Orzechowski

---

## MIT License

Copyright (c) Manuel Kreutz <manuel@140.am>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
