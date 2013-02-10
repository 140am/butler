## ØMQ Socket Layout

* Client : DEALER ->
* Broker : ROUTER <- LRU Queue -> ROUTER
* Worker : DEALER ->
* Sink : PULL


## Message Format

All messages are seperated by ØMQ frames (zmq_msg_t objects).


### Client

    * Request
    client_ident, null, api_version:request_id, service_name, request_expiration, request

    * Response
    null, api_version:request_id, response


#### RPC - JSON `request` and `response`

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


### Worker :: Outgoing to Router

    * Service Registration
    PPP_READY, service_name

    * Router Heartbeat
    PPP_HEARTBEAT

    * Client reply
    PPP_REPLY, reply_ident, null, api_version:request_id, response


### Router :: Incoming from Worker

    worker_ident, command, *

    * Worker - PPP_READY
    worker_ident, PPP_READY, service_name

    * Worker - PPP_HEARTBEAT
    worker_ident, PPP_HEARTBEAT

    * Worker - PPP_REPLY (Worker > Client)
    worker_ident, PPP_REPLY, client_message


### Router :: Outgoing to Worker

    router_ident, PPP_REPLY, worker_ident, *

    * Worker Heartbeat
    PPP_REPLY, worker_ident, PPP_HEARTBEAT

    * Worker Re-Connect
    PPP_REPLY, worker_ident, PPP_RECONNECT


### Worker :: Incoming from Router

    * Client Request (6 frames)
    client_ident, null, api_version:request_id, service_name, request_expiration, request

    * Router Heartbeat
    PPP_HEARTBEAT

    * Router Re-Registration Request
    PPP_RECONNECT
