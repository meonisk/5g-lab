"""Пропускает законченную реплику через STT и последующие действия режима."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import numpy as np

from . import runtime, settings
from .audio import decode_audio
from .interpretation import source_language
from .llm import cyrillic_chars
from .maintenance import expire_events
from .replies import reply_to_utterance
from .transcription import record_transcript


@dataclass(frozen=True)
class Recognition:
    transcript: str
    detected_language: str | None
    language_probability: float | None
    audio_rms: float
    processing_ms: float


def requested_language(service_mode: str) -> str | None:
    """Режим переводчика задаёт язык входной ноги; тест диалога определяет его сам."""
    language = source_language(service_mode)
    if language is None and service_mode != "bilingual_test":
        language = settings.language or None
    return language


def recognize(ulaw_audio: bytes, service_mode: str) -> Recognition:
    """Декодировать PCMU и выполнить STT только для достаточно громкой реплики."""
    audio_samples = decode_audio(ulaw_audio)
    audio_rms = float(np.sqrt(np.mean(np.square(audio_samples)))) if len(audio_samples) else 0.0

    recognition_started_at = time.perf_counter_ns()
    transcript = ""
    detected_language = None
    language_probability = None

    if runtime.model is not None and audio_rms > settings.stt_min_rms:
        segments, language_info = runtime.model.transcribe(
            audio_samples,
            language=requested_language(service_mode),
            task="transcribe",
            beam_size=settings.stt_beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        detected_language = language_info.language
        language_probability = language_info.language_probability

    return Recognition(
        transcript=transcript,
        detected_language=detected_language,
        language_probability=language_probability,
        audio_rms=audio_rms,
        processing_ms=(time.perf_counter_ns() - recognition_started_at) / 1_000_000,
    )


def single_call_id(event: dict) -> str | None:
    call_ids = event.get("call_ids") or []
    return call_ids[0] if len(call_ids) == 1 else None


def next_turn_index(call_id: str | None) -> int | None:
    if call_id is None:
        return None

    next_index = runtime.turn_counts.get(call_id, 0) + 1
    runtime.turn_counts[call_id] = next_index
    return next_index


def public_event_metadata(event: dict) -> dict:
    """Удалить аудио и внутренние временные поля из операционной метрики."""
    private_fields = {
        "audio_sha256",
        "audio_ulaw_b64",
        "audio_frame_received_at",
        "received_at",
        "_utterance_started_at",
    }
    return {key: value for key, value in event.items() if key not in private_fields}


def duration_ms(started_at: object, finished_at: float) -> float | None:
    if not isinstance(started_at, (int, float)):
        return None
    return (finished_at - started_at) * 1000


def build_result(
    ulaw_audio: bytes,
    event: dict,
    recognition: Recognition,
    service_mode: str,
    turn_index: int | None,
    received_at: float,
    queued_at: float,
    ai_started_at: float,
    end_reason: str,
) -> dict:
    """Собрать только безопасные данные, нужные тестам и измерению задержек."""
    result = public_event_metadata(event)
    result.update(
        {
            "backend_id": (
                f"{settings.backend}:{settings.model_size}:"
                f"{settings.device}:{settings.compute_type}"
            ),
            "model_revision": settings.model_revision,
            "audio_sha256": hashlib.sha256(ulaw_audio).hexdigest(),
            "audio_duration_seconds": len(ulaw_audio) / 8000,
            "audio_rms": recognition.audio_rms,
            "transcript_chars": len(recognition.transcript),
            "transcript_cyrillic_chars": cyrillic_chars(recognition.transcript),
            "detected_language": recognition.detected_language,
            "language_probability": recognition.language_probability,
            "received_at": received_at,
            "sentence_ready_at": queued_at,
            "ai_started_at": ai_started_at,
            "utterance_end_reason": end_reason,
            "turn_index": turn_index,
            "service_mode": service_mode,
            "processing_ms": recognition.processing_ms,
            "stt_processing_ms": recognition.processing_ms,
            "sentence_assembly_ms": duration_ms(
                event.get("_utterance_started_at"),
                queued_at,
            ),
            "queue_wait_ms": duration_ms(queued_at, ai_started_at),
            "adapter_to_worker_ms": duration_ms(
                event.get("observed_at"),
                received_at,
            ),
        }
    )
    return result


def store_completed_result(result: dict, ai_started_at: float, queued_at: float) -> None:
    """Добавить итоговые задержки и сохранить событие под общей блокировкой."""
    processed_at = time.time()
    result.update(
        {
            "processed_at": processed_at,
            "ai_total_ms": duration_ms(ai_started_at, processed_at),
            "sentence_to_reply_ms": duration_ms(queued_at, processed_at),
        }
    )

    with runtime.lock:
        runtime.events.append(result)
        expire_events(processed_at)


def process_utterance(
    ulaw_audio: bytes,
    event: dict,
    received_at: float,
    end_reason: str,
    queued_at: float,
) -> None:
    """Обработать одну реплику, не смешивая независимые действия режимов."""
    service_mode = event.get("service_mode", "observe")
    ai_started_at = time.time()

    recognition = recognize(ulaw_audio, service_mode)
    call_id = single_call_id(event)
    turn_index = next_turn_index(call_id)
    result = build_result(
        ulaw_audio,
        event,
        recognition,
        service_mode,
        turn_index,
        received_at,
        queued_at,
        ai_started_at,
        end_reason,
    )

    # После общего STT режим выбирает независимые действия: сохранить запись,
    # сформировать ответ либо только оставить техническую метрику.
    record_transcript(
        ulaw_audio,
        event,
        result,
        recognition.transcript,
        recognition.detected_language,
    )
    reply_to_utterance(
        event,
        result,
        recognition.transcript,
        queued_at,
    )
    store_completed_result(result, ai_started_at, queued_at)

    print(
        f"AI utterance_processed backend={result['backend_id']} "
        f"audio_seconds={result['audio_duration_seconds']:.3f} "
        f"rms={recognition.audio_rms:.5f} "
        f"transcript_chars={len(recognition.transcript)} "
        f"language={recognition.detected_language} "
        f"end={end_reason} calls={event.get('call_ids')}",
        flush=True,
    )
