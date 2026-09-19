"""Service startup; importing pipeline modules does not start worker threads."""

from . import runtime
from .routing import route_request, route_response


def main():
    print(
        f"SIP AS listening udp:{runtime.bind_ip}:{runtime.bind_port}; next={runtime.scscf[0]}:{runtime.scscf[1]}",
        flush=True,
    )
    while True:
        data, peer = runtime.sock.recvfrom(65535)
        message = data.decode("utf-8", "replace")
        if message.startswith("SIP/2.0"):
            route_response(message)
        else:
            route_request(message, peer)
