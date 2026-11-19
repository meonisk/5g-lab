"""SIP header parsing and local response construction."""

import re

from . import runtime


def header(message, name):
    match = re.search(rf"(?im)^{re.escape(name)}\s*:\s*(.+)$", message)
    return match.group(1).strip() if match else ""


def all_headers(message, long_name, compact_name=None):
    names = re.escape(long_name)
    if compact_name:
        names += "|" + re.escape(compact_name)
    # ``.`` also captures the CR in a CRLF-terminated SIP line.  Keeping it
    # would produce ``\r\r\n`` when the local response is assembled and
    # Kamailio would reject the response as having malformed required headers.
    return [line.rstrip("\r") for line in re.findall(rf"(?im)^((?:{names})\s*:\s*.+)$", message)]


def establishes_dialog(request, status):
    """1xx/2xx to INVITE and 2xx to UPDATE carry the AS Contact (RFC 3261, 3311)."""
    method = request.split(" ", 1)[0]
    if method == "INVITE":
        return 100 < status < 300
    return method == "UPDATE" and 200 <= status < 300


def local_response(request, status, reason, body="", to_tag="", contact_user=None, extra=()):
    lines = [f"SIP/2.0 {status} {reason}"]
    lines.extend(all_headers(request, "Via", "v"))
    lines.extend(all_headers(request, "Record-Route"))
    from_value = header(request, "From") or header(request, "f")
    to_value = header(request, "To") or header(request, "t")
    if to_tag and ";tag=" not in to_value:
        to_value += f";tag={to_tag}"
    lines += [
        f"From: {from_value}",
        f"To: {to_value}",
        f"Call-ID: {header(request, 'Call-ID') or header(request, 'i')}",
        f"CSeq: {header(request, 'CSeq')}",
    ]
    if establishes_dialog(request, status):
        lines.append(
            f"Contact: <sip:{contact_user or runtime.voice_user}@{runtime.bind_ip}:{runtime.bind_port};transport=udp>"
        )
    lines.extend(extra)
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body
