"""Вход SIP AS: запрос — логическому AS, ответ — по своему Via."""

from ..services import numbers
from .proxy import relay_response


def route_request(message: str, peer: tuple[str, int]) -> None:
    numbers.handle(message, peer)


def route_response(message: str) -> None:
    relay_response(message)
