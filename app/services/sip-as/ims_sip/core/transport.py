"""UDP-отправка и локальные SIP-ответы логических AS."""

from .. import runtime
from .sip import all_headers, header, message_call_id, request_method


def establishes_dialog(request: str, status: int) -> bool:
    """1xx/2xx на INVITE и 2xx на UPDATE несут Contact AS (RFC 3261 12.1.1, RFC 3311)."""
    method = request_method(request)
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
        f"Call-ID: {message_call_id(request)}",
        f"CSeq: {header(request, 'CSeq')}",
    ]
    if establishes_dialog(request, status):
        user = contact_user or runtime.voice_user
        lines.append(f"Contact: <sip:{user}@{runtime.bind_ip}:{runtime.bind_port};transport=udp>")
    lines.extend(extra)
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def send(message: str, peer: tuple[str, int]) -> None:
    runtime.sock.sendto(message.encode(), peer)


def send_local_response(
    request: str,
    peer: tuple[str, int],
    status_code: int,
    reason: str,
    *,
    body: str = "",
    to_tag: str = "",
    contact_user: str = "",
    extra: tuple[str, ...] = (),
) -> str:
    """Отправить ответ и вернуть его текст: INVITE-ответы повторяются до ACK/PRACK."""
    response = local_response(request, status_code, reason, body, to_tag, contact_user, extra)
    send(response, peer)
    return response
