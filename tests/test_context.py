import asyncio
import random

import pytest

from netsplode.context import track_connections


def test_asyncio_connection_tracking():
    # A simple mechanism to not close things down
    # until we've tried out the tracker.
    close_blocker = asyncio.Event()
    connections_made = asyncio.Event()
    connections_resetting = asyncio.Event()
    connections_reset = asyncio.Event()

    async def _handle_echo(reader, writer):
        data = await reader.read(100)
        await connections_reset.wait()
        await writer.drain()
        writer.write(data)
        # await close_blocker.wait()
        writer.close()

    async def _echo_client(message, port):
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        connections_made.set()
        await connections_resetting.wait()
        await asyncio.sleep(0.5)
        writer.write(message.encode())
        await connections_reset.wait()
        _data = await reader.read(100)
        writer.close()

    async def run_echo_test():
        port = random.choice(range(44000, 65000))
        server = await asyncio.start_server(_handle_echo, '127.0.0.1', port)
        with track_connections() as tracker:
            client_task = asyncio.create_task(_echo_client('test', port))
            await connections_made.wait()
            assert len(tracker._client_tcp_connections) == 1
            assert len(tracker._server_tcp_connections) == 0

            reset_task = asyncio.ensure_future(
                loop.run_in_executor(
                    # Running in an executor gives the echo client a chance
                    # to write a packet the resetter can sniff and use.
                    None,
                    tracker.reset_client_tcp_connections
            ))
            connections_resetting.set()
            await reset_task
        connections_reset.set()

        await client_task
        close_blocker.set()
        server.close()
        await server.wait_closed()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_echo_test())
