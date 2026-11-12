"""record AS: прокси с пометкой записи.

Без перевода звук звонка идёт из RTPengine в AI Worker (как observe) после
уведомления каждой стороне. Если звонок переводится, нога B проходит record AS
по цепочке iFC: он только помечает её, а translate пишет обе ноги MRF.
"""

import threading

from .. import runtime
from ..core import dialogs, mrf, proxy
from ..core.sip import message_call_id, request_method, status_code, tag_of, value_of
from ..core.subscribers import language_for, served_user, target_user

HOST = "record.as"


def parties(invite: str, response: str) -> list[tuple[str, str, str]]:
    """(SIP tag, текст, голос) уведомления для звонящего и вызываемого на их языках."""
    default = runtime.default_language
    caller = language_for(served_user(invite), runtime.languages, default)
    callee = language_for(target_user(invite), runtime.languages, default)
    return [
        (tag_of(value_of(invite, "From")), *runtime.announcements[caller]),
        (tag_of(value_of(response, "To")), *runtime.announcements[callee]),
    ]


def start_recording(invite: str, response: str) -> None:
    call_id = message_call_id(invite)
    # Без уведомления не записываем: сторона должна знать о записи.
    if not mrf.announce(call_id, parties(invite, response)):
        print(f"AS record skipped call_id={call_id} reason=announcement", flush=True)
        return
    mrf.stream_to_recognition(invite, "record")
    print(f"AS record started call_id={call_id}", flush=True)


def on_answer(response: str) -> None:
    invite = runtime.record_invites.pop(message_call_id(response), None)
    if invite is not None and 200 <= status_code(response) < 300:
        # Уведомление играет до нескольких секунд: SIP-цикл его не ждёт.
        threading.Thread(target=start_recording, args=(invite, response), daemon=True).start()


def on_invite(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    if target_user(message) in runtime.service_targets:
        proxy.forward(message, peer)  # 1003–1006 работают как раньше
        return
    dialogs.mark_record(call_id)
    if dialogs.is_own(call_id):
        proxy.forward(message, peer)
        print(f"AS record marked call_id={call_id} via=translate", flush=True)
        return
    runtime.record_invites[call_id] = message
    proxy.forward(message, peer, record_route=HOST, on_answer=on_answer)
    print(f"AS record marked call_id={call_id}", flush=True)


def on_bye(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    proxy.forward(message, peer)
    if dialogs.is_own(call_id):
        return  # ногу B освобождает B2BUA
    runtime.record_invites.pop(call_id, None)
    dialogs.forget(call_id)
    mrf.stop_recognition(call_id)
    print(f"AS record ended call_id={call_id}", flush=True)


def handle(message: str, peer: tuple[str, int]) -> None:
    method = request_method(message)
    if method == "INVITE" and not tag_of(value_of(message, "To")):
        on_invite(message, peer)
    elif method in {"BYE", "CANCEL"}:
        on_bye(message, peer)
    else:
        proxy.forward(message, peer)
