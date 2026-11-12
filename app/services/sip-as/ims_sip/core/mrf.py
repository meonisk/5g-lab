"""API MRF: Voice Agent (озвучка в ногу) и Media Adapter (поток на распознавание).

Ошибка наблюдения не прерывает звонок; привязка ноги к Voice Agent обязательна.
"""

import re
import threading
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


INTERPRETER_MODES = {"ru": "interpret_ru", "en": "interpret_en"}


def free_slots() -> int:
    """Свободные места Voice Agent; ошибка опроса — мест нет, звонок идёт без перевода."""
    try:
        status = request_json(
            "GET", runtime.voice_status_url, token=runtime.control_token, timeout=1
        )
    except Exception as exc:
        print(f"AS mrf status unavailable type={type(exc).__name__}", flush=True)
        return 0
    return max(0, runtime.voice_max_calls - len((status or {}).get("calls", {})))


def bind_leg(message, call_id, remote_ip, remote_port, service_mode) -> bool:
    """Привязать ногу: Voice Agent обязателен, Media Adapter — в фоне и без отказа звонка."""
    try:
        notify_voice(call_id, remote_ip, remote_port, service_mode)
    except Exception as error:
        print(f"AS voice unavailable call_id={call_id} type={type(error).__name__}", flush=True)
        return False
    stream_to_recognition(message, service_mode, remote_port)
    return True


def stream_to_recognition(message, service_mode, rtpengine_port=None) -> None:
    """Отдавать звук звонка из RTPengine на распознавание (Call-ID берётся из message)."""
    threading.Thread(
        target=notify_adapter, args=(message, service_mode, rtpengine_port), daemon=True
    ).start()


def stop_recognition(call_id) -> None:
    threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()


def release(call_id) -> None:
    """Освободить ногу: место Voice Agent и поток распознавания."""
    threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
    stop_recognition(call_id)


def play(call_id, text, voice) -> bool:
    """Сыграть фразу в ногу, привязанную к Voice Agent."""
    url = f"{runtime.voice_url}/{quote(call_id, safe='')}/reply"
    payload = {"text": text, "voice": voice, "reason": "announcement"}
    try:
        request_json("POST", url, payload=payload, token=runtime.control_token, timeout=2)
    except Exception as exc:
        print(f"AS mrf play failed call_id={call_id} type={type(exc).__name__}", flush=True)
        return False
    return True


def pair(leg_a, leg_b) -> None:
    """Сообщить AI Worker пару ног перевода: (Call-ID, язык) каждой стороны."""
    legs = [{"call_id": call_id, "language": language} for call_id, language in (leg_a, leg_b)]
    best_effort("POST", f"{runtime.ai_worker_url}/pairs", {"legs": legs})


def unpair(call_id) -> None:
    best_effort("DELETE", f"{runtime.ai_worker_url}/pairs/{quote(call_id, safe='')}")


def record_pair(session_call_id, legs) -> None:
    """Писать обе ноги в одну запись AI Worker: legs — [(Call-ID, caller|callee)]."""
    payload = {
        "session_call_id": session_call_id,
        "legs": [{"call_id": call_id, "speaker": speaker} for call_id, speaker in legs],
    }
    best_effort("POST", f"{runtime.ai_worker_url}/recordings", payload)


def announce(call_id, parties) -> bool:
    """Уведомление через RTPengine звонку без MRF: parties — [(SIP tag, текст, голос)]."""
    url = f"{runtime.adapter_url}/{quote(call_id, safe='')}/announce"
    payload = {"parties": [{"tag": t, "text": x, "voice": v} for t, x, v in parties]}
    try:
        request_json("POST", url, payload=payload, token=runtime.control_token, timeout=40)
    except Exception as exc:
        print(f"AS mrf announce failed call_id={call_id} type={type(exc).__name__}", flush=True)
        return False
    return True
