"""numbers AS: 1003–1006 завершаются на Voice Agent, остальные вызовы — прокси с observe.

Штатный IMS-клиент телефона предлагает 100rel и QoS preconditions (TS 24.229).
Тогда AS отвечает надёжным 183 с SDP-ответом, ждёт PRACK, затем UPDATE о
готовности QoS телефона и только после этого шлёт 200 OK. Клиент без этих
расширений получает прежний немедленный 200 OK с SDP.
"""

import re
import threading

from .. import runtime
from ..core import dialogs, mrf, uas
from ..core.mrf import media_is_anchored
from ..core.preconditions import (
    offerer_ready,
    required,
    sdp_body,
    supported,
    unsupported_required,
    uses_preconditions,
)
from ..core.proxy import forward
from ..core.sdp import accepts_pcmu_media, offered_media_endpoint
from ..core.sip import header, local_tag, message_call_id, request_method
from ..core.transport import send, send_local_response

HOST = "as"


def accept_agent_invite(message, peer, call_id, service_mode, tag) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
    if call is not None:
        if call["state"] == "final" and header(message, "CSeq") != header(call["invite"], "CSeq"):
            answer_reinvite(message, peer, call_id, call)
        elif call["last"]:
            send(call["last"], peer)  # повтор INVITE: последний ответ, без второго звонка
        return
    send_local_response(message, peer, 100, "Trying")
    unknown = unsupported_required(message)
    if unknown:
        extra = ("Unsupported: " + ", ".join(sorted(unknown)),)
        send_local_response(message, peer, 420, "Bad Extension", to_tag=tag, extra=extra)
        return
    media_endpoint = offered_media_endpoint(message)
    if media_endpoint is None or not accepts_pcmu_media(message):
        send_local_response(message, peer, 488, "Not Acceptable Here", to_tag=tag)
        return
    # P-CSCF обязан заякорить offer до iFC. Иначе SIP-абонент мог бы заставить
    # Voice Agent отправлять RTP на произвольный адрес (media SSRF/amplification).
    if not media_is_anchored(*media_endpoint):
        print(f"AS rejected unanchored media call_id={call_id}", flush=True)
        send_local_response(message, peer, 488, "Media Must Be Anchored", to_tag=tag)
        return
    # Preconditions ведутся, только если UAC объявил расширение (RFC 3312 11):
    # иначе Require: precondition в 183 вызвал бы у него 420.
    offer = sdp_body(message)
    options = supported(message) | required(message)
    qos = uses_preconditions(offer) and "precondition" in options
    reliable = "100rel" in required(message) or ("100rel" in options and qos)
    ready = offerer_ready(offer) if qos else True
    call = uas.new_call(
        message, peer, tag, service_mode, media_endpoint, qos=qos, reliable=reliable, ready=ready
    )
    with runtime.calls_lock:
        runtime.agent_calls[call_id] = call
    if not reliable:
        finalize(call_id)
        return
    uas.send_reliable_183(call_id, call, offer)
    print(f"AS sent reliable 183 call_id={call_id} preconditions={qos}", flush=True)


def finalize(call_id: str, timed_out: bool = False) -> None:
    """Единственный финальный ответ на INVITE; Voice Agent стартует здесь."""
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
        if call is None or call["state"] != "early":
            return
        call["state"] = "answering"
    if timed_out:
        print(f"AS precondition wait expired, answering call_id={call_id}", flush=True)
    message, service_mode = call["invite"], call["service_mode"]
    started = mrf.bind_leg(message, call_id, *call["endpoint"], service_mode)
    # CANCEL/BYE мог прийти, пока Voice Agent запускался: вызов уже снят с учёта.
    with runtime.calls_lock:
        cancelled = runtime.agent_calls.get(call_id) is not call
        if cancelled:
            runtime.agent_calls[call_id] = call  # до ACK на 487
    if cancelled:
        if started:
            mrf.release(call_id)
        uas.send_final(call_id, call, 487, "Request Terminated")
        return
    if not started:
        uas.send_final(call_id, call, 503, "Voice Agent Unavailable")
        return
    body = "" if call["reliable"] else uas.answer_sdp(call, sdp_body(message))
    uas.send_final(call_id, call, 200, "OK", body, (uas.ALLOW, uas.SUPPORTED_HEADER))
    print(
        f"AS terminated INVITE for voice agent call_id={call_id} service={service_mode}",
        flush=True,
    )


def move_media(call_id: str, call: dict, message: str) -> None:
    """Новый заякоренный адрес RTP; после ответа он передаётся Voice Agent."""
    endpoint = offered_media_endpoint(message)
    if not endpoint or not media_is_anchored(*endpoint) or endpoint == call["endpoint"]:
        return
    call["endpoint"] = endpoint
    if call["state"] != "final":
        return

    def renotify():
        try:
            mrf.notify_voice(call_id, *endpoint, call["service_mode"])
        except Exception as error:
            print(f"AS media move failed call_id={call_id} type={type(error).__name__}", flush=True)

    threading.Thread(target=renotify, daemon=True).start()


def answer_reinvite(message, peer, call_id, call) -> None:
    """re-INVITE в установленном диалоге (удержание, смена порта RTPengine)."""
    move_media(call_id, call, message)
    body = uas.answer_sdp(call, sdp_body(message))
    uas.reply(call, message, peer, 200, "OK", body, (uas.ALLOW,))


