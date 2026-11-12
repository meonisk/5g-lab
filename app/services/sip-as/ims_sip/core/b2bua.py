"""B2BUA: две ноги одного звонка через MRF.

Нога A — диалог звонящего, на который отвечает SIP AS. Нога B — новый диалог SIP AS
(свой Call-ID и From tag), который уходит в S-CSCF с ISC-меткой ноги A, чтобы S-CSCF
продолжил цепочку iFC со следующего приоритета. Медиа обеих ног идёт на Voice Agent.
"""

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import runtime
from . import dialogs
from .mrf import media_is_anchored, voice_agent_sdp
from .sdp import offered_media_endpoint
from .sip import (
    all_headers,
    angle_uri,
    local_tag,
    message_call_id,
    request_method,
    route_values,
    status_code,
    tag_of,
    transaction_branch,
    value_of,
)
from .transport import send, send_local_response

CONTACT_USER = "b2bua"
BRANCH_PREFIX = "z9hG4bK-b2b-"
TOP_VIA = re.compile(r"(?im)^(?:Via|v)\s*:([^\r\n,]*)")
OWN_BRANCH = re.compile(r"branch=(z9hG4bK-b2b-[^;\s]+)")


@dataclass
class Leg:
    call_id: str
    local_tag: str
    local_uri: str
    remote_uri: str
    remote_target: str
    remote_tag: str = ""
    route_set: list[str] = field(default_factory=list)
    cseq: int = 0
    media: tuple[str, int] | None = None


@dataclass
class Call:
    a: Leg
    b: Leg
    a_invite: str
    a_peer: tuple[str, int]
    languages: tuple[str, str]
    on_answer: Callable[["Call", str], bool]
    on_bye: Callable[["Call"], None]
    b_invite: str = ""
    b_branch: str = ""
    state: str = "calling"  # calling -> early -> answered -> ended
    ringing_sent: bool = False
    answered: bool = False
    b_final: bool = False


def find(call_id: str) -> Call | None:
    return runtime.b2bua_calls.get(call_id)


def strip_tag(value: str) -> str:
    return re.sub(r";tag=[^;>\s]*", "", value)


def contact() -> str:
    return f"<sip:{CONTACT_USER}@{runtime.bind_ip}:{runtime.bind_port};transport=udp>"


def leg_b_routes(a_request: str) -> list[str]:
    """Route ноги B по SIP_AS_LEG_B_ROUTE.

    isc — ISC Route ноги A без своего: S-CSCF продолжит цепочку iFC со следующего
    приоритета. orig — fallback F1 spike: S-CSCF начинает цепочку заново через
    sip:orig@, translate пропускает свою ногу B (dialogs.is_own).
    """
    if runtime.leg_b_route == "orig":
        return [f"<sip:orig@scscf.{runtime.ims_domain}:{runtime.scscf[1]};lr>"]
    return route_values(a_request)[1:]


def leg_b_invite(call: Call, a_request: str, request_uri: str) -> str:
    routes = leg_b_routes(a_request)
    body = voice_agent_sdp()
    lines = [
        f"INVITE {request_uri} SIP/2.0",
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch={call.b_branch}",
        "Max-Forwards: 70",
    ]
    if routes:
        lines.append("Route: " + ", ".join(routes))
    lines += all_headers(a_request, "P-Asserted-Identity")
    lines += [
        f"From: {call.b.local_uri};tag={call.b.local_tag}",
        f"To: {call.b.remote_uri}",
        f"Call-ID: {call.b.call_id}",
        "CSeq: 1 INVITE",
        f"Contact: {contact()}",
        "Content-Type: application/sdp",
        f"Content-Length: {len(body.encode())}",
    ]
    return "\r\n".join(lines) + "\r\n\r\n" + body


def start(a_request, peer, request_uri, languages, on_answer, on_bye) -> Call:
    """Принять ногу A (100 Trying) и отправить ногу B в S-CSCF."""
    a_call_id = message_call_id(a_request)
    send_local_response(a_request, peer, 100, "Trying")
    caller = value_of(a_request, "From")
    a = Leg(
        call_id=a_call_id,
        local_tag=local_tag(a_call_id),
        local_uri=strip_tag(value_of(a_request, "To")),
        remote_uri=strip_tag(caller),
        remote_target=angle_uri(value_of(a_request, "Contact")),
        remote_tag=tag_of(caller),
        route_set=route_values(a_request, "Record-Route"),
        media=offered_media_endpoint(a_request),
    )
    b = Leg(
        call_id=dialogs.new_call_id(),
        local_tag=secrets.token_hex(8),
        local_uri=strip_tag(caller),
        remote_uri=f"<{request_uri}>",
        remote_target=request_uri,
        cseq=1,
    )
    call = Call(
        a=a,
        b=b,
        a_invite=a_request,
        a_peer=peer,
        languages=languages,
        on_answer=on_answer,
        on_bye=on_bye,
        b_branch=BRANCH_PREFIX + secrets.token_hex(8),
    )
    call.b_invite = leg_b_invite(call, a_request, request_uri)
    runtime.b2bua_calls[a.call_id] = call
    runtime.b2bua_calls[b.call_id] = call
    runtime.b2bua_branches[call.b_branch] = call
    send(call.b_invite, runtime.scscf)
    print(f"AS b2bua leg_b call_id={b.call_id} for call_id={a.call_id}", flush=True)
    return call


