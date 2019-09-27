from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import socket
import threading

from netsplode.networking import reset_connection


def _reset_connections(connections, blocking=True):
    if blocking:
        with ThreadPoolExecutor() as threads:
            threads.map(reset_connection, connections)
    else:
        # Recurse, but put the thread pool in its own thread we won't join on.
        threading.Thread(
            target=_reset_connections,
            args=(connections,),
            kwargs={'blocking': True}
        ).run()


class Netsploder:
    def __init__(self):
        self._client_tcp_connections = set()
        self._server_tcp_connections = set()

    def add_client_tcp_connection(self, connection):
        self._client_tcp_connections.add(connection)

    def add_server_tcp_connection(self, connection):
        self._server_tcp_connections.add(connection)

    def remove_tcp_connection(self, connection):
        self._client_tcp_connections.discard(connection)
        self._server_tcp_connections.discard(connection)

    def reset_client_tcp_connections(self, blocking: bool=True):
        to_reset = self._client_tcp_connections.copy()
        _reset_connections(to_reset, blocking=blocking)
        self._client_tcp_connections -= to_reset

    def reset_server_tcp_connections(self, blocking: bool=True):
        to_reset = self._server_tcp_connections.copy()
        _reset_connections(to_reset, blocking=blocking)
        self._server_tcp_connections -= to_reset

    def reset_tcp_connections(self, blocking: bool=True):
        to_reset = self._client_tcp_connections | self._server_tcp_connections
        _reset_connections(to_reset, blocking=blocking)
        self._client_tcp_connections -= to_reset
        self._server_tcp_connections -= to_reset


@contextmanager
def create_netsploder():
    context = Netsploder()

    class NetsplodeConnectionsCollectingSocket(socket.socket):
        def accept(self):
            conn, address = super().accept()
            if conn.proto == socket.IPPROTO_TCP:
                context.add_server_tcp_connection(conn)
            return conn, address

        def connect(self, *args, **kwargs):
            retval = super().connect(*args, **kwargs)
            if self.proto == socket.IPPROTO_TCP:
                context.add_client_tcp_connection(self)
            return retval

        def connect_ex(self, *args, **kwargs):
            retval = super().connect_ex(*args, **kwargs)
            if self.proto == socket.IPPROTO_TCP:
                context.add_client_tcp_connection(self)
            return retval

        def shutdown(self, how: int) -> None:
            retval = super().shutdown(how)
            if how == socket.SHUT_RDWR:
                context.remove_tcp_connection(self)
            return retval

        def close(self, *args, **kwargs):
            retval = super().close()
            context.remove_tcp_connection(self)
            return retval

    original_socket = socket.socket
    socket.socket = NetsplodeConnectionsCollectingSocket
    try:
        yield context
    finally:
        socket.socket = original_socket
