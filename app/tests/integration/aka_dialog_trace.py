"""Private SIPp dialog trace checks after a completed AKA registration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import IPv4Address

START = re.compile(r"^(?:(INVITE|ACK|BYE|REGISTER)\s+\S+\s+SIP/2\.0|SIP/2\.0\s+(\d{3})\b)", re.I)
HEADER = re.compile(r"^([^:\s]+):\s*(.*)$")
SDP_AUDIO = re.compile(r"(?m)^m=audio\s+(\d+)\s+RTP/AVP\s+([^\r\n]+)")
SDP_ADDRESS = re.compile(r"(?m)^c=IN IP4\s+([0-9.]+)\s*$")
SDP_PCMU = re.compile(r"(?m)^a=rtpmap:0\s+PCMU/8000\s*$", re.I)
URI = re.compile(r"sip:([^@>;\s]+)@([^>;\s]+)", re.I)
TAG = re.compile(r"(?:^|;)\s*tag=([^;>\s]+)", re.I)
BRANCH = re.compile(r"(?i)\bbranch=([^;,\s]+)")


@dataclass
class TraceMessage:
    direction: str
    method: str
    status: int | None
    headers: dict[str, str]
    body: str

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    def cseq(self) -> tuple[int, str]:
        match = re.fullmatch(r"(\d+)\s+(INVITE|ACK|BYE|REGISTER)", self.header("cseq"), re.I)
        if not match:
            raise ValueError("missing CSeq")
        return int(match.group(1)), match.group(2).upper()


def _direction(lines: list[str], start: int) -> tuple[str, int]:
    for index in range(start - 1, max(-1, start - 7), -1):
        line = lines[index].lower()
        if "udp message sent" in line:
            return "sent", index
        if "udp message received" in line or "udp message recv" in line:
            return "received", index
    raise ValueError("SIPp message direction is missing")


def parse_dialog_messages(trace: str) -> list[TraceMessage]:
    lines = trace.splitlines()
    starts = [index for index, line in enumerate(lines) if START.match(line.strip())]
    parsed: list[TraceMessage] = []
    for position, start in enumerate(starts):
        direction, _ = _direction(lines, start)
        first = START.match(lines[start].strip())
        assert first is not None
        method = first.group(1).upper() if first.group(1) else "RESPONSE"
        status = int(first.group(2)) if first.group(2) else None
        headers: dict[str, str] = {}
        cursor = start + 1
        previous = ""
        while cursor < len(lines) and lines[cursor].strip():
            line = lines[cursor]
            if line[:1] in (" ", "\t") and previous:
                headers[previous] += " " + line.strip()
            else:
                match = HEADER.match(line)
                if not match:
                    raise ValueError("malformed SIP header")
                previous = "call-id" if match.group(1).lower() == "i" else match.group(1).lower()
                if previous == "via" and previous in headers:
                    # SIP proxies add Via hops; retain every value for exact branch binding.
                    headers[previous] += "\n" + match.group(2).strip()
                else:
                    headers[previous] = match.group(2).strip()
            cursor += 1
        body_end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[cursor + 1 : body_end])
        parsed.append(TraceMessage(direction, method, status, headers, body))
    return parsed


def split_registration(trace: str) -> tuple[str, str]:
    lines = trace.splitlines(keepends=True)
    first_invite = next(
        (index for index, line in enumerate(lines) if line.startswith("INVITE ")), None
    )
    if first_invite is None:
        raise ValueError("combined trace has no INVITE")
    _, preamble = _direction([line.rstrip("\r\n") for line in lines], first_invite)
    return "".join(lines[:preamble]), "".join(lines[preamble:])


def _uri(header: str) -> tuple[str, str]:
    match = URI.search(header)
    if not match:
        raise ValueError("missing SIP identity")
    return match.group(1), match.group(2).lower()


def _tag(header: str) -> str:
    match = TAG.search(header)
    if not match:
        raise ValueError("missing dialog tag")
    return match.group(1)


def _via_bound(response: TraceMessage, request: TraceMessage) -> bool:
    branch = BRANCH.search(request.header("via"))
    return bool(branch and branch.group(1) in set(BRANCH.findall(response.header("via"))))


def _media(message: TraceMessage) -> tuple[str, int]:
    if "application/sdp" not in message.header("content-type").lower():
        raise ValueError("missing SDP content type")
    if not message.header("content-length").isdigit() or int(message.header("content-length")) <= 0:
        raise ValueError("SDP content length is absent")
    audio = SDP_AUDIO.search(message.body)
    address = SDP_ADDRESS.search(message.body)
    if not audio or not address or not SDP_PCMU.search(message.body):
        raise ValueError("missing PCMU/8000 SDP")
    if "0" not in audio.group(2).split():
        raise ValueError("SDP audio does not offer PCMU payload 0")
    port = int(audio.group(1))
    if not 0 < port <= 65535:
        raise ValueError("invalid SDP media port")
    IPv4Address(address.group(1))
    return address.group(1), port


def extract_remote_media(trace: str, role: str) -> tuple[str, int]:
    if role not in {"caller", "callee"}:
        raise ValueError("role must be caller or callee")
    dialog = [message for message in parse_dialog_messages(trace) if message.method != "REGISTER"]
    direction = "received"
    candidate = [
        message
        for message in dialog
        if message.direction == direction
        and (
            (role == "callee" and message.method == "INVITE")
            or (role == "caller" and message.status == 200 and message.cseq()[1] == "INVITE")
        )
    ]
    if len(candidate) != 1:
        raise ValueError("expected one remote SDP offer or answer")
    return _media(candidate[0])


def _contact(header: str) -> tuple[str, str]:
    user, address = _uri(header)
    host, separator, port = address.rpartition(":")
    if not separator or not port.isdigit() or not 0 < int(port) <= 65535:
        raise ValueError("Contact lacks IP and port")
    IPv4Address(host)
    return user, address


def validate_dialog(
    trace: str,
    *,
    role: str,
    local_imsi: str,
    peer_imsi: str,
    domain: str,
    local_ip: str,
    local_port: int | str,
    registration_ok: bool | dict[str, object],
    media_port: int = 4000,
) -> dict[str, object]:
    """Check one complete two-party SIP dialog; return no private SIP fields."""
    result: dict[str, object] = {
        "status": "FAIL",
        "role": role,
        "message_count": 0,
        "provisional_count": 0,
    }
    if role not in {"caller", "callee"} or not (
        registration_ok is True
        or isinstance(registration_ok, dict)
        and registration_ok.get("status") == "PASS"
    ):
        return result
    try:
        from aka_trace import messages as registration_messages

        prefix, suffix = split_registration(trace)
        registration_ids = {m.header("call-id") for m in registration_messages(prefix)}
        dialog = parse_dialog_messages(suffix)
        result["message_count"] = len(dialog)
        ids = {m.header("call-id") for m in dialog}
        if (
            len(registration_ids) != 1
            or len(ids) != 1
            or not next(iter(ids))
            or ids & registration_ids
        ):
            return result
        if len(dialog) < 5 or dialog[0].method != "INVITE":
            return result
        invite = dialog[0]
        outgoing = "sent" if role == "caller" else "received"
        incoming = "received" if role == "caller" else "sent"
        if invite.direction != outgoing:
            return result
        invite_seq, invite_method = invite.cseq()
        if invite_method != "INVITE":
            return result
        index = 1
        while index < len(dialog) and dialog[index].status in {100, 180, 183}:
            provisional = dialog[index]
            if (
                provisional.direction != incoming
                or provisional.cseq() != (invite_seq, "INVITE")
                or provisional.header("via") != invite.header("via")
                or _uri(provisional.header("from")) != _uri(invite.header("from"))
                or _uri(provisional.header("to")) != _uri(invite.header("to"))
            ):
                return result
            index += 1
        result["provisional_count"] = index - 1
        if index + 3 >= len(dialog):
            return result
        answer, ack, bye, bye_ok = dialog[index : index + 4]
        if index + 4 != len(dialog):
            return result
        if (
            answer.direction != incoming
            or answer.status != 200
            or answer.cseq() != (invite_seq, "INVITE")
            or ack.direction != outgoing
            or ack.method != "ACK"
            or ack.cseq() != (invite_seq, "ACK")
            or bye.direction != outgoing
            or bye.method != "BYE"
            or bye.cseq() != (invite_seq + 1, "BYE")
            or bye_ok.direction != incoming
            or bye_ok.status != 200
            or bye_ok.cseq() != (invite_seq + 1, "BYE")
        ):
            return result
        if (
            not all(message.header("via") for message in (invite, answer, ack, bye, bye_ok))
            or not _via_bound(answer, invite)
            or not _via_bound(bye_ok, bye)
            or _uri(answer.header("from")) != _uri(invite.header("from"))
            or _uri(answer.header("to")) != _uri(invite.header("to"))
            or _uri(bye_ok.header("from")) != _uri(bye.header("from"))
            or _uri(bye_ok.header("to")) != _uri(bye.header("to"))
        ):
            return result
        local = (local_imsi, domain.lower())
        peer = (peer_imsi, domain.lower())
        if _uri(invite.header("from")) != (local if role == "caller" else peer):
            return result
        if _uri(invite.header("to")) != (peer if role == "caller" else local):
            return result
        if _contact((invite if role == "caller" else answer).header("contact")) != (
            local_imsi,
            f"{local_ip}:{local_port}".lower(),
        ):
            return result
        from_tag = _tag(invite.header("from"))
        to_tag = _tag(answer.header("to"))
        if (
            _tag(answer.header("from")) != from_tag
            or _tag(bye_ok.header("from")) != from_tag
            or _tag(bye_ok.header("to")) != to_tag
        ):
            return result
        for request in (ack, bye):
            if (
                _uri(request.header("from")) != _uri(invite.header("from"))
                or _tag(request.header("from")) != from_tag
            ):
                return result
            if (
                _uri(request.header("to")) != _uri(invite.header("to"))
                or _tag(request.header("to")) != to_tag
            ):
                return result
        local_sdp = invite if role == "caller" else answer
        local_media_ip, local_media_port = _media(local_sdp)
        if local_media_ip != local_ip or local_media_port != media_port:
            return result
        extract_remote_media(suffix, role)
        result["status"] = "PASS"
    except (ValueError, IndexError):
        pass
    return result