def handle_prack(message, peer, call_id) -> None:
    call = runtime.agent_calls.get(call_id)
    if call is None:
        send_local_response(message, peer, 481, "Call/Transaction Does Not Exist")
        return
    if not uas.rack_matches(call, message):
        send_local_response(message, peer, 481, "RAck Does Not Match")
        return
    call["pracked"] = True
    send_local_response(message, peer, 200, "OK", to_tag=call["tag"])
    if call["ready"]:
        finalize(call_id)
        return
    # Без N5/Rx телефон может не получить выделенный QoS-поток и не прислать
    # UPDATE. Ограниченное ожидание, затем ответ: вызов важнее политики QoS.
    uas.later(runtime.precondition_timeout, finalize, call_id, True)


def handle_update(message, peer, call_id) -> None:
    call = runtime.agent_calls.get(call_id)
    if call is None:
        send_local_response(message, peer, 481, "Call/Transaction Does Not Exist")
        return
    offer = sdp_body(message)
    if not offer.strip():
        uas.reply(call, message, peer, 200, "OK")  # session refresh без SDP
        return
    move_media(call_id, call, message)
    uas.reply(call, message, peer, 200, "OK", uas.answer_sdp(call, offer), (uas.ALLOW,))
    if call["qos"] and offerer_ready(offer):
        call["ready"] = True
        if not call["reliable"] or call["pracked"]:
            finalize(call_id)


def end_agent_call(message, peer, call_id, method, fallback_tag) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.pop(call_id, None)
        state = call["state"] if call else None
        if state == "early":
            call["state"] = "answering"
            runtime.agent_calls[call_id] = call  # до ACK на 487
    send_local_response(message, peer, 200, "OK", to_tag=call["tag"] if call else fallback_tag)
    if state == "early":
        # Ранний диалог: финального ответа на INVITE ещё нет; так же для BYE
        # до 200 OK (RFC 3261 9.2, 15.1.2). Повтор 183 прекращается.
        call["pracked"] = True
        uas.send_final(call_id, call, 487, "Request Terminated")
        print(f"AS terminated early voice agent call_id={call_id} method={method}", flush=True)
        return
    if state == "answering":
        # finalize ещё запускает Voice Agent: он сам ответит 487 и остановит его.
        print(f"AS {method} while answering call_id={call_id}", flush=True)
        return
    if call:
        call["acked"] = True  # прекратить повтор 200 OK: диалог завершён
    # Очистка вспомогательных сервисов не задерживает SIP 200 OK.
    mrf.release(call_id)
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)


def terminate_for_agent(message, peer, service_mode) -> None:
    """Обработать локально один запрос диалога голосового сервиса."""
    method = request_method(message)
    call_id = message_call_id(message)
    tag = local_tag(call_id)
    if method == "INVITE":
        accept_agent_invite(message, peer, call_id, service_mode, tag)
    elif method == "ACK":
        uas.handle_ack(call_id)
    elif method in {"BYE", "CANCEL"}:
        end_agent_call(message, peer, call_id, method, tag)
    elif method == "PRACK":
        handle_prack(message, peer, call_id)
    elif method == "UPDATE":
        handle_update(message, peer, call_id)
    elif method in {"OPTIONS", "INFO"}:
        send_local_response(message, peer, 200, "OK", to_tag=tag)
    else:
        # Каждый запрос получает ответ: молчание вызвало бы повторы и таймауты.
        send_local_response(message, peer, 501, "Not Implemented", to_tag=tag)


def request_target(request_line: str) -> str | None:
    """Номер или имя услуги из sip:/sips:/tel: Request-URI без параметров.

    Штатная звонилка набирает sip:1003;phone-context=...;user=phone, а S-CSCF
    переписывает его в tel:1003;phone-context=...
    """
    target_match = re.search(r"^[A-Z]+\s+(?:sips?|tel):([^@;> ]+)", request_line)
    if target_match is None:
        return None
    return re.sub(r"[-.() ]", "", target_match.group(1))


def service_mode_for_request(request_line: str, call_id: str) -> str | None:
    """Сначала продолжить известный диалог, затем проверить номер услуги."""
    with runtime.calls_lock:
        active_mode = runtime.agent_calls.get(call_id, {}).get("service_mode")
    if active_mode:
        return active_mode
    return runtime.service_targets.get(request_target(request_line) or "")


def observe_proxied_dialog(message: str, request_line: str, call_id: str) -> None:
    """Сообщить Media Adapter о начале/завершении обычного звонка."""
    if request_line.startswith("INVITE "):
        print(f"AS observed INVITE call_id={call_id}", flush=True)
        mrf.stream_to_recognition(message, "observe")
    elif request_line.startswith(("BYE ", "CANCEL ")):
        mrf.stop_recognition(call_id)


def handle(message: str, peer: tuple[str, int]) -> None:
    """Номер услуги — завершить на Voice Agent, иначе наблюдать и вернуть в S-CSCF."""
    request_line = message.split("\r\n", 1)[0]
    call_id = message_call_id(message)
    service_mode = service_mode_for_request(request_line, call_id)
    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return
    # Ногу B (B2BUA) и звонок под записью уже распознаёт услуга: не наблюдать дважды.
    if not (dialogs.is_own(call_id) or dialogs.is_marked_record(call_id)):
        observe_proxied_dialog(message, request_line, call_id)
    forward(message, peer)
