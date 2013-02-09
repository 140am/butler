# butler - ØMQ based Service Oriented Framework

The `butler` framework aims to offer a simple but high performance and reliable
service-oriented request-reply API between a large number of clients and services
through a central router using ØMQ sockets. Clients and services can come
and go at anytime to make adjusting a cluster size dynamically based on workload easy.


## Features

- Service Registration for Worker
- Heartbeat between Workers and Router (both direction)
- First Class Exception Handling
- Gevent Support (Asynchronous Calls and Worker within greenlets)
- Service Discovery by adding `mmi.` as prefix to service calls


## Installation

```python
easy_install butler
```

### Note

    There is a known issue in gevent ≤ 1.0 or libevent, which can cause zeromq socket events to be missed.
    butler uses the PyZMQ library which works around this by adding a timeout so it will not wait forever
    for gevent to notice events. The only known solution for this is to use gevent ≥ 1.0, which is currently
    at 1.0rc2, and does not exhibit this behavior.

To install the latest gevent 1.0:

    easy_install cython
    easy_install https://github.com/SiteSupport/gevent/archive/1.0rc2.zip

## Usage

### Service Router

Start a Router to provide a Client Frontend and Worker Backend.

```python
router = butler.Router()
router.frontend.bind("tcp://*:5555")
router.backend.bind("tcp://*:5556")
router.run()
```

The `frontend` and `backend` sockets allow the bridging of internal and public external networks.

### Service Worker

Register a Service Worker under a specific name:

```python
worker = butler.Service('tcp://127.0.0.1:5556', 'api.images')
```

Register a function for RPC calls:

```python
def resize_image(name, size):
    return 'resized image'

worker.register_function(resize_image)
worker.run()
```

Optionally functions can be exposed under a different name:

```python
worker.register_function(resize_image, 'resize')
```

You can also register an object and all its methods for RPC calls:

```python
class RPCService(object):
    def resize_image(self, name, size):
        return 'resized image'

worker.register(RPCService())
worker.run()
```

The following methods and attributes are reserved and invoked on the `butler.Service` object directly:

* timeout
* close

### Client Request

#### Remote procedure call (RPC) on a Service

Send a request to a registered service and receive its response.

```python
client = butler.Client('tcp://127.0.0.1:5555').rpc('api.images')
client.resize_image('test.jpeg', '150x180')
# ..other calls
client.close()
```

#### Exceptions during RPC

```python
try:
    client.resize_image()
except Exception, e:
    # TypeError: resize_image() takes exactly 2 argument (0 given)
```

#### Timeouts and Default Behavior

With the default `Client.timeout` requests will take max `2500` msec (2.5 seconds) to be accepted
by a `Service Worker` and return a response or error. The Client can optionally also automatically
re-connect (`Client.persistent = False`) and attempt multiple times (`Client.retries`) if required.


### Task Result Sink

Optional extension to receive event / messages from Service Worker in a central place.

```python
sink = butler.Sink('tcp://*:5558')
while True:
    msg = sink.get_message()
    log.info('MSG received: %s' % msg)
```


## Advanced Usage

#### Direct Calls / Request Processing

You can also call and introspect available Services directly:

```python
client = butler.Client('tcp://127.0.0.1:5555')

response = client.call( 'api.images', {
    'method' : 'resize_image',
    'uri' : 'test.jpeg',
    'size' : '150x180'
})
client.close()
```

Process incoming Direct Requests / Messages manually:

```python
worker = butler.Service('tcp://127.0.0.1:5556', 'api.images')

reply = None
while True:
    request = worker.recv(reply)
    reply = None  # reset state
    if not request:
        continue
    # do work
    reply = 'hello world'
```

#### Service Discovery

To see if a `Service Worker` is available to handle the named function add the `mmi.` prefix to any function calls. Will return `200` if OK or `400` if Service is not available.

```python
client = butler.Client('tcp://127.0.0.1:5555')
response = client.send( 'mmi.api.images' )
if response[1] == '200':
    print 'someone is around to handle %s' % response[0]
```

## Spec

### ØMQ Socket Layout

* Client : DEALER ->
* Broker : ROUTER <- LRU Queue -> ROUTER
* Worker : DEALER ->
* Sink : PULL


### Message Format

All messages are seperated by ØMQ frames (zmq_msg_t objects).


#### Client

    * Request
    client_ident, null, api_version:request_id, service_name, request_expiration, request

    * Response
    null, api_version:request_id, response


##### RPC - JSON `request` and `response`

To support a remote procedure call (RPC) the Client `request` need to be
JSON encoded and conform to the following format:

```python
{
    "method": "rpc_function_name",
    "args": [],
    "kwargs": {}
}
```

In case of errors during the RPC the `response` will contain an error code
and optionally the python exception object as a pickled representation using
the `pickle` module.

    * Error Response - Function not Implemented
    '404'

    * Error Response - Exception Raised
    '500:exception:PICKLESTRING'


#### Worker :: Outgoing to Router

    * Service Registration
    PPP_READY, service_name

    * Router Heartbeat
    PPP_HEARTBEAT

    * Client reply
    PPP_REPLY, reply_ident, null, api_version:request_id, response


#### Router :: Incoming from Worker

    worker_ident, command, *

    * Worker - PPP_READY
    worker_ident, PPP_READY, service_name

    * Worker - PPP_HEARTBEAT
    worker_ident, PPP_HEARTBEAT

    * Worker - PPP_REPLY (Worker > Client)
    worker_ident, PPP_REPLY, client_message


#### Router :: Outgoing to Worker

    router_ident, PPP_REPLY, worker_ident, *

    * Worker Heartbeat
    PPP_REPLY, worker_ident, PPP_HEARTBEAT

    * Worker Re-Connect
    PPP_REPLY, worker_ident, PPP_RECONNECT


#### Worker :: Incoming from Router

    * Client Request (6 frames)
    client_ident, null, api_version:request_id, service_name, request_expiration, request

    * Router Heartbeat
    PPP_HEARTBEAT

    * Router Re-Registration Request
    PPP_RECONNECT


## Inspiration

- http://rfc.zeromq.org/spec:7
- http://rfc.zeromq.org/spec:8
- http://rfc.zeromq.org/spec:9
- Code Snippets from Min RK <benjaminrk@gmail.com>
- Java example by Arkadiusz Orzechowski


## MIT License

Copyright (c) 2012 Manuel Kreutz, Encoding Booth LLC

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
