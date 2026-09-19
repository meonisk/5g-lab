"""Run each completed phrase through STT, normalization, and optional reply delivery."""

from __future__ import annotations

import hashlib
import time

import numpy as np

from . import runtime, settings
from .audio import decode_audio
from .interpretation import source_language
from .llm import cyrillic_chars
from .maintenance import expire_events
from .replies import reply_to_utterance
from .transcription import record_transcript


def process_utterance(ulaw, event, received_at, end_reason, queued_at):
    service_mode = event.get("service_mode", "observe")
    ai_started_at = time.time()
    audio = decode_audio(ulaw)
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    stt_started = time.perf_counter_ns()
    transcript = ""
    detected_language = None
    language_probability = None
    if runtime.model is not None and rms > settings.stt_min_rms:
        requested_language = source_language(service_mode)
        if requested_language is None and service_mode != "bilingual_test":
            requested_language = settings.language or None
        segments, info = runtime.model.transcribe(
            audio,
            language=requested_language,
            task="transcribe",
            beam_size=settings.stt_beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        detected_language = info.language
        language_probability = info.language_probability
    stt_ms = (time.perf_counter_ns() - stt_started) / 1_000_000
    result = {
        key: value
        for key, value in event.items()
        if key
        not in {
            "audio_sha256",
            "audio_ulaw_b64",
            "received_at",
            "_utterance_started_at",
        }
    }
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else None
    if call_id:
        runtime.turn_counts[call_id] = runtime.turn_counts.get(call_id, 0) + 1
    result.update(
        {
            "backend_id": f"{settings.backend}:{settings.model_size}:{settings.device}:{settings.compute_type}",
            "model_revision": settings.model_revision,
            "audio_sha256": hashlib.sha256(ulaw).hexdigest(),
            "audio_duration_seconds": len(ulaw) / 8000,
            "audio_rms": rms,
            "transcript_chars": len(transcript),
            "transcript_cyrillic_chars": cyrillic_chars(transcript),
            "detected_language": detected_language,
            "language_probability": language_probability,
            "received_at": received_at,
            "sentence_ready_at": queued_at,
            "ai_started_at": ai_started_at,
            "utterance_end_reason": end_reason,
            "turn_index": runtime.turn_counts.get(call_id) if call_id else None,
            "service_mode": service_mode,
            "processing_ms": stt_ms,
            "stt_processing_ms": stt_ms,
            "sentence_assembly_ms": (
                (queued_at - event["_utterance_started_at"]) * 1000
                if isinstance(event.get("_utterance_started_at"), (int, float))
                else None
            ),
            "queue_wait_ms": (ai_started_at - queued_at) * 1000,
            "adapter_to_worker_ms": (
                (received_at - event["observed_at"]) * 1000
                if isinstance(event.get("observed_at"), (int, float))
                else None
            ),
        }
    )
    # После STT выбираем независимые действия по режиму звонка.
    record_transcript(ulaw, event, result, transcript, detected_language)
    reply_to_utterance(event, result, transcript, queued_at)
    processed_at = time.time()
    result.update(
        {
            "processed_at": processed_at,
            "ai_total_ms": (processed_at - ai_started_at) * 1000,
            "sentence_to_reply_ms": (processed_at - queued_at) * 1000,
        }
    )
    with runtime.lock:
        runtime.events.append(result)
        expire_events(processed_at)
    print(
        f"AI utterance_processed backend={result['backend_id']} "
        f"audio_seconds={result['audio_duration_seconds']:.3f} rms={rms:.5f} "
        f"transcript_chars={len(transcript)} language={detected_language} "
        f"end={end_reason} calls={event.get('call_ids')}",
        flush=True,
    )
