"""Fail-closed metadata assessment of a rejected INVITE after AKA registration."""

from __future__ import annotations

import re

from aka_dialog_trace import _contact, _tag, _uri, parse_dialog_messages, split_registration
from aka_lifecycle_trace import _auth, _auth_matches, _expiry, _transactions
from aka_trace import messages as registration_messages
from aka_trace import validate_registration

BRANCH = re.compile(r"(?i)(?:^|;)\s*branch=([^;,\s]+)")


def _via_parts(value: str) -> tuple[str, str]:
    # The first Via is the client transaction; later proxy hops may follow.
    first = value.split("\n", 1)[0].split(",", 1)[0].strip()
    match = re.fullmatch(r"SIP/2\.0/UDP\s+([^;\s]+)(?:;.*)?", first, re.I)
    branch = BRANCH.search(first)
    if not match or not branch:
        raise ValueError("missing UDP transaction Via")
    return match.group(1).lower(), branch.group(1)


def _response_via_bound(response_via: str, request_via: str) -> bool:
    wanted = _via_parts(request_via)
    try:
        return any(
            _via_parts(part.strip()) == wanted
            for line in response_via.split("\n")
            for part in line.split(",")
        )
    except ValueError:
        return False


def validate_rejection(
    trace: str,
    *,
    expected_status: int,
    local_imsi: str,
    peer_imsi: str,
    domain: str,
    local_ip: str,
    local_port: int | str,
) -> dict[str, object]:
    """Require REGISTER 401/200 then one INVITE rejection and its transaction ACK."""
    result: dict[str, object] = {
        "status": "FAIL",
        "expected_status": expected_status,
        "message_count": 0,
        "provisional_100_count": 0,
        "response_statuses": [],
    }
    if expected_status not in (404, 480):
        return result
    try:
        prefix, suffix = split_registration(trace)
        registration = validate_registration(prefix, local_imsi, domain, local_ip, local_port)
        if registration["status"] != "PASS":
            return result
        registered_ids = {m.header("call-id") for m in registration_messages(prefix)}
        dialog = parse_dialog_messages(suffix)
        result["message_count"] = len(dialog)
        result["response_statuses"] = [m.status for m in dialog if m.status is not None]
        if len(dialog) < 3 or dialog[0].method != "INVITE":
            return result
        request_lines = re.findall(r"^(INVITE|ACK)\s+(\S+)\s+SIP/2\.0\s*$", suffix, re.I | re.M)
        if (
            len(request_lines) != 2
            or [method.upper() for method, _ in request_lines] != ["INVITE", "ACK"]
            or request_lines[0][1] != request_lines[1][1]
            or _uri(request_lines[0][1]) != (peer_imsi, domain.lower())
        ):
            return result
        invite = dialog[0]
        if invite.direction != "sent" or invite.cseq()[1] != "INVITE":
            return result
        call_id = invite.header("call-id")
        if (
            not call_id
            or call_id in registered_ids
            or any(m.header("call-id") != call_id for m in dialog)
        ):
            return result
        identity = (local_imsi, domain.lower())
        peer = (peer_imsi, domain.lower())
        local_contact = (local_imsi, f"{local_ip}:{local_port}".lower())
        if (
            _uri(invite.header("from")) != identity
            or _uri(invite.header("to")) != peer
            or _contact(invite.header("contact")) != local_contact
            or _via_parts(invite.header("via"))[0] != f"{local_ip}:{local_port}".lower()
        ):
            return result
        from_tag = _tag(invite.header("from"))
        invite_seq = invite.cseq()[0]
        index = 1
        while index < len(dialog) and dialog[index].status == 100:
            provisional = dialog[index]
            if (
                provisional.direction != "received"
                or provisional.cseq() != (invite_seq, "INVITE")
                or not _response_via_bound(provisional.header("via"), invite.header("via"))
                or _uri(provisional.header("from")) != identity
                or _uri(provisional.header("to")) != peer
                or _tag(provisional.header("from")) != from_tag
            ):
                return result
            index += 1
        result["provisional_100_count"] = index - 1
        if len(dialog) != index + 2:
            return result
        rejection, ack = dialog[index:]
        if (
            rejection.direction != "received"
            or rejection.status != expected_status
            or rejection.cseq() != (invite_seq, "INVITE")
            or not _response_via_bound(rejection.header("via"), invite.header("via"))
            or _uri(rejection.header("from")) != identity
            or _uri(rejection.header("to")) != peer
            or _tag(rejection.header("from")) != from_tag
            or ack.direction != "sent"
            or ack.method != "ACK"
            or ack.cseq() != (invite_seq, "ACK")
            or _via_parts(ack.header("via")) != _via_parts(invite.header("via"))
            or _uri(ack.header("from")) != identity
            or _uri(ack.header("to")) != peer
            or _tag(ack.header("from")) != from_tag
            or _tag(ack.header("to")) != _tag(rejection.header("to"))
        ):
            return result
        result["status"] = "PASS"
    except (ValueError, IndexError):
        pass
    return result


