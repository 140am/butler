import os

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()

setup(
    name = 'butler',
    version = '0.2.0',
    author = 'Manuel Kreutz',
    author_email = 'manuel@140.am',
    description = '0MQ based Service Oriented RPC Framework',
    license = 'Other/Proprietary License',
    url = 'https://github.com/encodingbooth/butler',
    packages=['butler'],
    long_description=README,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Environment :: Console',
        'Programming Language :: Python :: 2',
        'Topic :: Internet',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Clustering',
        'Topic :: System :: Distributed Computing',
        'Topic :: System :: Networking',
        'Topic :: System :: Systems Administration',
        'Topic :: Utilities',
        'License :: Other/Proprietary License'
    ],
    install_requires = [
        'pyzmq==2.2.0.1',
        'gevent'
    ]
)
