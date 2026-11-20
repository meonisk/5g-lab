"""UAS-механика локально завершённого INVITE (numbers AS, звонок на Voice Agent).

Надёжный 183 с RSeq повторяется до PRACK (RFC 3262 3), финальный ответ на
INVITE — до ACK (RFC 3261 13.3.1.4, 17.2.1): интервал T1 удваивается до T2,
предел 64*T1. Таймеры — фоновые потоки: цикл приёма UDP ими не блокируется.

Состояние вызова: early (финального ответа ещё нет), answering (запускается
Voice Agent) и final. Вызов в runtime.agent_calls под runtime.calls_lock.
"""

import threading
import time

from .. import runtime
from . import mrf
from .preconditions import SUPPORTED
from .sip import header
from .transport import send, send_local_response

ALLOW = "Allow: INVITE, ACK, BYE, CANCEL, PRACK, UPDATE, OPTIONS"
SUPPORTED_HEADER = "Supported: " + ", ".join(SUPPORTED)
SIP_T2 = 4.0  # RFC 3261 T2: верхняя граница интервала повтора ответа на INVITE
RSEQ = 1  # единственный надёжный 1xx диалога
# Класс потока фиксируется при импорте: таймер всегда асинхронный, даже когда
# threading.Thread подменён (unit-тесты исполняют фоновые задачи синхронно).
TIMER_THREAD = threading.Thread


def later(delay: float, function, *args) -> None:
    def run():
        time.sleep(delay)
        function(*args)

    TIMER_THREAD(target=run, daemon=True).start()


def new_call(invite, peer, tag, service_mode, endpoint, *, qos, reliable, ready) -> dict:
    return {
        "tag": tag,
        "service_mode": service_mode,
        "invite": invite,
        "peer": peer,
        "endpoint": endpoint,
        "qos": qos,
        "reliable": reliable,
        "ready": ready,
        "pracked": False,
        "acked": False,
        "state": "early",
        "status": 0,
        "last": "",
        "sdp_version": 1,
        "last_answer": "",
    }


def current(call_id: str, call: dict) -> bool:
    with runtime.calls_lock:
        return runtime.agent_calls.get(call_id) is call


def reply(call, request, peer, status, reason, body="", extra=()) -> str:
    """Ответ в диалоге вызова: свой tag и Contact пользователя услуги."""
    return send_local_response(
        request,
        peer,
        status,
        reason,
        body=body,
        to_tag=call["tag"],
        contact_user=runtime.service_users[call["service_mode"]],
        extra=extra,
    )


def answer_sdp(call: dict, offer: str) -> str:
    """SDP-ответ диалога: версия o= растёт при каждом изменении (RFC 3264 8)."""
    offer = offer if call["qos"] else ""
    body = mrf.voice_agent_sdp(offer, call["sdp_version"])
    if call["last_answer"] and body != call["last_answer"]:
        call["sdp_version"] += 1
        body = mrf.voice_agent_sdp(offer, call["sdp_version"])
    call["last_answer"] = body
    return body


def repeat_until(call_id: str, call: dict, flag: str, on_expire) -> None:
    """Повторять call["last"], пока не выставлен call[flag]; через 64*T1 — on_expire()."""
    deadline = time.monotonic() + 64 * runtime.sip_t1

    def wait(interval: float) -> None:
        later(max(0.0, min(interval, deadline - time.monotonic())), tick, interval)

    def tick(interval: float) -> None:
        if call[flag] or not current(call_id, call):
            return
        if time.monotonic() >= deadline:
            on_expire()
            return
        send(call["last"], call["peer"])
        wait(min(interval * 2, SIP_T2))

    wait(runtime.sip_t1)


def send_reliable_183(call_id: str, call: dict, offer: str) -> None:
    """Надёжный 183 несёт SDP-ответ; 200 OK после него идёт без тела."""
    required = "100rel, precondition" if call["qos"] else "100rel"
    extra = (f"Require: {required}", f"RSeq: {RSEQ}", ALLOW, SUPPORTED_HEADER)
    body = answer_sdp(call, offer)
    invite = call["invite"]
    call["last"] = reply(call, invite, call["peer"], 183, "Session Progress", body, extra)
    repeat_until(call_id, call, "pracked", lambda: prack_expired(call_id, call))


def prack_expired(call_id: str, call: dict) -> None:
    """RFC 3262: без PRACK за 64*T1 отклонить INVITE ответом 504."""
    with runtime.calls_lock:
        expired = current(call_id, call) and call["state"] == "early"
        if expired:
            call["state"] = "answering"
    if expired:
        print(f"AS reliable 183 not acknowledged call_id={call_id}", flush=True)
        send_final(call_id, call, 504, "No PRACK Received")


def rack_matches(call: dict, prack: str) -> bool:
    """RAck = RSeq надёжного 183, номер CSeq и метод INVITE (RFC 3262 7.2)."""
    invite_cseq = header(call["invite"], "CSeq").split()[:1]
    return header(prack, "RAck").split() == [str(RSEQ), *invite_cseq, "INVITE"]


def send_final(call_id, call, status, reason, body="", extra=()) -> None:
    """Единственный финальный ответ на INVITE; повтор до ACK."""
    call["status"] = status
    call["last"] = reply(call, call["invite"], call["peer"], status, reason, body, extra)
    call["state"] = "final"
    repeat_until(call_id, call, "acked", lambda: ack_expired(call_id, call))


def ack_expired(call_id: str, call: dict) -> None:
    with runtime.calls_lock:
        if not current(call_id, call):
            return
        runtime.agent_calls.pop(call_id)
    if call["status"] < 300:
        # RFC 3261 13.3.1.4: 2xx без ACK завершает сеанс.
        print(f"AS 200 OK not acknowledged call_id={call_id}", flush=True)
        mrf.release(call_id)


def handle_ack(call_id: str) -> None:
    with runtime.calls_lock:
        call = runtime.agent_calls.get(call_id)
        if call is not None:
            call["acked"] = True
            if call["state"] == "final" and call["status"] >= 300:
                runtime.agent_calls.pop(call_id)  # ACK на отказ закрывает транзакцию
    print(f"AS received ACK for voice agent call_id={call_id}", flush=True)
