"""Прокси-путь логического AS: свой Via, снятие своего Route, возврат ответа по Via."""

import re

from .. import runtime
from .sip import transaction_branch
from .transport import send

OWN_ROUTE = re.compile(r"(?im)^(Route\s*:\s*)<sip:as\.[^>]+>\s*,\s*")
OWN_VIA = re.compile(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-([^;\s]+)\r\n")


def build_forwarded_request(message: str, branch: str) -> str:
    request_line, remaining_headers = message.split("\r\n", 1)
    own_via = (
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    )
    # Поглощается только Route текущего AS. Следующий ISC Route возвращает
    # запрос в S-CSCF, где продолжается обычная маршрутизация.
    remaining_headers = OWN_ROUTE.sub(r"\1", remaining_headers, count=1)
    return request_line + "\r\n" + own_via + remaining_headers


def forward(message: str, peer: tuple[str, int]) -> None:
    """Вернуть запрос в S-CSCF; ответ найдёт отправителя по branch своего Via."""
    branch = transaction_branch(message)
    runtime.transactions[branch] = peer
    send(build_forwarded_request(message, branch), runtime.scscf)


def relay_response(message: str) -> None:
    """Удалить собственный Via и вернуть ответ исходному SIP peer."""
    via_match = OWN_VIA.search(message)
    if via_match is None:
        print(f"AS dropped response without own Via: {message.splitlines()[0]}", flush=True)
        return
    branch = via_match.group(1)
    destination_peer = runtime.transactions.get(branch)
    if destination_peer is None:
        print(f"AS dropped response for unknown transaction {branch}", flush=True)
        return
    print(
        f"AS relayed response {message.splitlines()[0]} "
        f"to {destination_peer[0]}:{destination_peer[1]}",
        flush=True,
    )
    send(OWN_VIA.sub("", message, count=1), destination_peer)
