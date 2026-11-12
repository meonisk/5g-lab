"""numbers AS: 1003–1006 завершаются на Voice Agent, остальные вызовы — прокси с observe."""

import re

from .. import runtime
from ..core import dialogs, mrf
from ..core.mrf import media_is_anchored, voice_agent_sdp
from ..core.proxy import forward
from ..core.sdp import accepts_pcmu, offered_media_endpoint
from ..core.sip import local_tag, message_call_id, request_method
from ..core.transport import send_local_response

HOST = "as"


def start_agent_call(message, call_id, offered_ip, offered_port, service_mode, tag) -> bool:
    """Создать Voice/Media состояние один раз; INVITE может повторяться."""
    if call_id in runtime.agent_calls:
        return True
    if not mrf.bind_leg(message, call_id, offered_ip, offered_port, service_mode):
        return False
    runtime.agent_calls[call_id] = {
        "tag": tag,
        "service_mode": service_mode,
        "rtpengine_port": offered_port,
    }
    return True


def accept_agent_invite(message, peer, call_id, service_mode, tag) -> None:
    send_local_response(message, peer, 100, "Trying")
    media_endpoint = offered_media_endpoint(message)
    if media_endpoint is None or not accepts_pcmu(message):
        send_local_response(message, peer, 488, "Not Acceptable Here", to_tag=tag)
        return
    offered_ip, offered_port = media_endpoint
    # P-CSCF обязан заякорить offer до iFC. Иначе SIP-абонент мог бы заставить
    # Voice Agent отправлять RTP на произвольный адрес (media SSRF/amplification).
    if not media_is_anchored(offered_ip, offered_port):
        print(f"AS rejected unanchored media call_id={call_id}", flush=True)
        send_local_response(message, peer, 488, "Media Must Be Anchored", to_tag=tag)
        return
    if not start_agent_call(message, call_id, offered_ip, offered_port, service_mode, tag):
        send_local_response(message, peer, 503, "Voice Agent Unavailable", to_tag=tag)
        return
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=voice_agent_sdp(),
        to_tag=tag,
        contact_user=runtime.service_users[service_mode],
    )
    print(
        f"AS terminated INVITE for voice agent call_id={call_id} service={service_mode}",
        flush=True,
    )


def end_agent_call(message, peer, call_id, method, fallback_tag) -> None:
    call = runtime.agent_calls.get(call_id, {})
    send_local_response(message, peer, 200, "OK", to_tag=call.get("tag", fallback_tag))
    runtime.agent_calls.pop(call_id, None)
    # Очистка вспомогательных сервисов не задерживает SIP 200 OK.
    mrf.release(call_id)
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)


def terminate_for_agent(message, peer, service_mode) -> None:
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


def service_mode_for_request(request_line: str, call_id: str) -> str | None:
    """Сначала продолжить известный диалог, затем проверить номер услуги."""
    active_mode = runtime.agent_calls.get(call_id, {}).get("service_mode")
    if active_mode:
        return active_mode
    target_match = re.search(r"^[A-Z]+\s+sip:([^@; ]+)", request_line)
    if target_match:
        return runtime.service_targets.get(target_match.group(1))
    return None


def observe_proxied_dialog(message: str, request_line: str, call_id: str) -> None:
    """Сообщить Media Adapter о начале/завершении обычного звонка."""
    if request_line.startswith("INVITE "):
        print(f"AS observed INVITE call_id={call_id}", flush=True)
        mrf.stream_to_recognition(message, "observe")
    elif request_line.startswith(("BYE ", "CANCEL ")):
        mrf.stop_recognition(call_id)


def handle(message: str, peer: tuple[str, int]) -> None:
    """Номер услуги — завершить на Voice Agent, иначе наблюдать и вернуть в S-CSCF."""
    request_line = message.split("\r\n", 1)[0]
    call_id = message_call_id(message)
    service_mode = service_mode_for_request(request_line, call_id)
    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return
    # Ногу B (B2BUA) и звонок под записью уже распознаёт услуга: не наблюдать дважды.
    if not (dialogs.is_own(call_id) or dialogs.is_marked_record(call_id)):
        observe_proxied_dialog(message, request_line, call_id)
    forward(message, peer)
