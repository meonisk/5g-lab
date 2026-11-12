"""Сохранение реплики: нормализация, метка спикера и приватная запись."""

from __future__ import annotations

from . import runtime, settings
from .audio import decode_pcm8
from .llm import (
    cyrillic_chars,
    normalize_transcript,
)
from .recording import recording_target, save_recording_turn


def record_transcript(ulaw, event, result, transcript, detected_language):
    service_mode = result["service_mode"]
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else None
    target = recording_target(call_id, service_mode, event) if call_id else None
    if target is None:
        return
    session_call_id, speaker = target

    normalized_transcript = transcript
    if transcript and settings.transcript_normalization == "raw":
        result.update({"normalization_applied": False, "transcript_kind": "raw_asr"})
    elif transcript:
        try:
            normalized_transcript, normalization_ms = normalize_transcript(
                transcript, detected_language
            )
            result.update(
                {
                    "normalization_applied": True,
                    "normalization_llm_model": settings.llm_model,
                    "normalization_processing_ms": normalization_ms,
                    "normalized_transcript_chars": len(normalized_transcript),
                    "normalized_transcript_cyrillic_chars": cyrillic_chars(normalized_transcript),
                }
            )
            print(
                f"AI transcript_normalized model={settings.llm_model} input_chars={len(transcript)} "
                f"output_chars={len(normalized_transcript)} llm_ms={normalization_ms:.3f} "
                f"calls={call_ids}",
                flush=True,
            )
        except Exception as exc:
            # Fail closed for text persistence: keep the WAV so the turn can
            # be reprocessed, but never label raw STT output as normalized.
            normalized_transcript = ""
            result.update(
                {
                    "normalization_applied": False,
                    "normalization_error_type": type(exc).__name__,
                }
            )
            print(
                f"AI transcript_normalization_failed model={settings.llm_model} "
                f"type={type(exc).__name__} calls={call_ids}",
                flush=True,
            )
    # Две ноги одного звонка пишут в один каталог из разных обработчиков.
    with runtime.recording_lock:
        saved = save_recording_turn(
            session_call_id, decode_pcm8(ulaw), normalized_transcript, result, speaker
        )
    if saved:
        result.update(
            {
                "recording_session_id": saved["session_id"],
                "recording_saved": saved["saved"],
                "recording_turn": saved.get("turn"),
                "recording_limit_reached": saved.get("limit_reached", False),
            }
        )
