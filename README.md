# ebwrkapi - Encoding Booth Workflow Protocol

The EB module aims to offer a high performance, reliable service-oriented
request-reply API between a set of client applications, a broker and
a set of worker applications using 0MQ sockets.

Requires <http://www.python.org/> and <http://www.zeromq.org/>


## Features

- Request / Reply broker for Client requests
- Service Discovery by adding `mmi.` as prefix to function names
- Extensible in 28 programming languages


## Getting Started

### Run a Request-Reply Broker

Provides a Client Frontend and Worker Backend.

    broker = ebwrkapi.EBBroker()
    broker.frontend.bind("tcp://*:5555")
    broker.backend.bind("tcp://*:5556")
    broker.run()


### Send Requests from Client

Send a request and receive its response.

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'validate.content', { 'uri' : 'http://www.encodingbooth.com/test.bin' } )
    print response

The default `EBClient.timeggout` will wait max `1000` msec (1 second) to be accepted by a `Worker` Server and return a response. The Client can also re-connect and attempt to get 1+ `EBClient.retries` if required.


### Worker

    worker = ebwrkapi.EBWorker("tcp://localhost:5556", 'video.cut')
    reply = None
    while True:
        request = worker.recv(reply)
        if not request:
            break  # worker was interrupted
        reply = request   # echo the request back to the client after modifying it
        reply['status'] = 1
        pass  # anything happneing here will cause the `Router` to stop
        routing messsages here


### Result Sink

    sink = ebwrkapi.EBSink('tcp://*:5558')
    while True:
        msg = sink.get_message()
        log.info('MSG received: %s' % msg)


### Service Discovery

To see if a `Worker` is available right now to handle the named function:

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'mmi.validate.content' )
    if response[1] == '200':
        print 'someone is around to handle %s' % response[0]


## Spec

### Client

- Request/Reply transaction with `Broker`
- Client can control sync / asynchronous behavior via `EBClient.timeout` and `EBClient.retries`
    - Client  wait for at least `EBClient.timeout` value (1000 msec / 1 sec) for response
- Request Sequence numbering to enforce Request -> Reply pattern


### Broker

- pool the BE and FE sockets for messages for max HEARTBEAT_INTERVAL msec
	- _only_ poll the BE socket if no workers are currently registered
    - effectively refusing client requests / signalling that no Workers are available
- process a `Client` request (Front End)
	- handle internal `mmi.` service call locally
	- `Worker` service call forwarded to BE routed by `Service`
- process a `Worker` messsage (Back End)
  	- require_worker = create `Worker` object
    - `worker_ready` is `false` unless the `Worker` has been already registered
	- parse message
		- PPP_READY
			- attempt to lookup `Service` by name in `self.services`
                - client requests
                - waiting workers
            - call `worker_waiting` to signal that Worker is ready to accept Work
		- PPP_HEARTBEAT
		- error
- every 1 Second in seperate thread
    - Purge expired but registered `Worker`
    - Send PPP_HEARTBEAT to BE for all `Worker` in `self.waiting`

### Worker

- Connects to `Broker` socket via `0MQ` socket
- Sends `PPP_READY` Message to `Broker` BE
- Goes into polling state calling #recv on the `Broker` BE socket
- `Worker` running in while loop until empty/invalid Response received OR keyboard interrupt signal
- processes each received `request` messages
    - Broker will not receive any Heartbeats until Worker is done
    - Broker will not issue new Tasks to the Worker
- send a `reply` to the Client by going through one loop cycle before timeout


## Performance

Pretty Pretty Good.. The throughput will primarily be limited by the Worker response
time and not the protocol over head. Benchmarks soon to come.


## Inspiration

- http://zguide.zeromq.org/page:all#Heartbeating
- http://rfc.zeromq.org/spec:9
- http://rfc.zeromq.org/spec:8
- Code Snippets from Min RK <benjaminrk@gmail.com>
- Based on Java example by Arkadiusz Orzechowski


## MIT License

Copyright (c) Manuel Kreutz <http://isprime.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
