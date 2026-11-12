"""API MRF: Voice Agent (озвучка в ногу) и Media Adapter (поток на распознавание).

Ошибка наблюдения не прерывает звонок; привязка ноги к Voice Agent обязательна.
"""

import re
import time
from urllib.parse import quote

from lab_common.http import request_json

from .. import runtime
from .sip import message_call_id


def best_effort(method, url, payload=None):
    """Используется для необязательного наблюдения и идемпотентной очистки."""
    try:
        request_json(method, url, payload=payload, token=runtime.control_token, timeout=1)
    except Exception as exc:
        print(f"AS service unavailable (call continues) type={type(exc).__name__}", flush=True)


def notify_adapter(message, service_mode="observe", rtpengine_port=None):
    if rtpengine_port is None:
        media = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
        rtpengine_port = int(media.group(1)) if media else None
    best_effort(
        "POST",
        runtime.adapter_url,
        {
            "call_id": message_call_id(message),
            "observed_at": time.time(),
            "service_mode": service_mode,
            "rtpengine_port": rtpengine_port,
        },
    )


def stop_adapter(call_id):
    best_effort("DELETE", f"{runtime.adapter_url}/{quote(call_id, safe='')}")


def notify_voice(call_id, remote_ip, remote_port, service_mode):
    # Для TERMINATE-звонка голосовой сервис обязателен: ошибка возвращается SIP-слою.
    request_json(
        "POST",
        runtime.voice_url,
        token=runtime.control_token,
        payload={
            "call_id": call_id,
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "service_mode": service_mode,
        },
    )


def stop_voice(call_id):
    best_effort("DELETE", f"{runtime.voice_url}/{quote(call_id, safe='')}")


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
