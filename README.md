# ebwrkapi - Encoding Booth Workflow Protocol

The EB module aims to offer a reliable service-oriented request-reply API between
a set of client applications, a broker and a set of worker applications. Features:

- Request / Reply broker to for Client requests
- Service Discovery by adding `mmi.` as prefix to function names

Based on 0MQ <http://www.zeromq.org/>


## Example Usage

### Create a Request-Reply Broker

Provides a Client Frontend and Worker Backend.

    broker = EBP.EBBroker()
    broker.frontend.bind "tcp://*:5555"
    broker.backend.bind "tcp://*:5556"
    broker.run()


### Client Usage

Send a request and receive its response.

    client = EBP.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'validate.content', { 'uri' : 'http://www.encodingbooth.com/test.bin' } )
    print response

The default `EBClient.timeout` will wait max `1000` msec (1 second) to be accepted by a `Worker` Server and return a response. The Client can also re-connect and attempt to get 1+ `EBClient.retries` if required.


### Worker

    worker = EBP.EBWorker("tcp://localhost:5556", 'video.cut')
    reply = None
    while True:
        request = worker.recv(reply)
        if not request:
            break  # worker was interrupted
        reply = request   # echo the request back to the client after modifying it
        reply['status'] = 1


### Service Discovery

To see if a `Worker` is available right now to handle the named function:

    client = EBP.EBClient('tcp://127.0.0.1:5555')
    response = client.send( 'mmi.validate.content' )
    if response[1] == '200':
        print 'someone is around to handle %s' % response[0]

## Inspiration

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
