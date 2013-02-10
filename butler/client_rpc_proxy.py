import json
import cPickle
import logging

log = logging.getLogger(__name__)


class RPCProxyCall:

    def __init__(self, client_obj, service_name, service_attr):
        self.service = service_name
        self.service_attr = service_attr
        self.client = client_obj

    def __call__(self, *args, **kwargs):
        self.client.retries = 1

        response = self.client.call(
            self.service, {
                'method' : self.service_attr,
                'args' : args,
                'kwargs' : kwargs
            }
        )

        # service returning `404` is considered a non implemented function
        if response == '404':
            raise AttributeError('%r object has no attribute %r' % (
                type(self).__name__, self.service_attr
            ))

        elif response and response.startswith('500:exception:'):

            # decode and un-serialize the exception response
            exc_response = json.loads(response[14:])
            exc_obj = cPickle.loads(str(exc_response['object']))

            # add the `traceback` string representation as a attribute to the Exception object
            setattr(exc_obj, 'traceback_messsage', exc_response['traceback'])

            raise exc_obj
        else:
            return response


class RPCProxy(object):

    def __init__(self, client_obj, service_name):
        self.service = service_name
        self.client = client_obj
        self.client.persistent = False

    def __setattr__(self, attr, value):
        # handle setting of `Client.timeout`
        if attr == 'timeout':
            self.client.timeout = value
        else:
            super(RPCProxy, self).__setattr__(attr, value)

    def __getattr__(self, attr):
        if attr == 'close':
            return self.client.close
        else:
            return RPCProxyCall(self.client, self.service, attr)
