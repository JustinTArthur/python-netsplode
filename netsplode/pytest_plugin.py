import pytest
import socket

from netsplode.context import track_connections


class CollectingSocket(socket.socket):
    pass


@pytest.fixture
def netsploder():
    with track_connections() as context:
        yield context

