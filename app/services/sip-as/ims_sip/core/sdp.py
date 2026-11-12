"""Допуск медиа-контракта PCMU на границе AI-услуг и адрес RTP из SDP."""

import ipaddress
import re


def accepts_pcmu(message: str) -> bool:
    """Reject offers the fixed PT=0 answer cannot satisfy, before allocating RTP.

    Phones may offer only AMR. A relay address alone is not proof that a
    transcoder has inserted PCMU. Inspect SDP, never SIP headers or video PTs.
    Multiple media streams and required QoS preconditions are not implemented.
    """
    headers, separator, body = message.partition("\r\n\r\n")
    if not separator:
        return False
    content_type = re.search(r"(?im)^(?:Content-Type|c):\s*([^;\r\n]+)", headers)
    if not content_type or content_type[1].strip().lower() != "application/sdp":
        return False
    required = re.findall(r"(?im)^Require:\s*([^\r\n]+)", headers)
    if any(
        token.strip().lower() in {"precondition", "100rel"}
        for value in required
        for token in value.split(",")
    ):
        return False
    lines = body.splitlines()
    media = [line.split() for line in lines if line.startswith("m=")]
    if len(media) != 1:
        return False
    audio = media[0]
    if len(audio) < 4 or audio[0] != "m=audio" or audio[2] != "RTP/AVP":
        return False
    if not audio[1].isdigit() or not 0 < int(audio[1]) <= 65535 or "0" not in audio[3:]:
        return False
    # Static PT 0 implies PCMU/8000/1; an explicit conflicting map is invalid.
    maps = re.findall(r"(?im)^a=rtpmap:0\s+([^\r\n]+)", body)
    if any(value.strip().upper() not in {"PCMU/8000", "PCMU/8000/1"} for value in maps):
        return False
    if any(line.lower() in {"a=inactive", "a=sendonly", "a=recvonly"} for line in lines):
        return False
    return not re.search(r"(?im)^a=des:qos\s+mandatory\b", body)


def offered_media_endpoint(message: str) -> tuple[str, int] | None:
    """Извлечь IPv4 и RTP-порт из SDP offer или answer."""
    connection_match = re.search(r"(?im)^c=IN IP4 ([^\s]+)", message)
    media_match = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
    if connection_match is None or media_match is None:
        return None
    try:
        offered_ip = str(ipaddress.ip_address(connection_match.group(1)))
        offered_port = int(media_match.group(1))
    except ValueError:
        return None
    return offered_ip, offered_port
