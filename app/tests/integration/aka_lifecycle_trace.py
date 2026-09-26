"""Sanitized SIPp REGISTER lifecycle checkpoints for one IMS binding."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aka_dialog_trace import TraceMessage, parse_dialog_messages

URI = re.compile(r"sip:([^@>;\s]+)@([^>;\s]+)", re.I)
PARAM = re.compile(r"(?i)(?:^|;)\s*expires\s*=\s*([^;,\s]+)")
DIGEST = re.compile(r'(?i)\b([a-z][\w-]*)\s*=\s*(?:"([^"]*)"|([^,\s]+))')


@dataclass
class Transaction:
    request: TraceMessage
    response: TraceMessage


def _uri(header: str) -> tuple[str, str]:
    match = URI.search(header)
    if not match:
        raise ValueError("missing SIP URI")
    return match.group(1), match.group(2).lower()


def _auth(header: str) -> dict[str, str]:
    return {
        m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
        for m in DIGEST.finditer(header)
    }


def _auth_matches(auth: dict[str, str], identity: tuple[str, str], *, empty: bool) -> bool:
    return (
        auth.get("username") in {identity[0], "@".join(identity)}
        and auth.get("realm", "").lower() == identity[1]
        and auth.get("uri", "").lower() == f"sip:{identity[1]}"
        and auth.get("algorithm", "").lower() == "akav1-md5"
        and (auth.get("response") == "" if empty else bool(auth.get("response")))
    )


def _expiry(message: TraceMessage) -> int | None:
    contact = message.header("contact")
    match = PARAM.search(contact)
    if match:
        value = match.group(1)
    elif re.search(r"(?i)(?:^|;)\s*expires\s*=", contact):
        raise ValueError("malformed Contact expiry")
    else:
        value = message.header("expires")
    if not value:
        return None
    if not value.isdigit():
        raise ValueError("invalid registration expiry")
    return int(value)


def _response_contact(message: TraceMessage, binding: tuple[str, str], *, required: bool) -> bool:
    value = message.header("contact")
    return _uri(value) == binding if value else not required


def _transactions(parsed: list[TraceMessage]) -> tuple[list[Transaction], bool]:
    transactions: list[Transaction] = []
    index = 0
    while index < len(parsed):
        request = parsed[index]
        if request.method != "REGISTER" or request.direction != "sent":
            raise ValueError("unexpected lifecycle message")
        index += 1
        while index < len(parsed) and parsed[index].status == 100:
            provisional = parsed[index]
            if provisional.direction != "received" or provisional.cseq() != request.cseq():
                raise ValueError("unbound 100 response")
            index += 1
        if index == len(parsed):
            return transactions, True
        response = parsed[index]
        if response.direction != "received" or response.status not in (200, 401):
            raise ValueError("unexpected REGISTER response")
        if response.cseq() != request.cseq():
            raise ValueError("REGISTER response CSeq mismatch")
        transactions.append(Transaction(request, response))
        index += 1
    return transactions, False


def checkpoint(
    trace: str, expected_imsi: str, domain: str, ip: str, port: int | str
) -> dict[str, object]:
    """Return only stages/counts/CSeq/status; credentials and identities stay private."""
    result: dict[str, object] = {
        "status": "PENDING",
        "initial": "PENDING",
        "refresh": "PENDING",
        "deregistration": "PENDING",
        "transaction_count": 0,
        "cseqs": [],
        "response_statuses": [],
    }
    try:
        parsed = parse_dialog_messages(trace)
        transactions, incomplete = _transactions(parsed)
        result["transaction_count"] = len(transactions)
        result["cseqs"] = [tx.request.cseq()[0] for tx in transactions]
        result["response_statuses"] = [tx.response.status for tx in transactions]
        ids = {message.header("call-id") for message in parsed}
        if parsed and (len(ids) != 1 or not next(iter(ids))):
            raise ValueError("Call-ID changed")
        contact = (expected_imsi, f"{ip}:{port}".lower())
        identity = (expected_imsi, domain.lower())
        for tx in transactions:
            if (
                _uri(tx.request.header("from")) != identity
                or _uri(tx.request.header("to")) != identity
                or _uri(tx.request.header("contact")) != contact
                or tx.request.cseq()[1] != "REGISTER"
            ):
                raise ValueError("binding identity changed")
        cseqs = result["cseqs"]
        if any(right <= left for left, right in zip(cseqs, cseqs[1:])):
            raise ValueError("CSeq did not increase")
        if not transactions:
            return result
        first = transactions[0]
        if first.response.status != 401 or _expiry(first.request) == 0:
            raise ValueError("missing initial AKA challenge")
        selector = _auth(first.request.header("authorization"))
        if not _auth_matches(selector, identity, empty=True):
            raise ValueError("initial AKA selector missing")
        challenge = _auth(first.response.header("www-authenticate"))
        if challenge.get("algorithm", "").lower() != "akav1-md5" or not challenge.get("nonce"):
            raise ValueError("missing AKA challenge")
        if len(transactions) < 2:
            return result
        authorized = transactions[1]
        auth = _auth(authorized.request.header("authorization"))
        if (
            authorized.response.status != 200
            or not _auth_matches(auth, identity, empty=False)
            or auth.get("nonce") != challenge["nonce"]
            or _expiry(authorized.request) == 0
            or not (_expiry(authorized.response) or 0) > 0
            or not _response_contact(authorized.response, contact, required=True)
        ):
            raise ValueError("initial AKA registration incomplete")
        result["initial"] = "PASS"

        index = 2
        if len(transactions) <= index:
            return result
        refresh = transactions[index]
        if _expiry(refresh.request) == 0:
            raise ValueError("refresh missing before deregistration")
        if refresh.response.status == 401:
            selector = _auth(refresh.request.header("authorization"))
            if not _auth_matches(selector, identity, empty=True):
                raise ValueError("refresh AKA selector missing")
            challenge = _auth(refresh.response.header("www-authenticate"))
            if challenge.get("algorithm", "").lower() != "akav1-md5" or not challenge.get("nonce"):
                raise ValueError("invalid refresh challenge")
            index += 1
            if len(transactions) <= index:
                return result
            refresh = transactions[index]
            auth = _auth(refresh.request.header("authorization"))
            if (
                not _auth_matches(auth, identity, empty=False)
                or auth.get("nonce") != challenge["nonce"]
            ):
                raise ValueError("refresh AKA response mismatch")
        elif not _auth_matches(
            _auth(refresh.request.header("authorization")), identity, empty=False
        ):
            raise ValueError("refresh request lacks authorization")
        if (
            refresh.response.status != 200
            or not (_expiry(refresh.request) or 0) > 0
            or not (_expiry(refresh.response) or 0) > 0
            or not _response_contact(refresh.response, contact, required=True)
        ):
            raise ValueError("refresh was not accepted")
        result["refresh"] = "PASS"

        index += 1
        if len(transactions) <= index:
            return result
        dereg = transactions[index]
        if _expiry(dereg.request) != 0:
            raise ValueError("deregistration request expiry is not zero")
        if dereg.response.status == 401:
            selector = _auth(dereg.request.header("authorization"))
            if not _auth_matches(selector, identity, empty=True):
                raise ValueError("deregistration AKA selector missing")
            challenge = _auth(dereg.response.header("www-authenticate"))
            if challenge.get("algorithm", "").lower() != "akav1-md5" or not challenge.get("nonce"):
                raise ValueError("deregistration challenge invalid")
            index += 1
            if len(transactions) <= index:
                return result
            dereg = transactions[index]
            auth = _auth(dereg.request.header("authorization"))
            if (
                _expiry(dereg.request) != 0
                or not _auth_matches(auth, identity, empty=False)
                or auth.get("nonce") != challenge["nonce"]
            ):
                raise ValueError("deregistration AKA response mismatch")
        elif not _auth_matches(_auth(dereg.request.header("authorization")), identity, empty=False):
            raise ValueError("deregistration request lacks authorization")
        if dereg.response.status != 200:
            raise ValueError("deregistration not accepted")
        response_expiry = _expiry(dereg.response)
        if response_expiry not in (None, 0) or not _response_contact(
            dereg.response, contact, required=False
        ):
            raise ValueError("deregistration response retained active binding")
        if len(transactions) != index + 1 or incomplete:
            raise ValueError("unexpected messages after deregistration")
        result["deregistration"] = "PASS"
        result["status"] = "PASS"
    except (ValueError, IndexError):
        result["status"] = "FAIL"
    return result


def validate_lifecycle(
    trace: str,
    expected_imsi: str,
    domain: str,
    ip: str,
    port: int | str,
    *,
    require_refresh: bool = True,
    require_deregistration: bool = True,
) -> dict[str, object]:
    result = checkpoint(trace, expected_imsi, domain, ip, port)
    required = ["initial"]
    if require_refresh:
        required.append("refresh")
    if require_deregistration:
        required.append("deregistration")
    if result["status"] != "FAIL":
        result["status"] = (
            "PASS" if all(result[stage] == "PASS" for stage in required) else "PENDING"
        )
    return result
