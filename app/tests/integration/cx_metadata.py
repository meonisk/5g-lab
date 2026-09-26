"""Strict, privacy-preserving metadata extraction from a Cx Ethernet PCAP."""

from __future__ import annotations

import hashlib
import hmac
import struct
from collections import defaultdict
from pathlib import Path

if __package__:
    from .cx_transport import IncompleteCapture, _streams
else:
    from cx_transport import IncompleteCapture, _streams

CX_COMMANDS = {300: "UAR", 303: "MAR", 301: "SAR"}
CX_APPLICATION = 16777216
SUCCESS = 2001
THREE_GPP_VENDOR = 10415
CX_REGISTRATION_RESULTS = {"UAR": {2001, 2002}, "MAR": set(), "SAR": set()}


def _pseudonym(value: bytes, key: bytes) -> str:
    return hmac.new(key, value, hashlib.sha256).hexdigest()[:24]


def identity_pseudonym(identity: str, key: bytes) -> str:
    """Let a caller bind expected IMS private identities without exporting them."""
    if not identity or not key:
        raise ValueError("Identity and pseudonym key are required")
    return _pseudonym(identity.encode(), key)


def challenge_fingerprint(challenge: bytes, key: bytes) -> str:
    """Hash a decoded 32-byte SIP AKA challenge for MAA comparison."""
    if len(challenge) != 32 or not key:
        raise ValueError("Expected a 32-byte AKA challenge and pseudonym key")
    return _pseudonym(challenge, key)


def _avps(body: bytes, key: bytes) -> dict:
    found = {}
    offset = 0
    while offset < len(body):
        if len(body) - offset < 8:
            raise IncompleteCapture("Truncated Diameter AVP")
        code = int.from_bytes(body[offset : offset + 4], "big")
        flags = body[offset + 4]
        length = int.from_bytes(body[offset + 5 : offset + 8], "big")
        header = 12 if flags & 0x80 else 8
        if length < header or offset + length > len(body):
            raise IncompleteCapture("Invalid Diameter AVP length")
        value = body[offset + header : offset + length]
        if code == 263:
            found["session"] = _pseudonym(value, key)
        elif code == 1:
            found["user"] = _pseudonym(value, key)
        elif code == 601 and "public_user" not in found:
            found["public_user"] = _pseudonym(value, key)
        elif code == 268:
            if len(value) != 4:
                raise IncompleteCapture("Invalid Diameter result code")
            if "result" in found:
                raise IncompleteCapture("Multiple Diameter result AVPs")
            found["result"] = int.from_bytes(value, "big")
            found["result_namespace"] = "base"
        elif code == 297:
            if "result" in found:
                raise IncompleteCapture("Multiple Diameter result AVPs")
            nested = {}
            inner = 0
            while inner < len(value):
                if len(value) - inner < 8:
                    raise IncompleteCapture("Truncated Experimental-Result AVP")
                nested_code = int.from_bytes(value[inner : inner + 4], "big")
                nested_flags = value[inner + 4]
                nested_length = int.from_bytes(value[inner + 5 : inner + 8], "big")
                nested_header = 12 if nested_flags & 0x80 else 8
                if nested_length < nested_header or inner + nested_length > len(value):
                    raise IncompleteCapture("Invalid Experimental-Result AVP")
                nested_value = value[inner + nested_header : inner + nested_length]
                if nested_code in (266, 298):
                    if len(nested_value) != 4 or nested_code in nested:
                        raise IncompleteCapture("Invalid Experimental-Result value")
                    nested[nested_code] = int.from_bytes(nested_value, "big")
                inner += (nested_length + 3) & ~3
            if set(nested) != {266, 298}:
                raise IncompleteCapture("Experimental-Result vendor or code missing")
            found["result"] = nested[298]
            found["result_namespace"] = (
                "3gpp" if nested[266] == THREE_GPP_VENDOR else "other_vendor"
            )
            found["vendor_id"] = nested[266]
        elif code == 612:
            inner = 0
            challenges = found.setdefault("challenge_fingerprints", [])
            while inner < len(value):
                if len(value) - inner < 8:
                    raise IncompleteCapture("Truncated SIP-Auth-Data-Item")
                nested_code = int.from_bytes(value[inner : inner + 4], "big")
                nested_flags = value[inner + 4]
                nested_length = int.from_bytes(value[inner + 5 : inner + 8], "big")
                nested_header = 12 if nested_flags & 0x80 else 8
                if nested_length < nested_header or inner + nested_length > len(value):
                    raise IncompleteCapture("Invalid SIP-Auth-Data-Item")
                if nested_code == 609:
                    challenge = value[inner + nested_header : inner + nested_length]
                    if len(challenge) != 32:
                        raise IncompleteCapture("Unexpected SIP-Authenticate length")
                    challenges.append(challenge_fingerprint(challenge, key))
                inner += (nested_length + 3) & ~3
        offset += (length + 3) & ~3
        if offset > len(body):
            raise IncompleteCapture("Truncated Diameter AVP padding")
    if "user" not in found and "public_user" in found:
        found["user"] = found["public_user"]
    found.pop("public_user", None)
    return found


def _successful(transaction: dict) -> bool:
    if transaction["result_namespace"] == "base":
        return transaction["result"] == SUCCESS
    return (
        transaction["result_namespace"] == "3gpp"
        and transaction["vendor_id"] == THREE_GPP_VENDOR
        and transaction["result"] in CX_REGISTRATION_RESULTS[transaction["command"]]
    )


