"""translate AS: B2BUA с переводом. Нога A — звонящий <-> MRF, нога B — MRF <-> вызываемый."""

from .. import runtime
from ..core import b2bua, mrf, proxy
from ..core.sip import request_method, tag_of, value_of
from ..core.subscribers import language_for, served_user, target_user

HOST = "translate.as"


def strip_star(user: str) -> str:
    """«*номер» разово включает перевод; дальше звонок идёт на номер без префикса."""
    return user[1:] if user.startswith("*") else user


def caller_language(message: str) -> str:
    return language_for(served_user(message), runtime.languages, runtime.default_language)


def on_invite(message: str, peer: tuple[str, int]) -> None:
    callee = strip_star(target_user(message))
    callee_language = language_for(callee, runtime.languages, runtime.default_language)
    languages = (caller_language(message), callee_language)
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
    return True


def on_bye(call: b2bua.Call) -> None:
    if not call.answered:
        return
    for leg in (call.a, call.b):
        mrf.release(leg.call_id)
    mrf.unpair(call.a.call_id)
    print(f"AS translate ended call_id={call.a.call_id}", flush=True)


def handle(message: str, peer: tuple[str, int]) -> None:
    if request_method(message) == "INVITE" and not tag_of(value_of(message, "To")):
        on_invite(message, peer)
        return
    proxy.forward(message, peer)