def reply_a(call: Call, status: int, reason: str, body: str = "") -> None:
    send_local_response(
        call.a_invite,
        call.a_peer,
        status,
        reason,
        body=body,
        to_tag=call.a.local_tag,
        contact_user=CONTACT_USER,
    )


def dialog_request(leg: Leg, method: str, *, cseq: int | None = None, body: str = ""):
    """Запрос внутри диалога ноги; уходит в S-CSCF, дальше — по route set ноги."""
    if cseq is None:
        leg.cseq += 1
        cseq = leg.cseq
    branch = BRANCH_PREFIX + secrets.token_hex(8)
    to = leg.remote_uri + (f";tag={leg.remote_tag}" if leg.remote_tag else "")
    lines = [
        f"{method} {leg.remote_target} SIP/2.0",
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch={branch}",
        "Max-Forwards: 70",
    ]
    if leg.route_set:
        lines.append("Route: " + ", ".join(leg.route_set))
    lines += [
        f"From: {leg.local_uri};tag={leg.local_tag}",
        f"To: {to}",
        f"Call-ID: {leg.call_id}",
        f"CSeq: {cseq} {method}",
        f"Contact: {contact()}",
    ]
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body, branch


def send_in_dialog(call: Call, leg: Leg, method: str) -> None:
    message, branch = dialog_request(leg, method)
    runtime.b2bua_branches[branch] = call
    send(message, runtime.scscf)


def ack_answer(call: Call) -> None:
    """ACK на 2xx — отдельная транзакция с номером CSeq INVITE."""
    message, _ = dialog_request(call.b, "ACK", cseq=1)
    send(message, runtime.scscf)


def ack_failure(call: Call, response: str) -> None:
    """ACK на финальный не-2xx — в транзакции INVITE ноги B (тот же branch и Route)."""
    head = call.b_invite.split("\r\n\r\n", 1)[0].split("\r\n")
    names = r"(Via|Max-Forwards|Route|From|Call-ID)\s*:"
    keep = [line for line in head[1:] if re.match(names, line)]
    lines = [
        f"ACK {head[0].split(' ')[1]} SIP/2.0",
        *keep,
        f"To: {value_of(response, 'To')}",
        "CSeq: 1 ACK",
        "Content-Length: 0",
    ]
    send("\r\n".join(lines) + "\r\n\r\n", runtime.scscf)


def handle_response(message: str) -> bool:
    """Ответ на INVITE ноги B или на свой запрос в диалоге; False — ответ не B2BUA."""
    # Только верхний Via: ответ ноги B, идущий через record AS (тот же процесс),
    # несёт Via B2BUA ниже и возвращается прокси-путём в S-CSCF.
    top = TOP_VIA.search(message)
    match = OWN_BRANCH.search(top.group(1)) if top else None
    if match is None:
        return False
    branch = match.group(1)
    call = runtime.b2bua_branches.get(branch)
    status = status_code(message)
    if call is None:
        print(f"AS b2bua dropped response for unknown branch {branch}", flush=True)
        return True
    if branch != call.b_branch:
        if status >= 200:
            runtime.b2bua_branches.pop(branch, None)
        return True
    if status < 200:
        leg_b_progress(call, status)
    elif status < 300:
        leg_b_answered(call, message)
    else:
        leg_b_failed(call, message, status)
    return True


def leg_b_progress(call: Call, status: int) -> None:
    """Звонящий слышит 180 один раз, пока UE2 не ответил."""
    if status in (180, 183) and call.state == "calling" and not call.ringing_sent:
        call.ringing_sent = True
        call.state = "early"
        reply_a(call, 180, "Ringing")
        print(f"AS b2bua ringing call_id={call.a.call_id}", flush=True)