def _messages(stream: bytes, key: bytes) -> list[dict]:
    messages = []
    offset = 0
    while offset < len(stream):
        if len(stream) - offset < 20:
            raise IncompleteCapture("Truncated Diameter header")
        if stream[offset] != 1:
            raise IncompleteCapture("Invalid Diameter version or stream boundary")
        length = int.from_bytes(stream[offset + 1 : offset + 4], "big")
        if length < 20 or length > len(stream) - offset:
            raise IncompleteCapture("Truncated Diameter message")
        flags = stream[offset + 4]
        command = int.from_bytes(stream[offset + 5 : offset + 8], "big")
        application, hop, end = struct.unpack_from("!III", stream, offset + 8)
        if application == CX_APPLICATION and command in CX_COMMANDS:
            fields = _avps(stream[offset + 20 : offset + length], key)
            messages.append(
                {
                    "command": CX_COMMANDS[command],
                    "application": application,
                    "request": bool(flags & 0x80),
                    "hop": hop,
                    "end": end,
                    **fields,
                }
            )
        offset += length
    return messages


def summarize_pcap(
    path: Path,
    key: bytes,
    port: int = 3868,
    expected_users: set[str] | None = None,
    expected_commands: dict[str, set[str]] | None = None,
) -> dict:
    """Require successful UAR/MAR/SAR pairs for each of two pseudonymous users."""
    if not key or not 1 <= port <= 65535:
        raise ValueError("Pseudonym key and valid Cx port are required")
    try:
        events = [event for stream in _streams(path, port) for event in _messages(stream, key)]
        if not events:
            raise IncompleteCapture("No Cx UAR/MAR/SAR messages")
        requests = defaultdict(list)
        answers = defaultdict(list)
        transactions = []
        issues = []
        for event in events:
            token = (
                event["command"],
                event["application"],
                event["hop"],
                event["end"],
                event.get("session"),
            )
            if not event.get("session"):
                raise IncompleteCapture("Cx Session-Id missing")
            if event["request"]:
                if not event.get("user"):
                    raise IncompleteCapture("Cx user identity missing")
                requests[token].append(event)
            else:
                if "result" not in event:
                    issues.append("Cx answer result missing")
                    continue
                answers[token].append(event)
        for token in requests.keys() | answers.keys():
            if len(requests[token]) != len(answers[token]):
                issues.append("Cx request/answer count mismatch")
            # Reusing an HBH/ETE/Session tuple would make identity attribution
            # ambiguous even if TCP packets were otherwise complete.
            if len(requests[token]) != 1:
                issues.append("Ambiguous Cx transaction identity")
                continue
            for request, event in zip(requests[token], answers[token]):
                if event.get("user") and event["user"] != request["user"]:
                    issues.append("Cx answer identity mismatch")
                    continue
                transactions.append(
                    {
                        "command": event["command"],
                        "application": event["application"],
                        "hop": event["hop"],
                        "end": event["end"],
                        "session": event["session"],
                        "user": request["user"],
                        "request_flags": [request["request"], event["request"]],
                        "result": event["result"],
                        "result_namespace": event["result_namespace"],
                        **({"vendor_id": event["vendor_id"]} if "vendor_id" in event else {}),
                        **(
                            {"challenge_fingerprints": event["challenge_fingerprints"]}
                            if "challenge_fingerprints" in event
                            else {}
                        ),
                    }
                )
        users = {item["user"] for item in transactions}
        if expected_commands is not None:
            if len(expected_commands) != 2 or any(
                not commands or not commands <= set(CX_COMMANDS.values())
                for commands in expected_commands.values()
            ):
                raise ValueError("Expected two users with valid Cx command sets")
            expected_users = set(expected_commands)
        if expected_users is not None:
            expected = {identity_pseudonym(identity, key) for identity in expected_users}
            if len(expected) != 2 or not users <= expected:
                return {
                    "status": "FAIL",
                    "reason": "Cx identity mismatch",
                    "transactions": transactions,
                }
            if users != expected:
                issues.append("Expected Cx user missing")
        elif len(users) != 2:
            issues.append("Expected two Cx users")
        required_by_user = (
            {
                identity_pseudonym(identity, key): commands
                for identity, commands in expected_commands.items()
            }
            if expected_commands is not None
            else {user: set(CX_COMMANDS.values()) for user in users}
        )
        for user, required in required_by_user.items():
            observed = {item["command"] for item in transactions if item["user"] == user}
            if observed - required:
                return {
                    "status": "FAIL",
                    "reason": "Unexpected Cx command for user",
                    "transactions": transactions,
                }
            if required - observed:
                issues.append("Missing expected Cx command for user")
        if any(not _successful(item) for item in transactions):
            return {
                "status": "FAIL",
                "reason": "Cx non-success or unsupported result",
                "transactions": transactions,
                **({"coverage": "INCOMPLETE", "issues": sorted(set(issues))} if issues else {}),
            }
        if issues:
            return {
                "status": "INCOMPLETE",
                "reason": "; ".join(sorted(set(issues))),
                "transactions": transactions,
            }
        return {"status": "PASS", "transactions": transactions}
    except IncompleteCapture as error:
        return {"status": "INCOMPLETE", "reason": str(error), "transactions": []}
