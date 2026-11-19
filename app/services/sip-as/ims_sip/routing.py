"""Проксирует обычные SIP-диалоги и завершает вызовы AI-сервисов."""

import hashlib
import re
import threading
import time

from . import runtime
from .agent_dialog import (
    accept_agent_invite,
    end_agent_call,
    handle_prack,
    handle_update,
    send_local_response,
)
from .control import notify_adapter, stop_adapter
from .messages import header


def request_method(message: str) -> str:
    request_line = message.split("\r\n", 1)[0]
    return request_line.split(" ", 1)[0]


def message_call_id(message: str) -> str:
    return header(message, "Call-ID") or header(message, "i")


def local_tag(call_id: str) -> str:
    """Детерминированный tag позволяет одинаково отвечать на retransmit."""
    return hashlib.sha256(call_id.encode()).hexdigest()[:16]


def terminate_for_agent(
    message: str,
    peer: tuple[str, int],
    service_mode: str,
) -> None:
    """Обработать локально один запрос диалога голосового сервиса."""
    method = request_method(message)
    call_id = message_call_id(message)
    tag = local_tag(call_id)

    if method == "INVITE":
        accept_agent_invite(message, peer, call_id, service_mode, tag)
    elif method == "ACK":
        print(f"AS received ACK for voice agent call_id={call_id}", flush=True)
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


def service_mode_for_request(message: str, request_line: str, call_id: str) -> str | None:
    """Сначала продолжить известный диалог, затем проверить номер услуги."""
    active_mode = runtime.agent_calls.get(call_id, {}).get("service_mode")
    if active_mode:
        return active_mode

    return runtime.service_targets.get(request_target(request_line) or "")


def request_target(request_line: str) -> str | None:
    """Номер или имя услуги из sip:/tel: Request-URI.

    Штатная звонилка набирает sip:1003;phone-context=...;user=phone, а S-CSCF
    переписывает его в tel:1003;phone-context=... Параметры отбрасываются.
    """
    target_match = re.search(r"^[A-Z]+\s+(?:sips?|tel):([^@;> ]+)", request_line)
    if target_match is None:
        return None
    return re.sub(r"[-.() ]", "", target_match.group(1))

    return None


def transaction_branch(message: str) -> str:
    """Поддержать полное и компактное имя SIP-заголовка Via."""
    branch_match = re.search(
        r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=([^;\s]+)",
        message,
    )
    return branch_match.group(1) if branch_match else str(time.time_ns())


def build_forwarded_request(message: str, branch: str) -> str:
    request_line, remaining_headers = message.split("\r\n", 1)
    own_via = (
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    )

    # Поглощается только Route текущего AS. Следующий ISC Route возвращает
    # запрос в S-CSCF, где продолжается обычная маршрутизация.
    remaining_headers = re.sub(
        r"(?im)^(Route\s*:\s*)<sip:as\.[^>]+>\s*,\s*",
        r"\1",
        remaining_headers,
        count=1,
    )
    return request_line + "\r\n" + own_via + remaining_headers


def observe_proxied_dialog(message: str, request_line: str, call_id: str) -> None:
    """Сообщить Media Adapter о начале/завершении обычного звонка."""
    if request_line.startswith("INVITE "):
        print(f"AS observed INVITE call_id={call_id}", flush=True)
        threading.Thread(
            target=notify_adapter,
            args=(message, "observe"),
            daemon=True,
        ).start()
    elif request_line.startswith(("BYE ", "CANCEL ")):
        threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()


def route_request(message: str, peer: tuple[str, int]) -> None:
    """Выбрать локальный AI-сервис либо проксирование обратно в S-CSCF."""
    request_line = message.split("\r\n", 1)[0]
    call_id = message_call_id(message)
    service_mode = service_mode_for_request(message, request_line, call_id)

    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return

    branch = transaction_branch(message)
    runtime.transactions[branch] = peer
    forwarded_request = build_forwarded_request(message, branch)

    observe_proxied_dialog(message, request_line, call_id)
    runtime.sock.sendto(forwarded_request.encode(), runtime.scscf)


def route_response(message: str) -> None:
    """Удалить собственный Via и вернуть ответ исходному SIP peer."""
    own_via_pattern = (
        r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*"
        r"branch=z9hG4bK-as-([^;\s]+)\r\n"
    )
    via_match = re.search(own_via_pattern, message)
    if via_match is None:
        print(
            f"AS dropped response without own Via: {message.splitlines()[0]}",
            flush=True,
        )
        return

    branch = via_match.group(1)
    destination_peer = runtime.transactions.get(branch)
    if destination_peer is None:
        print(f"AS dropped response for unknown transaction {branch}", flush=True)
        return

    response_without_own_via = re.sub(
        own_via_pattern,
        "",
        message,
        count=1,
    )
    print(
        f"AS relayed response {message.splitlines()[0]} "
        f"to {destination_peer[0]}:{destination_peer[1]}",
        flush=True,
    )
    runtime.sock.sendto(response_without_own_via.encode(), destination_peer)
