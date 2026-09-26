"""Strict, private SIPp AKA REGISTER trace assessment with safe metadata output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import IPv4Address

START = re.compile(r"^(REGISTER\s+\S+\s+SIP/2\.0|SIP/2\.0\s+\d{3}\b[^\r\n]*)\s*$")
SIP_URI = re.compile(r"sip:([^@>;\s]+)@([^>;\s]+)", re.I)


@dataclass
class Message:
    kind: str
    status: int | None
    headers: dict[str, str]

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    def cseq(self) -> int:
        match = re.fullmatch(r"(\d+)\s+REGISTER", self.header("cseq"), re.I)
        if not match:
            raise ValueError("missing REGISTER CSeq")
        return int(match.group(1))


def messages(trace: str) -> list[Message]:
    lines = trace.splitlines()
    parsed: list[Message] = []
    index = 0
    while index < len(lines):
        start = START.match(lines[index].strip())
        if not start:
            index += 1
            continue
        first = start.group(1)
        headers: dict[str, str] = {}
        index += 1
        last = ""
        while index < len(lines) and lines[index].strip():
            line = lines[index]
            if line[:1] in (" ", "\t") and last:
                headers[last] += " " + line.strip()
            elif ":" in line:
                name, value = line.split(":", 1)
                last = "call-id" if name.lower() == "i" else name.lower()
                headers[last] = value.strip()
            else:
                raise ValueError("malformed SIP header")
            index += 1
        status = int(first.split()[1]) if first.startswith("SIP/2.0 ") else None
        parsed.append(Message("response" if status is not None else "register", status, headers))
        index += 1
    return parsed


def _uri(header: str) -> tuple[str, str]:
    match = SIP_URI.search(header)
    if not match:
        raise ValueError("missing SIP identity or contact")
    return match.group(1), match.group(2).lower()


def _contact(header: str) -> tuple[str, str]:
    user, host = _uri(header)
    address, separator, port = host.rpartition(":")
    if not separator or not port.isdigit() or not 0 < int(port) <= 65535:
        raise ValueError("contact lacks IP and port")
    IPv4Address(address)
    return user, host


def _registered_expiry(response: Message) -> int:
    contact = response.header("contact")
    parameter = re.search(r"(?i)(?:^|;)\s*expires\s*=\s*([^;,\s]+)", contact)
    if parameter:
        value = parameter.group(1)
    elif re.search(r"(?i)(?:^|;)\s*expires\s*=", contact):
        raise ValueError("malformed Contact expiry")
    else:
        value = response.header("expires")
    if not re.fullmatch(r"\d+", value):
        raise ValueError("registration expiry missing or invalid")
    return int(value)


def _digest_parameter(header: str, name: str) -> str | None:
    match = re.search(rf'(?i)\b{re.escape(name)}\s*=\s*(?:"([^"]*)"|([^,\s]+))', header)
    return (match.group(1) if match.group(1) is not None else match.group(2)) if match else None


def _terminal_exchange(parsed: list[Message]) -> tuple[Message, Message, Message, Message]:
    """Admit only transaction-bound 100 responses before each terminal response."""
    index = 0
    terminals: list[Message] = []
    for terminal_status in (401, None):
        if index >= len(parsed) or parsed[index].kind != "register":
            raise ValueError("missing REGISTER")
        request = parsed[index]
        terminals.append(request)
        index += 1
        while index < len(parsed) and parsed[index].status == 100:
            provisional = parsed[index]
            if (
                provisional.header("call-id") != request.header("call-id")
                or provisional.cseq() != request.cseq()
                or provisional.header("via") != request.header("via")
                or _uri(provisional.header("from")) != _uri(request.header("from"))
                or _uri(provisional.header("to")) != _uri(request.header("to"))
            ):
                raise ValueError("100 response does not belong to outstanding REGISTER")
            index += 1
        if index >= len(parsed) or parsed[index].kind != "response":
            raise ValueError("missing terminal response")
        response = parsed[index]
        if terminal_status is not None and response.status != terminal_status:
            raise ValueError("wrong challenge status")
        terminals.append(response)
        index += 1
    if index != len(parsed):
        raise ValueError("messages after final response")
    return tuple(terminals)  # type: ignore[return-value]


def assess(trace: str, *, wrong_key: bool = False) -> dict[str, object]:
    """Return only status, counts, algorithm and CSeq; never raw SIP fields."""
    try:
        parsed = messages(trace)
    except ValueError:
        parsed = []
    statuses = [message.status for message in parsed if message.status is not None]
    try:
        cseqs = [message.cseq() for message in parsed]
    except ValueError:
        cseqs = []
    result: dict[str, object] = {
        "status": "FAIL",
        "algorithm": "AKAv1-MD5"
        if any("akav1-md5" in m.header("www-authenticate").lower() for m in parsed)
        else "MISSING",
        "message_count": len(parsed),
        "register_count": sum(m.kind == "register" for m in parsed),
        "provisional_100_count": statuses.count(100),
        "response_statuses": statuses,
        "cseqs": cseqs,
    }
    try:
        first, challenge, authorized, final = _terminal_exchange(parsed)
        ids = {m.header("call-id") for m in parsed}
        if len(ids) != 1 or not next(iter(ids)):
            return result
        if challenge.status != 401 or result["algorithm"] != "AKAv1-MD5":
            return result
        first_seq, auth_seq = first.cseq(), authorized.cseq()
        if [m.cseq() for m in (first, challenge, authorized, final)] != [
            first_seq,
            first_seq,
            auth_seq,
            auth_seq,
        ]:
            return result
        if auth_seq != first_seq + 1:
            return result
        initial_auth = first.header("authorization")
        if (
            not re.search(r"(?i)\bDigest\b", initial_auth)
            or _digest_parameter(initial_auth, "algorithm") != "AKAv1-MD5"
            or _digest_parameter(initial_auth, "response") != ""
        ):
            return result
        if not re.search(r"(?i)\bDigest\b", authorized.header("authorization")):
            return result
        auth = authorized.header("authorization")
        identity = _digest_parameter(auth, "username")
        realm = _digest_parameter(auth, "realm")
        digest_uri = _digest_parameter(auth, "uri")
        algorithm = _digest_parameter(auth, "algorithm")
        response = _digest_parameter(auth, "response")
        nonce = _digest_parameter(auth, "nonce")
        challenge_nonce = _digest_parameter(challenge.header("www-authenticate"), "nonce")
        if not identity or not response or not nonce or nonce != challenge_nonce:
            return result
        first_contact, auth_contact = (
            _contact(first.header("contact")),
            _contact(authorized.header("contact")),
        )
        first_identity, auth_identity = _uri(first.header("from")), _uri(authorized.header("from"))
        if first_contact != auth_contact or first_identity != auth_identity:
            return result
        if (
            first_contact[0] != first_identity[0]
            or identity not in {first_identity[0], "@".join(first_identity)}
            or realm != first_identity[1]
            or digest_uri != f"sip:{first_identity[1]}"
            or algorithm != "AKAv1-MD5"
            or first.header("to") != authorized.header("to")
        ):
            return result
        expected = {401, 403, 407} if wrong_key else {200}
        if final.status not in expected or (wrong_key and 200 in statuses):
            return result
        if not wrong_key:
            if _contact(final.header("contact")) != auth_contact or _registered_expiry(final) <= 0:
                return result
        result["status"] = "PASS"
        return result
    except ValueError:
        return result


def validate_registration(
    trace: str,
    expected_imsi: str,
    domain: str,
    ip: str,
    port: int | str,
    rejected: bool = False,
) -> dict[str, object]:
    """Bind a SIPp exchange to the requested private UE fixture."""
    result = assess(trace, wrong_key=rejected)
    if result["status"] != "PASS":
        return result
    try:
        parsed = messages(trace)
        first, _, authorized, _ = _terminal_exchange(parsed)
        for request in (first, authorized):
            if _uri(request.header("from")) != (expected_imsi, domain.lower()):
                result["status"] = "FAIL"
            if _uri(request.header("to")) != (expected_imsi, domain.lower()):
                result["status"] = "FAIL"
            if _contact(request.header("contact")) != (expected_imsi, f"{ip}:{port}".lower()):
                result["status"] = "FAIL"
    except ValueError:
        result["status"] = "FAIL"
    return result
