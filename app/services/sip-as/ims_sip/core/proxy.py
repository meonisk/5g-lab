"""Прокси-путь логического AS: свой Via, снятие своего Route, Record-Route, хук ответа."""

import re

from .. import runtime
from .sip import cseq_method, status_code, transaction_branch
from .transport import send

# Свой Route — первый, хост <метка>.as.<домен> или as.<домен>: в одной строке со
# следующим ISC Route через запятую либо отдельной строкой.
OWN_ROUTE = re.compile(r"(?im)^(Route\s*:\s*)<sip:(?:[a-z0-9-]+\.)?as\.[^>]+>\s*,\s*")
OWN_ROUTE_LINE = re.compile(r"(?im)^Route\s*:\s*<sip:(?:[a-z0-9-]+\.)?as\.[^>]+>\s*\r\n")
OWN_VIA = re.compile(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-([^;\s]+)\r\n")


def build_forwarded_request(message: str, branch: str, record_route: str = "") -> str:
    request_line, remaining_headers = message.split("\r\n", 1)
    own_via = (
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    )
    if record_route:
        # Логический AS остаётся в пути диалога: BYE придёт к нему и закроет услугу.
        host = f"{record_route}.{runtime.ims_domain}:{runtime.bind_port}"
        own_via += f"Record-Route: <sip:{host};transport=udp;lr>\r\n"
    # Поглощается только Route текущего AS. Следующий ISC Route возвращает
    # запрос в S-CSCF, где продолжается цепочка iFC.
    stripped = OWN_ROUTE.sub(r"\1", remaining_headers, count=1)
    if stripped == remaining_headers:
        stripped = OWN_ROUTE_LINE.sub("", remaining_headers, count=1)
    return request_line + "\r\n" + own_via + stripped


def forward(message: str, peer: tuple[str, int], *, record_route: str = "", on_answer=None):
    """Вернуть запрос в S-CSCF; on_answer(response) — на финальный ответ на INVITE."""
    branch = transaction_branch(message)
    runtime.transactions[branch] = peer
    if on_answer is not None:
        runtime.answer_hooks[branch] = on_answer
    send(build_forwarded_request(message, branch, record_route), runtime.scscf)


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
    response = OWN_VIA.sub("", message, count=1)
    send(response, destination_peer)
    if status_code(message) >= 200 and cseq_method(message) == "INVITE":
        hook = runtime.answer_hooks.pop(branch, None)
        if hook is not None:
            hook(response)
