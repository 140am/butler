import os

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()

setup(
    name = 'ebwrkapi',
    version = '0.1.0',
    author = 'Manuel Kreutz',
    author_email = 'manuel@140.am',
    description = 'ØMQ based Service Worker Framework',
    license = 'Other/Proprietary License',
    url = 'https://github.com/gosupreme/ebwrkapi',
    packages=['ebwrkapi'],
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
        'pyzmq == 2.1.10',
        'gevent',
        'gevent_zeromq'
    ]
)
