"""Собирает PCMU-кадры абонента в законченные речевые реплики."""

from __future__ import annotations

import base64
import hashlib
import time

from . import runtime, settings
from .audio import frame_rms
from .maintenance import expire_transient
from .queueing import enqueue_utterance

PCMU_FRAME_BYTES = 160  # 20 мс при PCMU/8000.
SUBSCRIBER_DIRECTIONS = {"caller_to_core", "caller_to_agent"}
DIALOGUE_MODES = {"bilingual_test", "interpret_ru", "interpret_en"}


def is_dialogue_mode(service_mode: str) -> bool:
    """Диалоговые тесты допускают более длинные фразы и транспортные паузы."""
    return service_mode in DIALOGUE_MODES


def phrase_limits(dialogue_mode: bool) -> tuple[int, int]:
    """Вернуть пороги тишины и максимальной длины в байтах PCMU."""
    if dialogue_mode:
        return (
            settings.dialogue_silence_bytes_required,
            settings.dialogue_max_utterance_bytes,
        )

    return settings.silence_bytes_required, settings.max_utterance_bytes


def decode_audio_chunk(event: dict) -> bytes | None:
    """Проверить медиаконтракт до добавления данных в общий буфер."""
    if event.get("codec") != "PCMU" or event.get("sample_rate_hz") != 8000:
        return None

    try:
        audio_chunk = base64.b64decode(event.get("audio_ulaw_b64", ""), validate=True)
    except ValueError:
        return None

    if not audio_chunk:
        return None

    expected_digest = event.get("audio_sha256")
    actual_digest = hashlib.sha256(audio_chunk).hexdigest()
    if actual_digest != expected_digest:
        print("AI rejected audio hash mismatch", flush=True)
        return None

    return audio_chunk


def stream_key(event: dict) -> str:
    """Call-ID не позволяет смешать два звонка при повторном использовании SSRC."""
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else "unbound"
    return f"{call_id}:{event.get('ssrc', 'unknown')}"


def empty_stream_state(now: float) -> dict:
    return {
        "utterance": bytearray(),
        "preroll": bytearray(),
        "speech_bytes": 0,
        "silence_bytes": 0,
        "in_speech": False,
        "utterance_started_at": None,
        "last_voice_packet_at": None,
        "last_seen": now,
    }


def get_stream_state(key: str, now: float) -> dict:
    """Создать буфер или вытеснить самый старый при достижении лимита."""
    if key not in runtime.buffers and len(runtime.buffers) >= settings.buffer_max:
        oldest_key = min(
            runtime.buffers,
            key=lambda candidate: runtime.buffers[candidate]["last_seen"],
        )
        runtime.buffers.pop(oldest_key, None)

    return runtime.buffers.setdefault(key, empty_stream_state(now))


def reset_phrase(state: dict) -> None:
    """Сохранить транспортное состояние потока, очистив только текущую фразу."""
    state.update(empty_stream_state(state["last_seen"]))


def queue_completed_phrase(
    state: dict,
    event: dict,
    received_at: float,
    reason: str,
) -> None:
    """Передать неизменяемый снимок фразы worker-у и очистить буфер."""
    completed_event = dict(event)
    completed_event["_utterance_started_at"] = state.get("utterance_started_at")
    completed_event["last_voice_packet_at"] = state.get("last_voice_packet_at")
    completed_audio = bytes(state["utterance"])

    reset_phrase(state)
    enqueue_utterance(completed_audio, completed_event, received_at, reason)


def close_phrase_after_transport_gap(
    state: dict,
    current_event: dict,
    received_at: float,
    dialogue_mode: bool,
) -> None:
    """Закрыть фразу, если клиент подавляет RTP-пакеты во время тишины."""
    observed_at = current_event.get("observed_at")
    previous_observed_at = state.get("observed_at")

    has_long_gap = (
        isinstance(observed_at, (int, float))
        and isinstance(previous_observed_at, (int, float))
        and observed_at - previous_observed_at >= settings.dialogue_event_gap_seconds
    )
    has_enough_speech = state["speech_bytes"] >= settings.min_utterance_bytes

    if not (dialogue_mode and state["in_speech"] and has_enough_speech and has_long_gap):
        return

    # У предыдущей фразы должны остаться её собственные метаданные, а не данные
    # первого пакета следующей фразы.
    previous_event = state.get("event", current_event)
    previous_received_at = state.get("received_at", received_at)
    queue_completed_phrase(state, previous_event, previous_received_at, "stream-gap")


