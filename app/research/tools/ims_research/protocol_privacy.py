"""Reduce protocol-heavy diagnostics to bounded, content-free metadata."""

from __future__ import annotations

import re

# Wire-level SIP, SDP, and Diameter diagnostics can contain auth vectors and
# media descriptions across arbitrary continuation lines. Retaining selected
# lines from such a dump would make its privacy boundary depend on log format.
PROTOCOL_RE = re.compile(
    r"(?im)(?:^|\s)(?:SIP/2\.0|INVITE sip:|REGISTER sip:|Authorization:|"
    r"Proxy-Authorization:|WWW-Authenticate:|Authentication-Info:|"
    r"Content-Type:\s*application/sdp|m=audio\s|a=rtpmap:|"
    r"Diameter(?:\s|:)|RAND\s*[:=]|XRES\s*[:=]|KASME\s*[:=]|"
    r"hex(?:adecimal)?\s*(?:dump|payload)\b)",
)
PROTOCOL_SOURCES = frozenset(
    {"lab-pcscf", "lab-icscf", "lab-scscf", "lab-pyhss", "lab-rtpengine", "lab-sip-as"}
)
EVENTS = (
    ("pdu_session_success", re.compile(r"PDU Session establishment is successful", re.I)),
    ("registration_success", re.compile(r"Initial Registration is successful", re.I)),
    ("sip_register", re.compile(r"\bREGISTER\s+sip:", re.I)),
    ("sip_invite", re.compile(r"\bINVITE\s+sip:", re.I)),
    ("diameter_mention", re.compile(r"\bDiameter\b", re.I)),
)


def sanitize_protocol_log(value: str, source: str = "") -> str:
    if source not in PROTOCOL_SOURCES and not PROTOCOL_RE.search(value):
        return value
    lines = value.splitlines()
    summary = [
        "[PROTOCOL_CONTENT_REMOVED: SIP/SDP/Diameter/auth and adjacent diagnostics]",
        f"[SOURCE: {source if source in PROTOCOL_SOURCES else 'detected-protocol-content'}]",
        f"[INPUT_LINE_COUNT: {len(lines)}]",
    ]
    summary.extend(
        f"[{name}: {sum(bool(pattern.search(line)) for line in lines)}]" for name, pattern in EVENTS
    )
    return "\n".join(summary) + "\n"
