"""Вход SIP AS: запрос — логическому AS по первому Route, ответ — по своему Via."""

from .. import runtime
from ..services import numbers
from .proxy import relay_response
from .sip import top_route_host

SERVICES = (numbers,)


def service_for(message: str):
    host = top_route_host(message)
    return next((s for s in SERVICES if host == f"{s.HOST}.{runtime.ims_domain}"), None)


def route_request(message: str, peer: tuple[str, int]) -> None:
    (service_for(message) or numbers).handle(message, peer)


def route_response(message: str) -> None:
    relay_response(message)
