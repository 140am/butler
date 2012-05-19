# ebwrkapi - Encoding Booth Workflow Protocol

The EB module aims to offer a reliable service-oriented request-reply API between
a set of client applications, a broker and a set of worker applications. Features:

- Request / Reply broker to for Client requests
- Service Discovery by adding `mmi.` as prefix to function names

Based on <http://www.python.org/> and 0MQ <http://www.zeromq.org/>


## Getting Started

### Run a Request-Reply Broker

Provides a Client Frontend and Worker Backend.

    broker = ebwrkapi.EBBroker()
    broker.frontend.bind "tcp://*:5555"
    broker.backend.bind "tcp://*:5556"
    broker.run()


### Send Requests from Client

Send a request and receive its response.

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'validate.content', { 'uri' : 'http://www.encodingbooth.com/test.bin' } )
    print response

The default `EBClient.timeout` will wait max `1000` msec (1 second) to be accepted by a `Worker` Server and return a response. The Client can also re-connect and attempt to get 1+ `EBClient.retries` if required.


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


### Service Discovery

To see if a `Worker` is available right now to handle the named function:

    client = ebwrkapi.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'mmi.validate.content' )
    if response[1] == '200':
        print 'someone is around to handle %s' % response[0]


## Components

### Client

- Sends Request/Reply transaction to `Broker`
- Client can control sync / asynchronous behavior via `EBClient.timeout` and `EBClient.retries`
    - Client  wait for at least `EBClient.timeout` value (1000 msec / 1 sec) for response
- Request Sequence numbering to enforce Request -> Reply pattern


### Broker

- pool the BE and FE sockets for messages
	- _only_ poll the BE socket if no workers are currently registered
- process Worker messsage
  	- require_worker = create `Worker` object
	- parse message
		- PPP_READY
			- attempt to lookup `service` name in `self.services` dict
              to get a `Service object
                - client requests
                - waiting workers
            - call `worker_waiting` to signal that Worker is ready to accept Work
		- PPP_HEARTBEAT
		- error
- process a `Client` request
	- internal `mmi.` service call
	- Worker` service call forwarded to BE
- Send Heartbeat Messages to BE
- Purge expired but registered `Worker`

### Worker

- Connects to `Broker` socket via `0MQ` socket
- Sends `PPP_READY` Message to `Broker` BE
- Goes into polling state calling #recv on the `Broker` BE socket
- `Worker` running in while loop until empty/invalid Response received OR keyboard interrupt signal
- processes each received `request` messages
    - Broker will not receive any Heartbeats until Worker is done
    - Broker will not issue new Tasks to the Worker
- send a `reply` to the Client by going through one loop cycle before timeout


## Inspiration

- http://zguide.zeromq.org/page:all
- http://rfc.zeromq.org/spec:9
- http://rfc.zeromq.org/spec:8


## Performance

Pretty Pretty Good.. The throughput will primarily be limited by the Worker response
time and not the protocol over head. Benchmarks soon to come.


## MIT License

Copyright (c) Manuel Kreutz <http://encodingbooth.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
