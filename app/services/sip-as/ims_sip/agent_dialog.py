"""UAS-диалог AI-услуги: 100rel, QoS preconditions, UPDATE и завершение.

Штатный IMS-клиент телефона обычно предлагает preconditions и 100rel
(TS 24.229). Тогда AS отвечает надёжным 183 с SDP-ответом, ждёт PRACK,
затем UPDATE о готовности QoS телефона и только после этого шлёт 200 OK.
Клиент без этих расширений получает прежний немедленный 200 OK с SDP.
"""

import ipaddress
import re
import threading
import time

from . import runtime
from .control import notify_adapter, notify_voice, stop_adapter, stop_voice
from .messages import header, local_response
from .preconditions import (
    SUPPORTED,
    answer_lines,
    offerer_ready,
    required,
    sdp_body,
    supported,
    unsupported_required,
    uses_preconditions,
)
from .sdp import accepts_pcmu

ALLOW = "Allow: INVITE, ACK, BYE, CANCEL, PRACK, UPDATE, OPTIONS"


def send_local_response(
    request, peer, status_code, reason, *, body="", to_tag="", contact_user="", extra=()
):
    response = local_response(request, status_code, reason, body, to_tag, contact_user, extra)
    runtime.sock.sendto(response.encode(), peer)
    return response


def offered_media_endpoint(message: str) -> tuple[str, int] | None:
    """Извлечь IPv4 и RTP-порт из SDP offer."""
    connection_match = re.search(r"(?im)^c=IN IP4 ([^\s]+)", message)
    media_match = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
    if connection_match is None or media_match is None:
        return None
    try:
        return str(ipaddress.ip_address(connection_match.group(1))), int(media_match.group(1))
    except ValueError:
        return None


def media_is_anchored(offered_ip: str, offered_port: int) -> bool:
    """AI Agent принимает RTP только от настроенного пула RTPengine."""
    return (
        offered_ip == runtime.rtpengine_ip
        and runtime.rtp_port_min <= offered_port <= runtime.rtp_port_max
    )


def voice_agent_sdp(offer_sdp: str = "") -> str:
    """Ответ для единственного кодека PCMU/8000 и, при необходимости, QoS."""
    lines = [
        "v=0",
        f"o=voice-agent 1 1 IN IP4 {runtime.voice_ip}",
        "s=IMS Voice Agent",
        f"c=IN IP4 {runtime.voice_ip}",
        "t=0 0",
        f"m=audio {runtime.voice_rtp_port} RTP/AVP 0",
        "a=rtpmap:0 PCMU/8000",
        "a=ptime:20",
        "a=sendrecv",
        *answer_lines(offer_sdp),
    ]
    return "\r\n".join(lines) + "\r\n"


def start_agent_call(message, call_id, offered_ip, offered_port, service_mode) -> bool:
    """Запустить Voice Agent и наблюдение; вызывается один раз перед 200 OK."""
    try:
        notify_voice(call_id, offered_ip, offered_port, service_mode)
    except Exception as error:
        print(f"AS voice unavailable call_id={call_id} type={type(error).__name__}", flush=True)
        return False

    # Наблюдение не задерживает SIP-ответ и может отказать независимо.
    threading.Thread(
        target=notify_adapter, args=(message, service_mode, offered_port), daemon=True
    ).start()
    return True


def reject(message, peer, tag, status, reason, extra=()):
    send_local_response(message, peer, status, reason, to_tag=tag, extra=extra)


def accept_agent_invite(message, peer, call_id, service_mode, tag) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
    if call is not None:
        if call["final"] and header(message, "CSeq") != header(call["invite"], "CSeq"):
            answer_reinvite(message, peer, call)
        elif call.get("last"):
            # Повтор INVITE: повторить последний ответ, не создавая второй звонок.
            runtime.sock.sendto(call["last"].encode(), peer)
        return

    send_local_response(message, peer, 100, "Trying")
    unknown = unsupported_required(message)
    if unknown:
        reject(
            message,
            peer,
            tag,
            420,
            "Bad Extension",
            ("Unsupported: " + ", ".join(sorted(unknown)),),
        )
        return

    media_endpoint = offered_media_endpoint(message)
    if media_endpoint is None or not accepts_pcmu(message):
        reject(message, peer, tag, 488, "Not Acceptable Here")
        return

    # P-CSCF обязан заякорить offer до iFC. Иначе SIP-абонент мог бы заставить
    # Voice Agent отправлять RTP на произвольный адрес (media SSRF/amplification).
    if not media_is_anchored(*media_endpoint):
        print(f"AS rejected unanchored media call_id={call_id}", flush=True)
        reject(message, peer, tag, 488, "Media Must Be Anchored")
        return

    offer = sdp_body(message)
    reliable = "100rel" in required(message) or (
        "100rel" in supported(message) and uses_preconditions(offer)
    )
    call = {
        "tag": tag,
        "service_mode": service_mode,
        "invite": message,
        "peer": peer,
        "endpoint": media_endpoint,
        "rtpengine_port": media_endpoint[1],
        "ready": offerer_ready(offer),
        "reliable": reliable,
        "prack": threading.Event(),
        "final": False,
        "last": "",
    }
    with runtime.calls_lock:
        runtime.agent_calls[call_id] = call
    if not reliable:
        finalize(call_id)
        return

    # Надёжный 183 несёт SDP-ответ; 200 OK после этого идёт без тела.
    options = ["100rel"] + (["precondition"] if uses_preconditions(offer) else [])
    extra = (
        f"Require: {', '.join(options)}",
        "RSeq: 1",
        ALLOW,
        f"Supported: {', '.join(SUPPORTED)}",
    )
    service_user = runtime.service_users[service_mode]
    call["last"] = send_local_response(
        message,
        peer,
        183,
        "Session Progress",
        body=voice_agent_sdp(offer),
        to_tag=tag,
        contact_user=service_user,
        extra=extra,
    )
    threading.Thread(target=retransmit_reliable, args=(call_id,), daemon=True).start()
    print(
        f"AS sent reliable 183 call_id={call_id} preconditions={uses_preconditions(offer)}",
        flush=True,
    )


