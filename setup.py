import os

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()

setup(
    name = 'ebwrkapi',
    version = '0.0.1',
    author = 'Manuel Kreutz',
    author_email = 'mk@isprime.com',
    description = 'Encoding Booth Distributed Computing Workflow Protocol',
    license = 'Other/Proprietary License',
    url = 'https://github.com/140am/ebwrkapi',
    packages=['ebwrkapi'],
    long_description=README,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Programming Language :: Python :: 2',
        'Topic :: Internet',
        'Topic :: Software Development :: Libraries',
        'Topic :: System :: Clustering',
        'Topic :: System :: Distributed Computing',
        'Topic :: System :: Networking',
        'Topic :: System :: Systems Administration',
        'Topic :: Utilities',
        'License :: Other/Proprietary License'
    ],
    install_requires = [
        'pyzmq == 2.1.10',
    ]
)
