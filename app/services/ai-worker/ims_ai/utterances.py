"""Run each completed phrase through STT, normalization, and optional reply delivery."""

from __future__ import annotations

import hashlib
import time

import numpy as np

from . import runtime, settings
from .audio import decode_audio, decode_pcm8
from .interpretation import (
    INTERPRETER_MODES,
    delivery_call,
    output_voice,
    source_language,
    validate_output,
)
from .llm import (
    cyrillic_chars,
    deliver_reply,
    generate_reply,
    normalize_transcript,
    remember_turn,
    repair_translation_language,
)
from .maintenance import expire_events
from .recording import recording_session, save_recording_turn


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
    if call_id and service_mode in {"transcribe", "bilingual_test"}:
        normalized_transcript = transcript
        if service_mode == "bilingual_test":
            recording = recording_session(call_id)
            source_key = event.get("source_stream_id") or str(event.get("ssrc"))
            speaker = recording["speakers"].setdefault(
                source_key, f"speaker_{len(recording['speakers']) + 1}"
            )
        else:
            speaker = "caller"
        if transcript:
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
                        "normalized_transcript_cyrillic_chars": cyrillic_chars(
                            normalized_transcript
                        ),
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
        saved = save_recording_turn(
            call_id, decode_pcm8(ulaw), normalized_transcript, result, speaker
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
    if (
        transcript
        and call_id
        and service_mode in {"translate", "assistant", *INTERPRETER_MODES}
        and runtime.reply_counts.get(call_id, 0) < settings.max_replies_per_call
    ):
        try:
            reply, llm_ms = generate_reply(call_id, transcript, service_mode)
            if reply:
                reply_cyrillic = cyrillic_chars(reply)
                try:
                    latin_chars = validate_output(reply, service_mode, reply_cyrillic)
                except ValueError:
                    if service_mode not in INTERPRETER_MODES:
                        raise
                    reply, repair_ms = repair_translation_language(reply, service_mode)
                    llm_ms += repair_ms
                    reply_cyrillic = cyrillic_chars(reply)
                    latin_chars = validate_output(reply, service_mode, reply_cyrillic)
                reply_voice = output_voice(service_mode)
                target_call_id = delivery_call(call_id, service_mode)
                reply_id = hashlib.sha256(
                    f"{call_id}:{result['turn_index']}:{queued_at}".encode()
                ).hexdigest()[:16]
                dispatch_started = time.perf_counter_ns()
                deliver_reply(target_call_id, reply, reply_voice, reply_id)
                reply_dispatch_ms = (time.perf_counter_ns() - dispatch_started) / 1_000_000
                runtime.reply_counts[call_id] = runtime.reply_counts.get(call_id, 0) + 1
                remember_turn(call_id, transcript, reply)
                while len(runtime.reply_counts) > settings.buffer_max:
                    evicted = next(iter(runtime.reply_counts))
                    runtime.reply_counts.pop(evicted, None)
                    runtime.turn_counts.pop(evicted, None)
                    runtime.conversations.pop(evicted, None)
                result.update(
                    {
                        "llm_model": settings.llm_model,
                        "llm_response_chars": len(reply),
                        "llm_response_cyrillic_chars": reply_cyrillic,
                        "llm_response_latin_chars": latin_chars,
                        "reply_voice": reply_voice,
                        "reply_id": reply_id,
                        "llm_processing_ms": llm_ms,
                        "reply_delivered": True,
                        "reply_dispatch_ms": reply_dispatch_ms,
                        "reply_destination_mode": (
                            "interpret_en"
                            if service_mode == "interpret_ru"
                            else "interpret_ru"
                            if service_mode == "interpret_en"
                            else service_mode
                        ),
                        "reply_index": runtime.reply_counts[call_id],
                    }
                )
                print(
                    f"AI reply_delivered model={settings.llm_model} prompt_chars={len(transcript)} "
                    f"response_chars={len(reply)} llm_ms={llm_ms:.3f} calls={call_ids}",
                    flush=True,
                )
        except Exception as exc:
            result.update(
                {
                    "llm_model": settings.llm_model,
                    "reply_delivered": False,
                    "llm_error_type": type(exc).__name__,
                }
            )
            print(
                f"AI reply_failed model={settings.llm_model} type={type(exc).__name__} calls={call_ids}",
                flush=True,
            )
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
