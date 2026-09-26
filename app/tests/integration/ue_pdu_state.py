"""Strict read-only metadata parser for UERANSIM ``nr-cli`` output."""

from __future__ import annotations

import ipaddress
import re


class PduStateError(ValueError):
    """CLI output cannot prove the requested IMS PDU state."""


SESSION = re.compile(r"^PDU Session([1-9][0-9]*):\s*$")
FIELD = re.compile(r"^ ([a-z][a-z-]*):\s*(.*?)\s*$")


def parse_ps_list(output: str, ims_dnn: str, ims_cidr: str, require_active: bool = True) -> dict:
    """Select IMS by APN/DNN, never by session order or a static address."""
    if not ims_dnn or not re.fullmatch(r"[A-Za-z0-9.-]+", ims_dnn):
        raise ValueError("Invalid IMS DNN")
    network = ipaddress.IPv4Network(ims_cidr)
    sessions = {}
    current = None
    for line in output.splitlines():
        if not line.strip() or line.startswith("---"):
            continue
        match = SESSION.fullmatch(line)
        if match:
            session_id = int(match.group(1))
            if session_id > 15 or session_id in sessions:
                raise PduStateError("PDU session ID is duplicated or out of range")
            current = {}
            sessions[session_id] = current
            continue
        match = FIELD.fullmatch(line)
        if match and current is not None:
            key, value = match.groups()
            if key in ("state", "session-type", "apn", "address"):
                if key in current or not value:
                    raise PduStateError("PDU session field is duplicated or empty")
                current[key] = value
            elif key not in ("s-nssai", "emergency", "ambr", "data-pending"):
                raise PduStateError("Unknown PDU session field")
            continue
        if line.startswith("  ") and current is not None:
            # Nested s-nssai fields do not identify the PDU session.
            if not re.fullmatch(r"  (sst|sd):\s*\S+", line):
                raise PduStateError("Malformed PDU session nested field")
            continue
        raise PduStateError("Unknown or malformed PDU session output")
    ims = []
    for session_id, fields in sessions.items():
        if set(fields) != {"state", "session-type", "apn", "address"}:
            raise PduStateError("PDU session metadata is incomplete")
        if fields["session-type"] not in ("IPv4", "IPv6", "IPv4v6"):
            raise PduStateError("Unknown PDU session type")
        if fields["apn"].casefold() != ims_dnn.casefold():
            continue
        if fields["session-type"] != "IPv4":
            raise PduStateError("IMS session is not IPv4")
        active = fields["state"] == "PS-ACTIVE"
        if fields["state"] not in ("PS-ACTIVE", "PS-ACTIVE-PENDING", "PS-INACTIVE"):
            raise PduStateError("Unknown IMS PDU state")
        if active:
            try:
                address = ipaddress.IPv4Address(fields["address"])
            except ipaddress.AddressValueError:
                raise PduStateError("Active IMS PDU lacks IPv4 address") from None
            if address not in network:
                raise PduStateError("IMS PDU address is outside configured CIDR")
        elif fields["address"] != "null":
            raise PduStateError("Inactive IMS PDU has an unexpected address")
        ims.append(
            {
                "session_id": session_id,
                "state": fields["state"],
                "type": fields["session-type"],
                "address": str(address) if active else None,
            }
        )
    if len(ims) > 1:
        raise PduStateError("Duplicate IMS PDU sessions")
    if require_active and (not ims or ims[0]["state"] != "PS-ACTIVE"):
        raise PduStateError("Active IMS PDU session is absent")
    return {
        "ims": ims[0] if ims else None,
        "sessions": {
            session_id: {
                "state": fields["state"],
                "type": fields["session-type"],
                "dnn": fields["apn"],
                "address": fields["address"],
            }
            for session_id, fields in sessions.items()
        },
    }


def parse_status(output: str) -> dict:
    """Read only coarse UE registration status; PDU identity comes from ps-list."""
    found = {}
    for line in output.splitlines():
        match = re.fullmatch(r"(cm-state|rm-state|mm-state):\s*(\S+)\s*", line)
        if match:
            key, value = match.groups()
            if key in found:
                raise PduStateError("Duplicate UE status field")
            found[key] = value
    if set(found) != {"cm-state", "rm-state", "mm-state"}:
        raise PduStateError("UE status metadata is incomplete")
    return found
