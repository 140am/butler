# -*- coding: utf-8 -*-
"""
The `butler` framework aims to make building reliable and high-performance service-oriented
systems easy. The internal communication is done via ØMQ sockets.

Usage
-----

Start a Router::

    import butler

    router = butler.Router()
    router.frontend.bind("tcp://*:5555")
    router.backend.bind("tcp://*:5556")
    router.run()

Register a Service Worker by name::

    worker = butler.Service('tcp://127.0.0.1:5556', 'api.images')

Expose a function on the Service Worker::

    def resize_image(name, size):
        return 'resized image'

    worker.register_function(resize_image)
    worker.run()

Or expose all the methods of an object::

    class RPCService(object):
        def resize_image(self, name, size):
            return 'resized image'

    worker.register(RPCService())
    worker.run()

Send a request to a registered Service and receive its response::

    client = butler.Client('tcp://127.0.0.1:5555').rpc('api.images')
    client.resize_image('test.jpeg', '150x180')
    client.close()

"""

from setuptools import setup

setup(
    name = 'butler',
    version = '0.3.0',
    author = 'Manuel Kreutz',
    author_email = 'manuel@140.am',
    description = '0MQ based Service Oriented RPC Framework',
    license = 'MIT',
    url = 'https://github.com/140am/butler',
    packages = ['butler'],
    long_description = __doc__,
    classifiers = [
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Programming Language :: Python :: 2.5',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Clustering',
        'Topic :: System :: Distributed Computing',
        'Topic :: System :: Networking',
        'Topic :: System :: Systems Administration',
        'License :: OSI Approved :: MIT License',
    ],
    install_requires = [
        'pyzmq==2.2.0.1',
        'gevent'
    ]
)
