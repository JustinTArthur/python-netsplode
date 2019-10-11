import asyncio
import logging
import socket
from ipaddress import ip_address
from threading import Thread
from time import sleep
from typing import Union, Any, Optional, Sequence

from scapy.all import conf as scapy_conf, send, sniff, IP, IPv6, TCP, LOOPBACK_INTERFACE

logger = logging.getLogger(__name__)


def reset_connection(
    connection,
    blocking=True,
    delay: Optional[Union[int, float]] = None,
    use_abortive_close: Optional[bool] = None,
    fallback_to_abortive_close_after: Optional[Union[int, float]] = 5.0
):
    """Takes a connection object (e.g. a transport, socket, or stream) and
    forces the stream to undertake a real or simulated connection drop,
    resulting in a reset.

    Supports asyncio and Trio connection primitives, socket and
    SSLSocket objects.
    """
    if not blocking:
        Thread(
            target=reset_connection,
            args=(connection,),
            kwargs={
                'blocking': True,
                'delay': delay,
                'use_abortive_close': use_abortive_close,
                'fallback_to_abortive_close_after':
                    fallback_to_abortive_close_after
            }
        ).start()
        return
    if delay:
        sleep(delay)
    sock = socket_for_connection(connection)
    if sock:
        if use_abortive_close:
            abortively_close_socket(sock)
            return
        if (use_abortive_close is not False) and (not _can_sniff()):
            abortively_close_socket(sock)
            return
        if sock.proto == socket.IPPROTO_TCP:
            peer1, peer2 = _socket_peers(sock)
            could_reset = reset_tcp_stream_of_peers(
                peer1,
                peer2,
                timeout=fallback_to_abortive_close_after
            )
            if not could_reset and use_abortive_close is not False:
                abortively_close_socket(sock)


def _can_sniff():
    try:
        scapy_conf.L2listen()
    except RuntimeError:
        return False
    return True


def socket_for_connection(connection):
    if isinstance(connection, socket.socket) or is_socketlike(connection):
        return connection
    if isinstance(connection, (asyncio.BaseTransport, asyncio.StreamWriter)):
        return connection.get_extra_info('socket')
    if hasattr(connection, 'socket'):
        return connection.socket
    if hasattr(connection, 'transport_stream') and hasattr(connection.transport_stream, 'socket'):
        return connection.transport_stream.socket
    return None


def is_socketlike(socketlike_candidate: Any):
    return all(
        hasattr(socketlike_candidate, a)
        for a in ('setsockopt', 'getpeername', 'getsockname')
    )


def abortively_close_socket(sock):
    """
    Informs the OS that the socket shouldn't linger after being closed,
    then closes it. This means I/O attempts from this side will receive a
    warning from the OS that the socket no longer exists (e.g. a reset),
    but also means that the remote side may see reset warnings, even for FIN
    packets.
    :param sock:
    :return:
    """
    sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_LINGER,
        b'\x01\x00\x00\x00\x00\x00\x00\x00'
    )
    sock.close()


def reset_tcp_stream_of_peers(
    peer1: Sequence[Union[str, int]],
    peer2: Sequence[Union[str, int]] = None,
    timeout: Optional[Union[float, int]] = None
) -> bool:
    frame = capture_tcp_frame_between_peers(peer1, peer2, timeout)
    if frame:
        reset_tcp_stream_of_eth_frame(frame)
        return True
    return False


def capture_tcp_frame_between_peers(
    peer1: Sequence[Union[str, int]],
    peer2: Sequence[Union[str, int]] = None,
    timeout: Optional[Union[float, int]] = None
) -> Union[bytes, bytearray]:
    combo1 = f'src host {peer1[0]} and src port {peer1[1]}'
    combo2 = f'dst host {peer1[0]} and dst port {peer1[1]}'
    if peer2:
        combo1 = f'{combo1} and dst host {peer2[0]} and dst port {peer2[1]}'
        combo2 = f'{combo2} and src host {peer2[0]} and src port {peer2[1]}'
    pkt_filter = f'tcp and (({combo1}) or ({combo2}))'

    logger.debug(f'Sniffing for: {pkt_filter}')
    if is_loopback_conversation(peer1, peer2):
        frames = sniff(
            count=1,
            iface=LOOPBACK_INTERFACE,
            filter=pkt_filter,
            timeout=timeout
        )
    else:
        frames = sniff(
            count=1,
            filter=pkt_filter,
            timeout=timeout
        )
    return frames[0] if len(frames) > 0 else None


def is_loopback_conversation(*peers):
    return all(ip_address(peer[0]).is_loopback for peer in peers)

def reset_tcp_stream_of_eth_frame(frame: Any, severity=50):
    """
    Attempts to reset an ongoing TCP stream using RST injection.
    This technique is based on tcpkill from Dug Song's dsniff toolkit.

    It requires a recent real packet in order to start the injection process.
    """
    ip_class = IPv6 if IPv6 in frame else IP
    ip_payload = frame[ip_class]
    tcp_payload = ip_payload[TCP]
    if tcp_payload.flags & 'FRS':
        # Connection already closing (observed FIN, RST, or SYN)
        return

    # Prepare an RST packet that looks like it came from the other direction.
    reset_packet = ip_class(
        src=ip_payload.dst,
        dst=ip_payload.src
    ) / TCP(
        sport=tcp_payload.dport,
        dport=tcp_payload.sport,
        flags='R',
        seq=tcp_payload.ack
    )

    window = tcp_payload.window
    for i in range(severity):
        ip_payload[TCP].seq += (i * window)
        send(reset_packet)


def _socket_peers(sock: socket.socket):
    peer1 = sock.getpeername()
    peer2 = sock.getsockname()
    return peer1, peer2