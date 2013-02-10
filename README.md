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

Start a Router to provide a Client Frontend and Service Backend.

```python
router = butler.Router()
router.frontend.bind("tcp://*:5555")
router.backend.bind("tcp://*:5556")
router.run()
```

The `frontend` and `backend` sockets allow the bridging of internal and public external networks or different protocols.

### Service Worker

Register a `Service` under a specific name:

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

You can also register an object and expose all its methods:

```python
class RPCService(object):
    def resize_image(self, name, size):
        return 'resized image'

worker.register(RPCService())
worker.run()
```

The following methods and attribute names are reserved and invoked on the `butler.Service` object directly:

* timeout
* close

### Client Request

#### Remote procedure call (RPC) on a Service

Send a request to a registered `Service` and receive its response.

```python
client = butler.Client('tcp://127.0.0.1:5555').rpc('api.images')
client.resize_image('test.jpeg', '150x180')
# ..other calls
client.close()
```

#### Exceptions during RPC

Unhandled exceptions are raised on the client side with the original traceback as a string representation:

```python
try:
    client.resize_image()
except Exception, e:
    # TypeError: resize_image() takes exactly 2 argument (0 given)
    #
    # Original Traceback (most recent call last):
    # ...
```

#### Timeouts and Default Behavior

With the default `Client.timeout` requests will take max `2500` msec (2.5 seconds) to be accepted
by a `Service Worker` and return a response or error. If required the `Client` can optionally also automatically
re-connect (`Client.persistent = False`) or attempt multiple times (`Client.retries`).


### Task Result Sink

Optional extension to receive event / messages from `Service Worker` instances:

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


## MIT License

> Copyright (c) 2012-2013 Manuel Kreutz
> 
> Permission is hereby granted, free of charge, to any person
> obtaining a copy of this software and associated documentation files
> (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge,
> publish, distribute, sublicense, and/or sell copies of the Software,
> and to permit persons to whom the Software is furnished to do so,
> subject to the following conditions: 
>
> The above copyright notice and this permission notice shall be
> included in all copies or substantial portions of the Software. 
> 
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
> EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
> MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
> BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
> ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
> CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE. 