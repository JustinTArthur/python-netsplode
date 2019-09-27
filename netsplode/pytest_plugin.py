import pytest
import socket

from netsplode.context import create_netsploder


class CollectingSocket(socket.socket):
    pass


@pytest.fixture
def netsploder():
    with create_netsploder() as context:
        yield context

