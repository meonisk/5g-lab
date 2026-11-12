"""Вход SIP AS: запрос — логическому AS по первому Route, ответ — B2BUA или по своему Via."""

from .. import runtime
from ..services import numbers, translate
from . import b2bua
from .proxy import relay_response
from .sip import message_call_id, top_route_host

SERVICES = (translate, numbers)


def service_for(message: str):
    host = top_route_host(message)
    return next((s for s in SERVICES if host == f"{s.HOST}.{runtime.ims_domain}"), None)


def route_request(message: str, peer: tuple[str, int]) -> None:
    service = service_for(message)
    # BYE/re-INVITE ноги B2BUA приходят на Contact SIP AS, без Route логического AS.
    if service is None and b2bua.find(message_call_id(message)) is not None:
        b2bua.handle_request(message, peer)
        return
    (service or numbers).handle(message, peer)


def route_response(message: str) -> None:
    if not b2bua.handle_response(message):
        relay_response(message)
