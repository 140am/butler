# butler 0.3.0 (master)
* added `close` method to `Client` and `RPC proxy` objects to shutdown a connection

# butler 0.2.0 (November 21, 2012)
* first version of the `RPC` interface for the `Client` similar to python's xmlrpclib
* allow to register whole objects as a `Client` proxy for `RPC` calls
* allow setting `Client.timeout` when using the RPC proxy interface
* remove registered Services from `Router` after 1 hour if they have no `Worker` associated anymore
* fix handling empty responses in `Client`
* use ØMQ DEALER instead of REQ sockets for `Client.call()`
* dependency on `py-zeromq 2.2.0.1`

# butler 0.1.0 (November 9, 2012)
* initial version under library name `ebwrkapi`
* design based on [http://rfc.zeromq.org/spec:7](http://rfc.zeromq.org/spec:7) and [http://rfc.zeromq.org/spec:9](http://rfc.zeromq.org/spec:9)