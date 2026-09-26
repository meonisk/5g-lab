"""Read-only S-CSCF registrar evidence from Kamailio's usrloc RPC."""

from __future__ import annotations

import re
import subprocess


class RegistrarError(RuntimeError):
    """The registrar state could not be read or did not meet the gate."""


def parse_showimpu(output: str, expected_impu: str) -> dict:
    """Parse the one IMPU RPC response without exposing its other private fields."""
    if not output.strip():
        return {"state": "absent", "contacts": []}
    if "error:" in output or not output.lstrip().startswith("{"):
        raise RegistrarError("S-CSCF showimpu response was invalid")
    impu = re.search(r"^\s*impu:\s*(\S+)\s*$", output, re.M)
    state = re.search(r"^\s*state:\s*(\S+)\s*$", output, re.M)
    if not impu or impu.group(1) != expected_impu or not state:
        raise RegistrarError("S-CSCF showimpu identity or state was invalid")
    contacts = []
    in_contacts = False
    current = None
    closed = False
    for line in output.splitlines():
        if re.fullmatch(r"\s*contacts:\s*\{\s*", line):
            in_contacts = True
            continue
        if not in_contacts:
            continue
        if re.fullmatch(r"\t\}\s*", line):
            closed = True
            break
        entry = re.fullmatch(r"\t\t(\S+):\s*\{\s*", line)
        if entry:
            current = {"uri": entry.group(1), "expires": None}
            contacts.append(current)
            continue
        expiry = re.fullmatch(r"\t\t\texpires:\s*(-?\d+)\s*", line)
        if expiry and current is not None:
            current["expires"] = int(expiry.group(1))
        elif line.strip() and not (line.startswith("\t\t\t") or line == "\t\t}"):
            raise RegistrarError("S-CSCF contact block contains an unknown entry")
    if not in_contacts or not closed or any(contact["expires"] is None for contact in contacts):
        raise RegistrarError("S-CSCF contact block was incomplete")
    return {"state": state.group(1), "contacts": contacts}


def read_registration(impu: str, container: str = "lab-scscf", timeout: int = 10) -> dict:
    """Read only; never log raw RPC output, which contains subscriber identity."""
    try:
        call = subprocess.run(
            ["docker", "exec", container, "kamcmd", "ulscscf.showimpu", impu],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RegistrarError("S-CSCF registrar RPC unavailable") from None
    if call.returncode:
        raise RegistrarError("S-CSCF registrar RPC failed")
    return parse_showimpu(call.stdout, impu)


def require_contact(state: dict, expected_uri_prefix: str, present: bool) -> dict:
    """Gate exact target Contact persistence or deletion at one readback instant."""
    matching = [
        contact
        for contact in state["contacts"]
        if contact["uri"].split(";", 1)[0] == expected_uri_prefix
    ]
    if present:
        if state["state"] != "registered" or len(matching) != 1 or matching[0]["expires"] <= 0:
            raise RegistrarError("Expected positive-expiry S-CSCF contact is absent")
    elif matching:
        raise RegistrarError("Deregistered S-CSCF contact is still present")
    return {
        "state": state["state"],
        "matching_contacts": len(matching),
        "expiry": matching[0]["expires"] if matching else None,
    }


def require_inactive_contact(state: dict, expected_uri: str) -> dict:
    """Distinguish nonpositive remaining lifetime from physical record deletion."""
    matching = [c for c in state["contacts"] if c["uri"].split(";", 1)[0] == expected_uri]
    if len(matching) > 1 or any(c["expires"] > 0 for c in matching):
        raise RegistrarError("Old Contact still has a positive remaining lifetime")
    return {
        "state": state["state"],
        "matching_contacts": len(matching),
        "expiry": matching[0]["expires"] if matching else None,
        "physically_absent": not matching,
    }


def require_contact_inventory(
    state: dict, expected_positive: list[str], expected_inactive: list[str] | None = None
) -> dict:
    """Check every canonical Contact, including stale nonpositive records.

    Inactive targets may be absent or retained with nonpositive lifetime.
    This does not itself prove physical deletion; use require_contact(False).
    """
    inactive = expected_inactive if expected_inactive is not None else []
    if not isinstance(expected_positive, list) or not isinstance(inactive, list):
        raise RegistrarError("Contact inventory expectations are invalid")
    wanted = expected_positive + inactive
    if any(not isinstance(uri, str) or not uri or ";" in uri for uri in wanted):
        raise RegistrarError("Contact inventory URI is invalid")
    if len(set(wanted)) != len(wanted):
        raise RegistrarError("Contact inventory expectation is duplicated")
    if not isinstance(state, dict) or not isinstance(state.get("contacts"), list):
        raise RegistrarError("Contact inventory state is invalid")
    if expected_positive and state.get("state") != "registered":
        raise RegistrarError("Positive Contact has no registered IMPU state")
    found: dict[str, int] = {}
    for contact in state["contacts"]:
        if not isinstance(contact, dict):
            raise RegistrarError("Contact inventory entry is invalid")
        uri, expiry = contact.get("uri"), contact.get("expires")
        if not isinstance(uri, str) or type(expiry) is not int:
            raise RegistrarError("Contact inventory entry is malformed")
        canonical = uri.split(";", 1)[0]
        if canonical not in wanted or canonical in found:
            raise RegistrarError("Unexpected or duplicate Contact in inventory")
        found[canonical] = expiry
    if any(found.get(uri, 0) <= 0 for uri in expected_positive):
        raise RegistrarError("Expected positive Contact is missing or inactive")
    if any(found.get(uri, 0) > 0 for uri in inactive):
        raise RegistrarError("Expected inactive Contact remains positive")
    return {
        "state": state.get("state"),
        "positive_count": len(expected_positive),
        "inactive_present_count": sum(uri in found for uri in inactive),
        "inactive_absent_count": sum(uri not in found for uri in inactive),
        "positive_expiries": [found[uri] for uri in expected_positive],
    }