def answer_reinvite(message, peer, call) -> None:
    """re-INVITE в установленном диалоге (удержание, смена кодека RTPengine)."""
    endpoint = offered_media_endpoint(message)
    if endpoint and media_is_anchored(*endpoint):
        call["endpoint"] = endpoint
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=voice_agent_sdp(sdp_body(message)),
        to_tag=call["tag"],
        contact_user=runtime.service_users[call["service_mode"]],
        extra=(ALLOW,),
    )


def retransmit_reliable(call_id: str) -> None:
    """RFC 3262: повторять 183 с удвоением T1, без PRACK за 64*T1 отклонить INVITE."""
    call = runtime.agent_calls.get(call_id)
    interval, deadline = runtime.sip_t1, time.monotonic() + 64 * runtime.sip_t1
    while call is not None and not call["prack"].wait(
        max(0.0, min(interval, deadline - time.monotonic()))
    ):
        if time.monotonic() >= deadline:
            with runtime.calls_lock:
                if runtime.agent_calls.pop(call_id, None) is not None:
                    reject(call["invite"], call["peer"], call["tag"], 504, "No PRACK Received")
            print(f"AS reliable 183 not acknowledged call_id={call_id}", flush=True)
            return
        runtime.sock.sendto(call["last"].encode(), call["peer"])
        interval = min(interval * 2, 4.0)


def handle_prack(message, peer, call_id) -> None:
    call = runtime.agent_calls.get(call_id)
    if call is None:
        send_local_response(message, peer, 481, "Call/Transaction Does Not Exist")
        return
    rack = header(message, "RAck").split()
    if not rack or rack[0] != "1":
        send_local_response(message, peer, 481, "RAck Does Not Match")
        return
    call["prack"].set()
    send_local_response(message, peer, 200, "OK", to_tag=call["tag"])

    if call["ready"]:
        finalize(call_id)
        return
    # Без N5/Rx телефон может не получить выделенный QoS-поток и не прислать
    # UPDATE. Ограниченное ожидание, затем ответ: вызов важнее политики QoS.
    timer = threading.Timer(runtime.precondition_timeout, finalize, args=(call_id, True))
    timer.daemon = True
    timer.start()


def handle_update(message, peer, call_id) -> None:
    call = runtime.agent_calls.get(call_id)
    if call is None:
        send_local_response(message, peer, 481, "Call/Transaction Does Not Exist")
        return
    service_user = runtime.service_users[call["service_mode"]]
    offer = sdp_body(message)
    if not offer.strip():
        send_local_response(message, peer, 200, "OK", to_tag=call["tag"], contact_user=service_user)
        return

    endpoint = offered_media_endpoint(message)
    if endpoint and media_is_anchored(*endpoint):
        call["endpoint"] = endpoint
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=voice_agent_sdp(offer),
        to_tag=call["tag"],
        contact_user=service_user,
        extra=(ALLOW,),
    )
    if offerer_ready(offer):
        call["ready"] = True
        if not call["reliable"] or call["prack"].is_set():
            finalize(call_id)


def finalize(call_id: str, timed_out: bool = False) -> None:
    """Единственный финальный ответ на INVITE; Voice Agent стартует здесь."""
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
        if call is None or call["final"]:
            return
        call["final"] = True
    if timed_out:
        print(f"AS precondition wait expired, answering call_id={call_id}", flush=True)

    message, peer, tag = call["invite"], call["peer"], call["tag"]
    if not start_agent_call(message, call_id, *call["endpoint"], call["service_mode"]):
        with runtime.calls_lock:
            runtime.agent_calls.pop(call_id, None)
        reject(message, peer, tag, 503, "Voice Agent Unavailable")
        return
    call["rtpengine_port"] = call["endpoint"][1]
    body = "" if call["reliable"] else voice_agent_sdp(sdp_body(message))
    call["last"] = send_local_response(
        message,
        peer,
        200,
        "OK",
        body=body,
        to_tag=tag,
        contact_user=runtime.service_users[call["service_mode"]],
        extra=(ALLOW, f"Supported: {', '.join(SUPPORTED)}"),
    )
    print(
        f"AS terminated INVITE for voice agent call_id={call_id} service={call['service_mode']}",
        flush=True,
    )


def end_agent_call(message, peer, call_id, method, fallback_tag) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.pop(call_id, {})
    send_local_response(message, peer, 200, "OK", to_tag=call.get("tag", fallback_tag))
    if call:
        call["prack"].set()  # Остановить повтор 183, если он ещё идёт.

    if method == "CANCEL" and call and not call["final"]:
        # Ранний диалог: финальный ответ на INVITE ещё не отправлен (RFC 3261 9.2).
        reject(call["invite"], call["peer"], call["tag"], 487, "Request Terminated")
        print(f"AS cancelled early voice agent call_id={call_id}", flush=True)
        return

    # Очистка вспомогательных сервисов не задерживает SIP 200 OK.
    threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
    threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)
