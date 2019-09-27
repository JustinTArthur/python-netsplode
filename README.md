# netsplode for Python
_A Connection Destruction Toolkit_

Network disconnects cause code to behave in unexpected ways. netsplode
helps test a project's resilience to these events. It might also be
useful for scripting network operations tasks.

## Installation
Once the API is more stable, builds will be released to PyPI.
Requirements:
* Python 3.6 or newer.
* In Windows, simulating real connection resets requires the [Npcap
driver+library](https://nmap.org/npcap/) to be installed.

## Usage
`netsplode.reset_connection(…)` accepts a variety of connection objects including:
* Python `socket.socket` objects.
* asyncio transports and `StreamWriter`s.
* Trio streams
* host/port pairs (coming soon)

```python
import asyncio
import netsplode

async def main():
    reader, writer = await asyncio.open_connection('127.0.0.1', 8888)
    
    writer.write(b'hi')
    netsplode.reset_connection(writer, blocking=False)
    await reader.read(100)

asyncio.run(main())
```

### Netsploder Contexts
To reset connections that might not be easily accessible, a context manager is
available that temporarily patches the standard library to collect established
connections. This context manager can then be used to reset those connections.

For example, to reset connections made by a redis client:
```python
import netsplode
import redis

with netsplode.create_netsploder() as netsploder:
    r = redis.Redis(host='localhost', port=6379, db=0)
    netsploder.reset_tcp_connections()
```
the following methods are available on Netsploder context objects:
* `Netsploder.reset_tcp_connections()`
* `Netsploder.reset_client_tcp_connections()`
* `Netsploder.reset_server_tcp_connections()`

### In Pytest
For convenience, a `netsploder` fixture can be injected into tests
if netsplode is installed in your test environment. The object behaves like
it does in the context manager pattern, restoring the environment to normal
after the test is completed.
```python
def test_my_server(netsploder):
    my_server = MyServer()
    my_server.start_serving()

    simulate_connections(my_server, 5)
    # wait for client connections…
    netsploder.reset_server_tcp_connections()
```

## Behind the Scenes
### Networking
netsplode for Python uses the following techniques to ’splode connections:
* Sniff for a TCP packet and inject an RST response.
  * Technique based on _tcpkill_ from Dug Song's
  [dsniff](https://www.monkey.org/~dugsong/dsniff/) project.
  * Requires access to lower level OS stuff, uses
  [the scapy library](https://scapy.net/) for sniff and inject support.
* Perform an abortive close, where the socket is cleanly closed on our side
but the resources are immediately cleared from the OS networking stack so that
finalization steps are met with reset responses. This doesn't accurately
simulate the more typical of network interruptions, but is close.
  * Requires access to the OS socket object. Exotic connection types and
  host/port pairs can't do this.
* Overzealous keep-alive (coming soon)

### Concurrency
When non-blocking resets are requested, Python threads are used to perform the
reset in the background. This won't perform as efficiently as network and sleep
concurrency options native to an event loop or runner you might be using;
however, the approach makes it so the library can be used almost anywhere.
