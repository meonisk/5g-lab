"""Связь SIP AS с обработчиками звука. Ошибка наблюдения не прерывает звонок."""

import re
import time
from urllib.parse import quote

from lab_common.http import request_json

from . import runtime
from .messages import header


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
            "call_id": header(message, "Call-ID") or header(message, "i"),
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