def remember_latest_event(state: dict, event: dict, received_at: float, now: float) -> None:
    """Не сохранять base64-копию аудио второй раз в состоянии потока."""
    state["last_seen"] = now
    state["observed_at"] = event.get("observed_at")
    state["received_at"] = received_at
    state["event"] = {
        key: value
        for key, value in event.items()
        if key not in {"audio_ulaw_b64", "audio_frame_received_at"}
    }


def append_frame(state: dict, frame: bytes) -> None:
    """Обновить VAD-состояние одним 20-миллисекундным кадром."""
    frame_has_voice = frame_rms(frame) >= settings.vad_rms

    if frame_has_voice:
        if not state["in_speech"]:
            state["utterance"].extend(state["preroll"])
            state["preroll"].clear()
            state["in_speech"] = True
            state["utterance_started_at"] = time.time()

        state["utterance"].extend(frame)
        state["speech_bytes"] += len(frame)
        state["silence_bytes"] = 0
        return

    if state["in_speech"]:
        state["utterance"].extend(frame)
        state["silence_bytes"] += len(frame)
        return

    # Небольшой preroll не обрезает первый согласный после тишины.
    state["preroll"].extend(frame)
    del state["preroll"][: -settings.preroll_bytes]


def completion_reason(state: dict, silence_limit: int, utterance_limit: int) -> str | None:
    """Реплика заканчивается тишиной либо защитным пределом длительности."""
    if not state["in_speech"]:
        return None

    enough_speech = state["speech_bytes"] >= settings.min_utterance_bytes
    if enough_speech and state["silence_bytes"] >= silence_limit:
        return "silence"

    if len(state["utterance"]) >= utterance_limit:
        return "maximum-duration"

    return None


def process_audio_frames(
    audio_chunk: bytes,
    state: dict,
    event: dict,
    received_at: float,
    silence_limit: int,
    utterance_limit: int,
) -> None:
    """Последовательно применить VAD и поставить законченные фразы в очередь."""
    for frame_offset in range(0, len(audio_chunk), PCMU_FRAME_BYTES):
        frame = audio_chunk[frame_offset : frame_offset + PCMU_FRAME_BYTES]
        if len(frame) != PCMU_FRAME_BYTES:
            continue

        append_frame(state, frame)
        timestamps = event.get("audio_frame_received_at", [])
        frame_index = frame_offset // PCMU_FRAME_BYTES
        if state["in_speech"] and state["silence_bytes"] == 0 and frame_index < len(timestamps):
            state["last_voice_packet_at"] = timestamps[frame_index]

        reason = completion_reason(state, silence_limit, utterance_limit)
        if reason:
            queue_completed_phrase(state, event, received_at, reason)


def flush_idle_streams(now: float) -> None:
    """DTX produces no silent frames: finish without waiting for the next sentence.

    Called only by the media-assembler thread, after its input queue is drained.
    The timeout must exceed the publisher interval plus transport jitter.
    """
    for state in runtime.buffers.values():
        if (
            state["in_speech"]
            and state["speech_bytes"] >= settings.min_utterance_bytes
            and now - state["last_seen"] >= settings.dialogue_event_gap_seconds
        ):
            queue_completed_phrase(state, state["event"], state["received_at"], "idle-gap")


def process_event(event: dict) -> None:
    """Валидировать одно окно RTP и добавить его к соответствующему потоку."""
    service_mode = event.get("service_mode", "observe")
    dialogue_mode = is_dialogue_mode(service_mode)

    if event.get("direction") not in SUBSCRIBER_DIRECTIONS and not dialogue_mode:
        return

    audio_chunk = decode_audio_chunk(event)
    if audio_chunk is None:
        return

    now = time.time()
    received_at = event.get("received_at", now)
    silence_limit, utterance_limit = phrase_limits(dialogue_mode)

    expire_transient(now)
    state = get_stream_state(stream_key(event), now)

    close_phrase_after_transport_gap(state, event, received_at, dialogue_mode)
    remember_latest_event(state, event, received_at, now)
    process_audio_frames(
        audio_chunk,
        state,
        event,
        received_at,
        silence_limit,
        utterance_limit,
    )
