"""Read per-call media endpoints from RTPengine's local NG control API."""

import ipaddress
import secrets
import socket

from . import runtime


def _decode(data, offset=0):
    marker = data[offset : offset + 1]
    if marker == b"i":
        end = data.index(b"e", offset)
        return int(data[offset + 1 : end]), end + 1
    if marker == b"l":
        result = []
        offset += 1
        while data[offset : offset + 1] != b"e":
            value, offset = _decode(data, offset)
            result.append(value)
        return result, offset + 1
    if marker == b"d":
        result = {}
        offset += 1
        while data[offset : offset + 1] != b"e":
            key, offset = _decode(data, offset)
            result[key], offset = _decode(data, offset)
        return result, offset + 1
    separator = data.index(b":", offset)
    length = int(data[offset:separator])
    start = separator + 1
    return data[start : start + length], start + length


def _query(call_id):
    encoded = call_id.encode("ascii")
    # RTPengine uses the cookie for reply correlation and duplicate suppression.
    # Reusing it can return a previous call's cached response under concurrency.
    cookie = ("media-adapter-" + secrets.token_hex(8)).encode("ascii")
    request = (
        cookie
        + b" d7:call-id"
        + str(len(encoded)).encode("ascii")
        + b":"
        + encoded
        + b"7:command5:querye"
    )
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.settimeout(runtime.rtpengine_query_timeout)
    try:
        control.sendto(request, (runtime.rtpengine_ip, runtime.rtpengine_ng_port))
        response = control.recv(65535)
    finally:
        control.close()
    prefix = cookie + b" "
    if not response.startswith(prefix):
        raise ValueError("RTPengine returned a mismatched control cookie")
    decoded, end = _decode(response, len(prefix))
    if end != len(response) or decoded.get(b"result") != b"ok":
        raise ValueError("RTPengine returned an invalid query response")
    return decoded


def resolve_subscriber_port(call_id):
    """Return the even relay port whose remote endpoint is in the IMS UE pool."""
    try:
        response = _query(call_id)
        for tag in response.get(b"tags", {}).values():
            for media in tag.get(b"medias", []):
                if media.get(b"type") != b"audio":
                    continue
                for stream in media.get(b"streams", []):
                    endpoint = stream.get(b"endpoint", {})
                    address = endpoint.get(b"address", b"").decode("ascii")
                    port = stream.get(b"local port")
                    if (
                        b"RTP" in stream.get(b"flags", [])
                        and ipaddress.ip_address(address) in runtime.ims_ue_network
                        and runtime.port_min <= port <= runtime.port_max
                        and port % 2 == 0
                    ):
                        return port
    except (OSError, ValueError, IndexError, KeyError, UnicodeError, TypeError) as exc:
        print(f"MEDIA RTPengine query failed type={type(exc).__name__}", flush=True)
    return None