def validate_inactive_callee(
    trace: str,
    *,
    mode: str,
    local_imsi: str,
    domain: str,
    local_ip: str,
    local_port: int | str,
    requested_expiry: int = 30,
) -> dict[str, object]:
    """Require AKA binding then explicit deregistration or bounded passive expiry.

    This proves the private callee trace saw no INVITE while its SIPp process
    remained alive; the caller's server rejection is checked separately.
    """
    result: dict[str, object] = {
        "status": "FAIL",
        "mode": mode,
        "transaction_count": 0,
        "response_statuses": [],
    }
    if mode not in {"deregister", "expire"} or not 0 < requested_expiry <= 3600:
        return result
    try:
        parsed = parse_dialog_messages(trace)
        transactions, incomplete = _transactions(parsed)
        result["transaction_count"] = len(transactions)
        result["response_statuses"] = [tx.response.status for tx in transactions]
        expected_count = 4 if mode == "deregister" else 2
        if incomplete or len(transactions) != expected_count:
            return result
        call_ids = {message.header("call-id") for message in parsed}
        if len(call_ids) != 1 or not next(iter(call_ids)):
            return result
        identity = (local_imsi, domain.lower())
        contact = (local_imsi, f"{local_ip}:{local_port}".lower())
        cseqs = [tx.request.cseq() for tx in transactions]
        if cseqs != [(index, "REGISTER") for index in range(1, expected_count + 1)]:
            return result
        for tx in transactions:
            if (
                tx.request.direction != "sent"
                or tx.response.direction != "received"
                or _uri(tx.request.header("from")) != identity
                or _uri(tx.request.header("to")) != identity
                or _contact(tx.request.header("contact")) != contact
            ):
                return result
        first, first_401, authorized, first_200 = (
            transactions[0].request,
            transactions[0].response,
            transactions[1].request,
            transactions[1].response,
        )
        if (
            first_401.status != 401
            or first_200.status != 200
            or not _auth_matches(_auth(first.header("authorization")), identity, empty=True)
            or not _auth_matches(_auth(authorized.header("authorization")), identity, empty=False)
            or _expiry(first) != requested_expiry
            or _expiry(authorized) != requested_expiry
            or not 0 < (_expiry(first_200) or 0) <= requested_expiry
            or _contact(first_200.header("contact")) != contact
        ):
            return result
        challenge = _auth(first_401.header("www-authenticate"))
        if (
            challenge.get("algorithm", "").lower() != "akav1-md5"
            or not challenge.get("nonce")
            or _auth(authorized.header("authorization")).get("nonce") != challenge["nonce"]
        ):
            return result
        if mode == "deregister":
            selector, challenge_response, dereg, final = (
                transactions[2].request,
                transactions[2].response,
                transactions[3].request,
                transactions[3].response,
            )
            next_challenge = _auth(challenge_response.header("www-authenticate"))
            if (
                challenge_response.status != 401
                or final.status != 200
                or _expiry(selector) != 0
                or _expiry(dereg) != 0
                or _expiry(final) != 0
                or _contact(final.header("contact")) != contact
                or not _auth_matches(_auth(selector.header("authorization")), identity, empty=True)
                or not _auth_matches(_auth(dereg.header("authorization")), identity, empty=False)
                or next_challenge.get("algorithm", "").lower() != "akav1-md5"
                or not next_challenge.get("nonce")
                or _auth(dereg.header("authorization")).get("nonce") != next_challenge["nonce"]
            ):
                return result
        result["status"] = "PASS"
    except (ValueError, IndexError):
        pass
    return result
