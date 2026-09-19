"""Проксирует обычные SIP-диалоги и завершает вызовы AI-сервисов."""

import hashlib
import ipaddress
import re
import threading
import time

from . import runtime
from .control import notify_adapter, notify_voice, stop_adapter, stop_voice
from .messages import header, local_response


def request_method(message: str) -> str:
    request_line = message.split("\r\n", 1)[0]
    return request_line.split(" ", 1)[0]


def message_call_id(message: str) -> str:
    return header(message, "Call-ID") or header(message, "i")


def local_tag(call_id: str) -> str:
    """Детерминированный tag позволяет одинаково отвечать на retransmit."""
    return hashlib.sha256(call_id.encode()).hexdigest()[:16]


def send_local_response(
    request: str,
    peer: tuple[str, int],
    status_code: int,
    reason: str,
    *,
    body: str = "",
    to_tag: str = "",
    contact_user: str = "",
) -> None:
    response = local_response(
        request,
        status_code,
        reason,
        body,
        to_tag,
        contact_user,
    )
    runtime.sock.sendto(response.encode(), peer)


def offered_media_endpoint(message: str) -> tuple[str, int] | None:
    """Извлечь IPv4 и RTP-порт из SDP offer."""
    connection_match = re.search(r"(?im)^c=IN IP4 ([^\s]+)", message)
    media_match = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
    if connection_match is None or media_match is None:
        return None

    try:
        offered_ip = str(ipaddress.ip_address(connection_match.group(1)))
        offered_port = int(media_match.group(1))
    except ValueError:
        return None

    return offered_ip, offered_port


def media_is_anchored(offered_ip: str, offered_port: int) -> bool:
    """AI Agent принимает RTP только от настроенного пула RTPengine."""
    return (
        offered_ip == runtime.rtpengine_ip
        and runtime.rtp_port_min <= offered_port <= runtime.rtp_port_max
    )


def voice_agent_sdp() -> str:
    """Сформировать минимальный ответ для единственного кодека PCMU/8000."""
    return (
        "v=0\r\n"
        f"o=voice-agent 1 1 IN IP4 {runtime.voice_ip}\r\n"
        "s=IMS Voice Agent\r\n"
        f"c=IN IP4 {runtime.voice_ip}\r\n"
        "t=0 0\r\n"
        f"m=audio {runtime.voice_rtp_port} RTP/AVP 0\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=ptime:20\r\n"
        "a=sendrecv\r\n"
    )


def start_agent_call(
    message: str,
    call_id: str,
    offered_ip: str,
    offered_port: int,
    service_mode: str,
    tag: str,
) -> bool:
    """Создать Voice/Media состояние один раз; INVITE может повторяться."""
    if call_id in runtime.agent_calls:
        return True

    try:
        notify_voice(call_id, offered_ip, offered_port, service_mode)
        runtime.agent_calls[call_id] = {
            "tag": tag,
            "service_mode": service_mode,
            "rtpengine_port": offered_port,
        }

        # Наблюдение не задерживает SIP-ответ и может отказать независимо.
        threading.Thread(
            target=notify_adapter,
            args=(message, service_mode, offered_port),
            daemon=True,
        ).start()
        return True
    except Exception as error:
        print(
            f"AS voice unavailable call_id={call_id} type={type(error).__name__}",
            flush=True,
        )
        return False


def accept_agent_invite(
    message: str,
    peer: tuple[str, int],
    call_id: str,
    service_mode: str,
    tag: str,
) -> None:
    send_local_response(message, peer, 100, "Trying")

    media_endpoint = offered_media_endpoint(message)
    if media_endpoint is None:
        send_local_response(
            message,
            peer,
            488,
            "Not Acceptable Here",
            to_tag=tag,
        )
        return

    offered_ip, offered_port = media_endpoint

    # P-CSCF обязан заякорить offer до iFC. Иначе SIP-абонент мог бы заставить
    # Voice Agent отправлять RTP на произвольный адрес (media SSRF/amplification).
    if not media_is_anchored(offered_ip, offered_port):
        print(f"AS rejected unanchored media call_id={call_id}", flush=True)
        send_local_response(
            message,
            peer,
            488,
            "Media Must Be Anchored",
            to_tag=tag,
        )
        return

    if not start_agent_call(
        message,
        call_id,
        offered_ip,
        offered_port,
        service_mode,
        tag,
    ):
        send_local_response(
            message,
            peer,
            503,
            "Voice Agent Unavailable",
            to_tag=tag,
        )
        return

    service_user = runtime.service_users[service_mode]
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=voice_agent_sdp(),
        to_tag=tag,
        contact_user=service_user,
    )
    print(
        f"AS terminated INVITE for voice agent call_id={call_id} service={service_mode}",
        flush=True,
    )


def end_agent_call(
    message: str,
    peer: tuple[str, int],
    call_id: str,
    method: str,
    fallback_tag: str,
) -> None:
    call = runtime.agent_calls.get(call_id, {})
    send_local_response(
        message,
        peer,
        200,
        "OK",
        to_tag=call.get("tag", fallback_tag),
    )
    runtime.agent_calls.pop(call_id, None)

    # Очистка вспомогательных сервисов не задерживает SIP 200 OK.
    threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
    threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)


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


def service_mode_for_request(message: str, request_line: str, call_id: str) -> str | None:
    """Сначала продолжить известный диалог, затем проверить номер услуги."""
    active_mode = runtime.agent_calls.get(call_id, {}).get("service_mode")
    if active_mode:
        return active_mode

    target_match = re.search(r"^[A-Z]+\s+sip:([^@; ]+)", request_line)
    if target_match:
        return runtime.service_targets.get(target_match.group(1))

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
