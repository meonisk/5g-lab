"""UAS-диалог AI-услуги: 100rel, QoS preconditions, UPDATE и завершение.

Штатный IMS-клиент телефона обычно предлагает preconditions и 100rel
(TS 24.229). Тогда AS отвечает надёжным 183 с SDP-ответом, ждёт PRACK,
затем UPDATE о готовности QoS телефона и только после этого шлёт 200 OK.
Клиент без этих расширений получает прежний немедленный 200 OK с SDP.

Состояние вызова: early (до финального ответа), answering (запускается
Voice Agent, финальный ответ ещё не отправлен) и final. Финальные ответы
на INVITE повторяются до ACK (RFC 3261 13.3.1.4, 17.2.1).
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
# RFC 3261 T2: верхняя граница интервала повторов ответа на INVITE.
SIP_T2 = 4.0


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


def voice_agent_sdp(offer_sdp: str = "", version: int = 1) -> str:
    """Ответ для единственного кодека PCMU/8000 и, при необходимости, QoS."""
    lines = [
        "v=0",
        f"o=voice-agent 1 {version} IN IP4 {runtime.voice_ip}",
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


def answer_sdp(call, offer: str) -> str:
    """SDP-ответ диалога: версия o= растёт при каждом изменении (RFC 3264 8)."""
    offer = offer if call["qos"] else ""
    body = voice_agent_sdp(offer, call["sdp_version"])
    if call["last_answer"] and body != call["last_answer"]:
        call["sdp_version"] += 1
        body = voice_agent_sdp(offer, call["sdp_version"])
    call["last_answer"] = body
    return body


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


def stop_agent_services(call_id: str) -> None:
    # Очистка вспомогательных сервисов не задерживает SIP-ответ.
    threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
    threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()


def reject(message, peer, tag, status, reason, extra=()):
    send_local_response(message, peer, status, reason, to_tag=tag, extra=extra)


def accept_agent_invite(message, peer, call_id, service_mode, tag) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
    if call is not None:
        if call["state"] == "final" and header(message, "CSeq") != header(call["invite"], "CSeq"):
            answer_reinvite(message, peer, call_id, call)
        elif call.get("last"):
            # Повтор INVITE: повторить последний ответ, не создавая второй звонок.
            runtime.sock.sendto(call["last"].encode(), peer)
        return

    send_local_response(message, peer, 100, "Trying")
    unknown = unsupported_required(message)
    if unknown:
        extra = ("Unsupported: " + ", ".join(sorted(unknown)),)
        reject(message, peer, tag, 420, "Bad Extension", extra)
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

    # Preconditions ведутся, только если UAC объявил расширение (RFC 3312 11):
    # иначе Require: precondition в 183 вызвал бы у него 420.
    offer = sdp_body(message)
    options = supported(message) | required(message)
    qos = uses_preconditions(offer) and "precondition" in options
    reliable = "100rel" in required(message) or ("100rel" in options and qos)
    call = {
        "tag": tag,
        "service_mode": service_mode,
        "invite": message,
        "peer": peer,
        "endpoint": media_endpoint,
        "rtpengine_port": media_endpoint[1],
        "ready": offerer_ready(offer) if qos else True,
        "qos": qos,
        "reliable": reliable,
        "prack": threading.Event(),
        "ack": threading.Event(),
        "state": "early",
        "status": 0,
        "last": "",
        "sdp_version": 1,
        "last_answer": "",
    }
    with runtime.calls_lock:
        runtime.agent_calls[call_id] = call
    if not reliable:
        finalize(call_id)
        return

    # Надёжный 183 несёт SDP-ответ; 200 OK после этого идёт без тела.
    extra = (
        f"Require: {', '.join(['100rel'] + (['precondition'] if qos else []))}",
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
        body=answer_sdp(call, offer),
        to_tag=tag,
        contact_user=service_user,
        extra=extra,
    )
    threading.Thread(target=retransmit_reliable, args=(call_id, call), daemon=True).start()
    print(f"AS sent reliable 183 call_id={call_id} preconditions={qos}", flush=True)


def move_media(call_id, call, message) -> None:
    """Новый заякоренный адрес RTP; после ответа он передаётся Voice Agent."""
    endpoint = offered_media_endpoint(message)
    if not endpoint or not media_is_anchored(*endpoint) or endpoint == call["endpoint"]:
        return
    call["endpoint"] = endpoint
    if call["state"] != "final":
        return

    call["rtpengine_port"] = endpoint[1]

    def renotify():
        try:
            notify_voice(call_id, *endpoint, call["service_mode"])
        except Exception as error:
            print(f"AS media move failed call_id={call_id} type={type(error).__name__}", flush=True)

    threading.Thread(target=renotify, daemon=True).start()


def answer_reinvite(message, peer, call_id, call) -> None:
    """re-INVITE в установленном диалоге (удержание, смена кодека RTPengine)."""
    move_media(call_id, call, message)
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=answer_sdp(call, sdp_body(message)),
        to_tag=call["tag"],
        contact_user=runtime.service_users[call["service_mode"]],
        extra=(ALLOW,),
    )


def retransmit(call, event_name: str, deadline: float) -> bool:
    """Повторять последний ответ с удвоением T1 до T2; True, если событие пришло."""
    interval = runtime.sip_t1
    while not call[event_name].wait(max(0.0, min(interval, deadline - time.monotonic()))):
        if time.monotonic() >= deadline:
            return False
        runtime.sock.sendto(call["last"].encode(), call["peer"])
        interval = min(interval * 2, SIP_T2)
    return True


def retransmit_reliable(call_id: str, call) -> None:
    """RFC 3262: без PRACK за 64*T1 отклонить INVITE ответом 504."""
    if retransmit(call, "prack", time.monotonic() + 64 * runtime.sip_t1):
        return
    with runtime.calls_lock:
        expired = runtime.agent_calls.get(call_id) is call and call["state"] == "early"
        if expired:
            call["state"] = "answering"
    if expired:
        print(f"AS reliable 183 not acknowledged call_id={call_id}", flush=True)
        send_final(call_id, call, 504, "No PRACK Received")


def send_final(call_id, call, status, reason, body="", extra=()) -> None:
    """Финальный ответ на INVITE; повтор до ACK, затем очистка неуспешного вызова."""
    call["status"] = status
    call["last"] = send_local_response(
        call["invite"],
        call["peer"],
        status,
        reason,
        body=body,
        to_tag=call["tag"],
        contact_user=runtime.service_users[call["service_mode"]],
        extra=extra,
    )
    call["state"] = "final"
    threading.Thread(target=await_ack, args=(call_id, call), daemon=True).start()


def await_ack(call_id: str, call) -> None:
    acked = retransmit(call, "ack", time.monotonic() + 64 * runtime.sip_t1)
    if acked and call["status"] < 300:
        return

    with runtime.calls_lock:
        if runtime.agent_calls.get(call_id) is call:
            runtime.agent_calls.pop(call_id)
    if call["status"] < 300:
        # RFC 3261 13.3.1.4: 2xx без ACK завершает сеанс.
        print(f"AS 200 OK not acknowledged call_id={call_id}", flush=True)
        stop_agent_services(call_id)


def handle_ack(call_id: str) -> None:
    call = runtime.agent_calls.get(call_id)
    if call is not None:
        call["ack"].set()
    print(f"AS received ACK for voice agent call_id={call_id}", flush=True)


def handle_prack(message, peer, call_id) -> None:
    call = runtime.agent_calls.get(call_id)
    if call is None:
        send_local_response(message, peer, 481, "Call/Transaction Does Not Exist")
        return
    # RAck = RSeq надёжного 183, номер CSeq и метод INVITE (RFC 3262 7.2).
    invite_cseq = header(call["invite"], "CSeq").split()[:1]
    if header(message, "RAck").split() != ["1", *invite_cseq, "INVITE"]:
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

    move_media(call_id, call, message)
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=answer_sdp(call, offer),
        to_tag=call["tag"],
        contact_user=service_user,
        extra=(ALLOW,),
    )
    if call["qos"] and offerer_ready(offer):
        call["ready"] = True
        if not call["reliable"] or call["prack"].is_set():
            finalize(call_id)


def finalize(call_id: str, timed_out: bool = False) -> None:
    """Единственный финальный ответ на INVITE; Voice Agent стартует здесь."""
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
        if call is None or call["state"] != "early":
            return
        call["state"] = "answering"
    if timed_out:
        print(f"AS precondition wait expired, answering call_id={call_id}", flush=True)

    message = call["invite"]
    started = start_agent_call(message, call_id, *call["endpoint"], call["service_mode"])

    # CANCEL/BYE мог прийти, пока Voice Agent запускался: вызов уже снят с учёта.
    with runtime.calls_lock:
        cancelled = runtime.agent_calls.get(call_id) is not call
        if cancelled:
            runtime.agent_calls[call_id] = call  # До ACK на 487.
    if cancelled:
        if started:
            stop_agent_services(call_id)
        send_final(call_id, call, 487, "Request Terminated")
        return
    if not started:
        send_final(call_id, call, 503, "Voice Agent Unavailable")
        return

    call["rtpengine_port"] = call["endpoint"][1]
    body = "" if call["reliable"] else answer_sdp(call, sdp_body(message))
    send_final(call_id, call, 200, "OK", body, (ALLOW, f"Supported: {', '.join(SUPPORTED)}"))
    print(
        f"AS terminated INVITE for voice agent call_id={call_id} service={call['service_mode']}",
        flush=True,
    )


def end_agent_call(message, peer, call_id, method, fallback_tag) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.pop(call_id, None)
        state = call["state"] if call else None
        if state == "early":
            call["state"] = "answering"
            runtime.agent_calls[call_id] = call  # До ACK на 487.
    send_local_response(message, peer, 200, "OK", to_tag=call["tag"] if call else fallback_tag)
    if call:
        call["prack"].set()  # Остановить повтор 183, если он ещё идёт.

    if state == "early":
        # Ранний диалог: финальный ответ на INVITE ещё не отправлен; так же
        # для BYE до 200 OK (RFC 3261 9.2, 15.1.2).
        send_final(call_id, call, 487, "Request Terminated")
        print(f"AS terminated early voice agent call_id={call_id} method={method}", flush=True)
        return
    if state == "answering":
        # finalize ещё запускает Voice Agent: он сам ответит 487 и остановит его.
        print(f"AS {method} while answering call_id={call_id}", flush=True)
        return

    if call:
        call["ack"].set()  # Прекратить повтор 200 OK: диалог завершён.
    stop_agent_services(call_id)
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)
