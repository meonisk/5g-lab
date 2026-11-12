"""Read per-call media endpoints from RTPengine's local NG control API."""

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


def resolve_subscriber_ports(call_id):
    """Even relay ports of every call side whose remote endpoint is an IMS subscriber."""
    ports = []
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
                        and runtime.is_subscriber(address)
                        and runtime.port_min <= port <= runtime.port_max
                        and port % 2 == 0
                    ):
                        ports.append(port)
    except (OSError, ValueError, IndexError, KeyError, UnicodeError, TypeError) as exc:
        print(f"MEDIA RTPengine query failed type={type(exc).__name__}", flush=True)
    return ports


def resolve_subscriber_port(call_id):
    """Return the first even relay port whose remote endpoint is in the IMS UE pool."""
    ports = resolve_subscriber_ports(call_id)
    return ports[0] if ports else None


def _encode(value):
    """bencode для NG: int, str/bytes, list, dict (ключи по возрастанию)."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(_encode(k) + _encode(v) for k, v in items) + b"e"
    raise TypeError(f"bencode: unsupported {type(value).__name__}")


def _command(payload):
    """Одна команда NG со своим cookie; ответ без result=ok — ошибка."""
    cookie = ("media-adapter-" + secrets.token_hex(8)).encode("ascii")
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.settimeout(runtime.rtpengine_query_timeout)
    try:
        address = (runtime.rtpengine_ip, runtime.rtpengine_ng_port)
        control.sendto(cookie + b" " + _encode(payload), address)
        response = control.recv(65535)
    finally:
        control.close()
    prefix = cookie + b" "
    if not response.startswith(prefix):
        raise ValueError("RTPengine returned a mismatched control cookie")
    decoded, end = _decode(response, len(prefix))
    if end != len(response) or decoded.get(b"result") != b"ok":
        raise ValueError(f"RTPengine {payload['command']} failed")
    return decoded


def play_media(call_id, from_tag, blob):
    """Сыграть WAV в звонок RTPengine стороне с этим SIP tag (уведомление о записи)."""
    response = _command(
        {"command": "play media", "call-id": call_id, "from-tag": from_tag, "blob": blob}
    )
    return response.get(b"duration")
