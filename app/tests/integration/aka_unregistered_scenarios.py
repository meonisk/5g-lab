"""Render private SIPp scenarios for an unregistered-callee rejection gate."""

from pathlib import Path

try:
    from . import aka_call_scenarios, aka_lifecycle_scenario
except ImportError:  # Direct integration-script imports.
    import aka_call_scenarios
    import aka_lifecycle_scenario


def _bounded(settings: dict, name: str, default: int, low: int, high: int) -> int:
    value = int(settings.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def render_callee(path: Path, cfg: dict, ue: int, mode: str) -> Path:
    """Register, explicitly deregister or expire, then keep one SIP socket alive."""
    if ue not in (1, 2) or mode not in ("deregister", "expire"):
        raise ValueError("ue must be 1 or 2; mode must be deregister or expire")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    hold = _bounded(cfg, "SIP_AKA_INACTIVE_HOLD_SECONDS", 420, 60, 900)
    expiry = _bounded(cfg, "SIP_AKA_EXPIRY_SECONDS", 30, 1, 300)
    initial = aka_lifecycle_scenario._initial_body(path, cfg, ue)
    if mode == "expire":
        # Both initial REGISTER messages must request the same short binding.
        if initial.count("Expires: 300") != 2:
            raise ValueError("AKA initial registration template expiry changed")
        initial = initial.replace("Expires: 300", f"Expires: {expiry}")
        after = ""
    else:
        after = '<pause milliseconds="5000"/>\n' + aka_lifecycle_scenario._exchange(cfg, ue, 3, 0)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<scenario name="AKA callee {mode}">\n'
        + initial
        + after
        + f'<pause milliseconds="{hold * 1000}"/>\n'
        + "</scenario>\n"
    )
    path.write_text(xml, encoding="utf-8", newline="\n")
    return path


def render_caller(directory: Path, cfg: dict, caller: int, expected_status: int = 404) -> Path:
    """Register, open a fresh SIPp call, then ACK the configured non-2xx result."""
    if caller not in (1, 2) or expected_status not in (404, 480):
        raise ValueError("caller must be 1 or 2; expected_status must be 404 or 480")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    callee = 3 - caller
    delay = _bounded(cfg, "SIP_AKA_REJECTION_INVITE_DELAY_MS", 5000, 0, 30000)
    register = aka_call_scenarios._register_body(directory, cfg, caller)
    domain = cfg["IMS_DOMAIN"]
    caller_imsi = cfg[f"UE{caller}_IMSI"]
    callee_imsi = cfg[f"UE{callee}_IMSI"]
    from_uri = f"sip:{caller_imsi}@{domain}"
    to_uri = f"sip:{callee_imsi}@{domain}"
    branch = "z9hG4bK-[pid]-[call_number]-invite"
    invite = f"""INVITE {to_uri} SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch={branch}
Max-Forwards: 70
From: <{from_uri}>;tag=[call_number]
To: <{to_uri}>
Call-ID: [call_id]
CSeq: 1 INVITE
Contact: <sip:{caller_imsi}@[local_ip]:[local_port]>
Route: [$service_route]
Content-Length: 0"""
    # Non-2xx ACK is part of the INVITE transaction: original Request-URI,
    # same Via branch/CSeq/From tag, and the rejection response's To tag.
    ack = f"""ACK {to_uri} SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch={branch}
Max-Forwards: 70
From: <{from_uri}>;tag=[call_number]
To: <{to_uri}>[peer_tag_param]
Call-ID: [call_id]
CSeq: 1 ACK
Route: [$service_route]
Content-Length: 0"""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<scenario name="AKA rejected unregistered callee">\n'
        '<User variables="registered,service_route"/>\n'
        '<nop next="2" test="registered"/>\n'
        + register
        + '<nop next="19"><action><assignstr assign_to="registered" value="yes"/></action></nop>\n'
        + '<label id="2"/>\n'
        + f'<pause milliseconds="{delay}"/>\n'
        + aka_call_scenarios._message(invite, retrans=500)
        + '<recv response="100" optional="true"/>\n'
        + f'<recv response="{expected_status}"/>\n'
        + aka_call_scenarios._message(ack)
        + '<label id="19"/>\n'
        + "</scenario>\n"
    )
    path = directory / f"ue{caller}-rejection-caller.xml"
    path.write_text(xml, encoding="utf-8", newline="\n")
    return path
