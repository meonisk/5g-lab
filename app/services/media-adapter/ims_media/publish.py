"""Публикует ограниченные окна RTP без SIP-идентичностей абонентов."""

import base64
import hashlib
import threading
import time

from lab_common.http import request_json

from . import runtime
from .api import end_worker_call
from .rtpengine import resolve_subscriber_port


def match_session(
    source_port: int,
    destination_port: int,
    direction: str,
    active_sessions: dict,
):
    """Найти ровно один звонок, которому принадлежит RTP-поток."""
    if direction == "caller_to_agent":
        matching_sessions = [
            (call_id, session)
            for call_id, session in active_sessions.items()
            if session.get("rtpengine_port") == source_port
        ]
        return matching_sessions[0] if len(matching_sessions) == 1 else None

    if direction != "caller_to_core":
        return None

    matching_sessions = [
        (call_id, session)
        for call_id, session in active_sessions.items()
        if session.get("subscriber_port") == destination_port
    ]
    if len(matching_sessions) == 1:
        return matching_sessions[0]

    # Обычный абонентский звонок не завершается на Voice Agent. Когда такой
    # звонок один, его можно однозначно связать с наблюдаемым RTP-потоком.
    if len(active_sessions) == 1:
        call_id, session = next(iter(active_sessions.items()))
        if session.get("rtpengine_port") is None:
            return call_id, session

    return None


def refresh_subscriber_ports(active_sessions: dict) -> None:
    """Один раз получить у RTPengine порт абонентской стороны каждого звонка."""
    for call_id, current_session in list(active_sessions.items()):
        is_terminated_call = current_session.get("rtpengine_port") is not None
        already_resolved = current_session.get("subscriber_port") is not None
        if not is_terminated_call or already_resolved:
            continue

        subscriber_port = resolve_subscriber_port(call_id)
        if subscriber_port is None:
            continue

        resolved_session = dict(current_session)
        resolved_session["subscriber_port"] = subscriber_port
        active_sessions[call_id] = resolved_session

        with runtime.lock:
            if call_id in runtime.sessions:
                runtime.sessions[call_id]["subscriber_port"] = subscriber_port

        print(
            f"MEDIA mapped call_id={call_id} subscriber_port={subscriber_port}",
            flush=True,
        )


def take_batch_snapshot() -> tuple[dict, dict, list[str]]:
    """Атомарно забрать счётчики и снимок активных сессий."""
    with runtime.lock:
        media_windows = dict(runtime.counters)
        runtime.counters.clear()

        session_cutoff = time.time() - runtime.session_ttl
        expired_call_ids = [
            call_id
            for call_id, session in runtime.sessions.items()
            if session.get("observed_at", 0) < session_cutoff
        ]
        for call_id in expired_call_ids:
            runtime.sessions.pop(call_id, None)

        active_sessions = dict(runtime.sessions)

    return media_windows, active_sessions, expired_call_ids


def close_expired_worker_calls(expired_call_ids: list[str]) -> None:
    """Не задерживать цикл RTP сетевым запросом очистки AI-состояния."""
    for call_id in expired_call_ids:
        threading.Thread(
            target=end_worker_call,
            args=(call_id,),
            daemon=True,
        ).start()


def build_observation(
    call_id: str,
    session: dict,
    stream_identity: tuple,
    counters: dict,
) -> dict:
    """Создать событие без номера телефона, IMSI и исходного сетевого адреса."""
    ssrc, source_port, _destination_port, payload_type, direction = stream_identity
    audio = bytes(counters["audio"])

    observation = {
        "event": "normalized_audio_activity",
        "mode": "OBSERVE",
        "call_ids": [call_id],
        "service_mode": session["service_mode"],
        "ssrc": ssrc,
        "payload_type": payload_type,
        "packets": counters["packets"],
        "source_stream_id": hashlib.sha256(f"{source_port}:{ssrc}".encode()).hexdigest()[:16],
        "direction": direction,
        "payload_bytes": counters["payload_bytes"],
        "window_seconds": runtime.interval,
        "observed_at": time.time(),
    }

    if audio:
        observation.update(
            {
                "codec": "PCMU",
                "sample_rate_hz": 8000,
                "audio_bytes": len(audio),
                "audio_sha256": hashlib.sha256(audio).hexdigest(),
                "audio_ulaw_b64": base64.b64encode(audio).decode("ascii"),
            }
        )

    return observation


def deliver_observation(observation: dict) -> None:
    """Отказ AI фиксируется, но не влияет на RTP между абонентами."""
    try:
        request_json(
            "POST",
            runtime.worker_url,
            payload=observation,
            token=runtime.control_token,
            timeout=1,
        )
        print(
            f"MEDIA delivered direction={observation['direction']} "
            f"ssrc={observation['ssrc']} packets={observation['packets']} "
            f"audio={observation.get('audio_bytes', 0)} calls=1 "
            f"service={observation['service_mode']}",
            flush=True,
        )
    except Exception as error:
        print(
            f"MEDIA AI unavailable (media relay unaffected) type={type(error).__name__}",
            flush=True,
        )


def publish_media_windows(media_windows: dict, active_sessions: dict) -> None:
    """Связать каждое окно с одним звонком и отправить его AI Worker."""
    for stream_identity, counters in media_windows.items():
        _ssrc, source_port, destination_port, _payload_type, direction = stream_identity
        matched_session = match_session(
            source_port,
            destination_port,
            direction,
            active_sessions,
        )
        if matched_session is None:
            continue

        call_id, session = matched_session
        observation = build_observation(
            call_id,
            session,
            stream_identity,
            counters,
        )
        deliver_observation(observation)


def publish() -> None:
    """Периодически сбрасывать накопленные RTP-счётчики небольшими окнами."""
    while True:
        time.sleep(runtime.interval)

        media_windows, active_sessions, expired_call_ids = take_batch_snapshot()
        refresh_subscriber_ports(active_sessions)
        close_expired_worker_calls(expired_call_ids)
        publish_media_windows(media_windows, active_sessions)
