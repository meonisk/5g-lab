"""translate AS: B2BUA с переводом или прозрачный прокси, если переводить нечего или нечем.

Нога A — звонящий <-> MRF, нога B — MRF <-> вызываемый. Без перевода звонок идёт
дальше по цепочке iFC как обычный: звонящий не получает 503.
"""

import re
import threading

from .. import runtime
from ..core import b2bua, dialogs, mrf, proxy
from ..core.mrf import media_is_anchored
from ..core.sdp import accepts_pcmu, offered_media_endpoint
from ..core.sip import local_tag, message_call_id, request_method, tag_of, value_of
from ..core.subscribers import language_for, served_user, target_user

HOST = "translate.as"
LEGS_PER_CALL = 2  # нога A и нога B занимают два места Voice Agent
STAR = re.compile(r"^(\S+ (?:sips?|tel):)\*")


def strip_star(user: str) -> str:
    """«*номер» разово включает перевод; дальше звонок идёт на номер без префикса."""
    return user[1:] if user.startswith("*") else user


def caller_language(message: str) -> str:
    return language_for(served_user(message), runtime.languages, runtime.default_language)


def bypass_reason(message: str) -> str | None:
    """Почему звонок идёт без перевода; None — переводить."""
    if dialogs.is_own(message_call_id(message)):
        return "own_leg"
    callee = strip_star(target_user(message))
    if callee in runtime.service_targets:
        return "service_number"
    if callee not in runtime.languages:
        return "unknown_callee"
    if caller_language(message) == runtime.languages[callee]:
        return "same_language"
    endpoint = offered_media_endpoint(message)
    if endpoint is None or not accepts_pcmu(message) or not media_is_anchored(*endpoint):
        return "media"
    if mrf.free_slots() < LEGS_PER_CALL:
        return "no_mrf"
    return None


def bypass(message: str, peer: tuple[str, int], reason: str) -> None:
    print(f"AS translate bypass call_id={message_call_id(message)} reason={reason}", flush=True)
    proxy.forward(STAR.sub(r"\1", message, count=1), peer)


def on_invite(message: str, peer: tuple[str, int]) -> None:
    reason = bypass_reason(message)
    if reason is not None:
        bypass(message, peer, reason)
        return
    callee = strip_star(target_user(message))
    languages = (caller_language(message), runtime.languages[callee])
    request_uri = f"sip:{callee}@{runtime.ims_domain}"
    b2bua.start(message, peer, request_uri, languages, on_answer, on_bye)


def on_answer(call: b2bua.Call, response: str) -> bool:
    """Обе ноги к Voice Agent в режимах своих языков, затем пара в AI Worker."""
    (lang_a, lang_b), a, b = call.languages, call.a, call.b
    if a.media is None:
        return False
    if not mrf.bind_leg(call.a_invite, a.call_id, *a.media, mrf.INTERPRETER_MODES[lang_a]):
        return False
    if not mrf.bind_leg(response, b.call_id, *b.media, mrf.INTERPRETER_MODES[lang_b]):
        mrf.release(a.call_id)
        return False
    mrf.pair((a.call_id, lang_a), (b.call_id, lang_b))
    print(
        f"AS translate answered call_id={a.call_id} leg_b={b.call_id} languages={lang_a}-{lang_b}",
        flush=True,
    )
    # record AS (приоритет 20) пометил ногу B, когда она шла по цепочке iFC.
    if dialogs.is_marked_record(b.call_id):
        threading.Thread(target=start_pair_recording, args=(call,), daemon=True).start()
    return True


def start_pair_recording(call: b2bua.Call) -> None:
    """Уведомление каждой стороне голосом MRF, затем запись обеих ног в одну сессию AI."""
    legs = ((call.a.call_id, call.languages[0]), (call.b.call_id, call.languages[1]))
    for call_id, language in legs:
        text, voice = runtime.announcements[language]
        if not mrf.play(call_id, text, voice):
            print(f"AS record skipped call_id={call.a.call_id} reason=announcement", flush=True)
            return
    mrf.record_pair(call.a.call_id, [(call.a.call_id, "caller"), (call.b.call_id, "callee")])
    print(f"AS record started call_id={call.a.call_id} legs=2", flush=True)


def on_bye(call: b2bua.Call) -> None:
    if not call.answered:
        return
    for leg in (call.a, call.b):
        mrf.release(leg.call_id)
    mrf.unpair(call.a.call_id)
    print(f"AS translate ended call_id={call.a.call_id}", flush=True)


def handle(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    method = request_method(message)
    to_tag = tag_of(value_of(message, "To"))
    if b2bua.find(call_id) is not None:
        b2bua.handle_request(message, peer)
    elif method == "INVITE" and not to_tag:
        on_invite(message, peer)
    elif method == "ACK" and to_tag == local_tag(call_id):
        return  # ACK на наш не-2xx ответ ноге A: транзакция уже завершена
    else:
        proxy.forward(message, peer)
