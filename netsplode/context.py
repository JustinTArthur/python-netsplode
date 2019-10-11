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
        ).start()


class ConnectionTracker:
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
def track_connections():
    tracker = ConnectionTracker()

    class NetsplodeConnectionsTrackingSocket(socket.socket):
        def accept(self):
            conn, address = super().accept()
            if conn.proto == socket.IPPROTO_TCP:
                tracker.add_server_tcp_connection(conn)
            return conn, address

        def connect(self, *args, **kwargs):
            try:
                retval = super().connect(*args, **kwargs)
            except BlockingIOError:
                # async runners often start the socket as non-blocking
                # and then use select/poll mechanisms to check for success later
                if self.proto == socket.IPPROTO_TCP:
                    tracker.add_client_tcp_connection(self)
                raise
            if self.proto == socket.IPPROTO_TCP:
                tracker.add_client_tcp_connection(self)
            return retval

        def connect_ex(self, *args, **kwargs):
            retval = super().connect_ex(*args, **kwargs)
            if self.proto == socket.IPPROTO_TCP:
                tracker.add_client_tcp_connection(self)
            return retval

        def shutdown(self, how: int) -> None:
            retval = super().shutdown(how)
            if how == socket.SHUT_RDWR:
                tracker.remove_tcp_connection(self)
            return retval

        def close(self, *args, **kwargs):
            retval = super().close()
            tracker.remove_tcp_connection(self)
            return retval

    original_socket = socket.socket
    socket.socket = NetsplodeConnectionsTrackingSocket
    try:
        yield tracker
    finally:
        socket.socket = original_socket