def leg_b_answered(call: Call, response: str) -> None:
    """200 от UE2: ACK, привязка ног услугой и только потом 200 звонящему."""
    b = call.b
    if call.answered:
        ack_answer(call)
        return
    b.remote_tag = tag_of(value_of(response, "To"))
    b.remote_target = angle_uri(value_of(response, "Contact")) or b.remote_target
    b.route_set = list(reversed(route_values(response, "Record-Route")))
    b.media = offered_media_endpoint(response)
    call.b_final = True
    ack_answer(call)
    if call.state == "ended":
        # Звонящий отменил вызов раньше, чем пришёл ответ UE2.
        send_in_dialog(call, b, "BYE")
        runtime.b2bua_branches.pop(call.b_branch, None)
        return
    anchored = b.media is not None and media_is_anchored(*b.media)
    if not anchored or not call.on_answer(call, response):
        print(f"AS b2bua answer failed call_id={call.a.call_id}", flush=True)
        send_in_dialog(call, b, "BYE")
        reply_a(call, 500, "Media Unavailable")
        end(call)
        return
    call.answered = True
    call.state = "answered"
    reply_a(call, 200, "OK", voice_agent_sdp())
    print(f"AS b2bua answered call_id={call.a.call_id} leg_b={b.call_id}", flush=True)


def leg_b_failed(call: Call, response: str, status: int) -> None:
    """486/480/408 и любой финальный не-2xx от UE2 — тот же ответ звонящему."""
    call.b_final = True
    ack_failure(call, response)
    if call.state == "ended":
        runtime.b2bua_branches.pop(call.b_branch, None)
        return
    reply_a(call, status, response.split("\r\n", 1)[0].split(" ", 2)[2])
    print(f"AS b2bua leg_b failed call_id={call.a.call_id} status={status}", flush=True)
    end(call)


def end(call: Call) -> None:
    """Забыть обе ноги и отдать услуге освобождение MRF и пары."""
    if call.state == "ended":
        return
    call.state = "ended"
    runtime.b2bua_calls.pop(call.a.call_id, None)
    runtime.b2bua_calls.pop(call.b.call_id, None)
    if call.b_final:
        runtime.b2bua_branches.pop(call.b_branch, None)
    dialogs.forget(call.b.call_id)
    call.on_bye(call)


def same_transaction(message: str, request: str) -> bool:
    return transaction_branch(message) == transaction_branch(request)


def cancel_b(call: Call) -> None:
    """CANCEL ноги B: те же Request-URI, Via, Route, From, To и Call-ID, что у INVITE."""
    head = call.b_invite.split("\r\n\r\n", 1)[0].split("\r\n")
    names = r"(Via|Max-Forwards|Route|From|To|Call-ID)\s*:"
    keep = [line for line in head[1:] if re.match(names, line)]
    lines = [
        f"CANCEL {head[0].split(' ')[1]} SIP/2.0",
        *keep,
        "CSeq: 1 CANCEL",
        "Content-Length: 0",
    ]
    send("\r\n".join(lines) + "\r\n\r\n", runtime.scscf)


def handle_request(message: str, peer: tuple[str, int]) -> None:
    """Запрос в диалоге ноги A или B: ответить на своей ноге, другой — только BYE/CANCEL."""
    call_id = message_call_id(message)
    call = find(call_id)
    method = request_method(message)
    leg = call.a if call_id == call.a.call_id else call.b
    if method == "ACK":
        return
    if method == "INVITE" and leg is call.a and same_transaction(message, call.a_invite):
        send_local_response(message, peer, 100, "Trying")  # повтор INVITE ноги A
        return
    if method in {"INVITE", "UPDATE"}:
        # Удержание и session timer: MRF остаётся точкой медиа, другая нога не трогается.
        send_local_response(
            message,
            peer,
            200,
            "OK",
            body=voice_agent_sdp(),
            to_tag=leg.local_tag,
            contact_user=CONTACT_USER,
        )
        print(f"AS b2bua refreshed {method} call_id={call_id}", flush=True)
        return
    send_local_response(message, peer, 200, "OK", to_tag=leg.local_tag)
    if method == "CANCEL" and leg is call.a and not call.answered:
        reply_a(call, 487, "Request Terminated")
        if not call.b_final:
            cancel_b(call)
        print(f"AS b2bua cancelled call_id={call.a.call_id}", flush=True)
        end(call)
    elif method == "BYE":
        other = call.b if leg is call.a else call.a
        if call.answered:
            send_in_dialog(call, other, "BYE")
        side = "a" if leg is call.a else "b"
        print(f"AS b2bua ended call_id={call.a.call_id} by={side}", flush=True)
        end(call)
