import base64
import hashlib
import hmac
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

events = []
buffers = {}
lock = threading.Lock()
work = queue.Queue(maxsize=int(os.environ["AI_QUEUE_MAX"]))
event_retention = int(os.environ["AI_EVENT_RETENTION"])
retention_seconds = int(os.environ["AI_TRANSCRIPT_RETENTION_SECONDS"])
buffer_max = int(os.environ["AI_STREAM_BUFFER_MAX"])
buffer_ttl = int(os.environ["AI_STREAM_BUFFER_TTL_SECONDS"])
max_replies_per_call = int(os.environ["AI_MAX_REPLIES_PER_CALL"])
history_turns = int(os.environ["AI_CONVERSATION_HISTORY_TURNS"])
conversation_ttl = int(os.environ["AI_CONVERSATION_TTL_SECONDS"])
request_max_bytes = int(os.environ["AI_REQUEST_MAX_BYTES"])
vad_rms = int(os.environ["AI_VAD_RMS"])
min_utterance_bytes = int(float(os.environ["AI_UTTERANCE_MIN_SECONDS"]) * 8000)
silence_bytes_required = int(float(os.environ["AI_UTTERANCE_SILENCE_MS"]) / 1000 * 8000)
max_utterance_bytes = int(float(os.environ["AI_UTTERANCE_MAX_SECONDS"]) * 8000)
dialogue_silence_bytes_required = int(
    float(os.environ["AI_DIALOGUE_UTTERANCE_SILENCE_MS"]) / 1000 * 8000)
dialogue_max_utterance_bytes = int(
    float(os.environ["AI_DIALOGUE_UTTERANCE_MAX_SECONDS"]) * 8000)
dialogue_event_gap_seconds = float(os.environ["AI_DIALOGUE_EVENT_GAP_MS"]) / 1000
preroll_bytes = int(float(os.environ["AI_AUDIO_PREROLL_MS"]) / 1000 * 8000)
backend = os.environ["AI_BACKEND"]
model_size = os.environ["AI_MODEL_SIZE"]
model_revision = os.environ["AI_MODEL_REVISION"]
device = os.environ["AI_DEVICE"]
compute_type = os.environ["AI_COMPUTE_TYPE"]
language = os.environ["AI_LANGUAGE"]
llm_url = os.environ["LLM_URL"]
llm_model = os.environ["LLM_MODEL"]
llm_timeout = float(os.environ["LLM_TIMEOUT_SECONDS"])
llm_max_tokens = int(os.environ["LLM_MAX_TOKENS"])
llm_temperature = float(os.environ["LLM_TEMPERATURE"])
llm_system_prompt = os.environ["LLM_SYSTEM_PROMPT"]
llm_translation_prompt = os.environ["LLM_TRANSLATION_PROMPT"]
llm_transcription_prompt = os.environ["LLM_TRANSCRIPTION_PROMPT"]
llm_english_transcription_prompt = os.environ["LLM_ENGLISH_TRANSCRIPTION_PROMPT"]
llm_normalization_max_tokens = int(os.environ["LLM_NORMALIZATION_MAX_TOKENS"])
normalized_transcript_max_chars = int(os.environ["TRANSCRIPT_NORMALIZED_MAX_CHARS"])
llm_response_max_chars = int(os.environ["VOICE_AGENT_REPLY_MAX_CHARS"])
translation_voice = os.environ["TTS_TRANSLATION_VOICE"]
translation_min_latin = int(os.environ["TRANSLATION_MIN_LATIN_CHARS"])
translation_max_cyrillic = int(os.environ["TRANSLATION_MAX_CYRILLIC_CHARS"])
voice_agent_url = os.environ["VOICE_AGENT_URL"].rstrip("/")
recording_enabled = os.environ["RECORDING_ENABLED"] == "1"
recording_root = Path(os.environ["RECORDING_ROOT"])
recording_max_bytes = int(os.environ["RECORDING_MAX_BYTES_PER_CALL"])
recording_retention_days = int(os.environ["RECORDING_RETENTION_DAYS"])
model = None
model_error = None
reply_counts = {}
turn_counts = {}
conversations = {}
recordings = {}
call_id_pattern = re.compile(r"^[A-Za-z0-9_.+~-]{1,128}$")
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()


def expire_events(now):
    events[:] = [item for item in events if now - item.get("processed_at", now) <= retention_seconds]
    del events[:-event_retention]


def expire_transient(now):
    for stale_key in [key for key, value in buffers.items() if now - value["last_seen"] > buffer_ttl]:
        buffers.pop(stale_key, None)
    for call_id in [key for key, value in conversations.items()
                    if now - value["last_seen"] > conversation_ttl]:
        conversations.pop(call_id, None)
        reply_counts.pop(call_id, None)
        turn_counts.pop(call_id, None)


def load_model():
    global model, model_error
    try:
        started = time.perf_counter()
        model = WhisperModel(model_size, device=device, compute_type=compute_type,
                             download_root=os.environ["AI_MODEL_CACHE"], revision=model_revision)
        print(f"AI model_ready backend={backend} model={model_size} device={device} "
              f"load_seconds={time.perf_counter() - started:.3f}", flush=True)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {exc}"
        print(f"AI model_failed backend={backend} model={model_size} error={model_error}", flush=True)


def ulaw_sample(value):
    value = (~value) & 0xff
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0f
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample


ULAW_TABLE = np.array([ulaw_sample(value) for value in range(256)], dtype=np.int16)


def decode_pcm8(ulaw):
    return ULAW_TABLE[np.frombuffer(ulaw, dtype=np.uint8)]


def decode_audio(ulaw):
    pcm8 = decode_pcm8(ulaw)
    pcm16 = np.repeat(pcm8, 2)
    return pcm16.astype(np.float32) / 32768.0


def frame_rms(ulaw):
    pcm = decode_pcm8(ulaw).astype(np.float64)
    return int(np.sqrt(np.mean(np.square(pcm)))) if len(pcm) else 0


def cyrillic_chars(text):
    return sum("\u0400" <= char <= "\u052f" for char in text)


def generate_reply(call_id, transcript, service_mode):
    conversation = conversations.setdefault(call_id, {"messages": [], "last_seen": time.time()})
    conversation["last_seen"] = time.time()
    system_prompt = llm_translation_prompt if service_mode == "translate" else llm_system_prompt
    request_body = json.dumps({
        "model": llm_model,
        "stream": False,
        "messages": ([{"role": "system", "content": system_prompt}]
                     + conversation["messages"]
                     + [{"role": "user", "content": transcript}]),
        "options": {"temperature": llm_temperature, "num_predict": llm_max_tokens},
    }).encode()
    request = urllib.request.Request(llm_url, request_body, {"Content-Type": "application/json"})
    started = time.perf_counter_ns()
    response = json.load(urllib.request.urlopen(request, timeout=llm_timeout))
    text = " ".join(response["message"]["content"].split())[:llm_response_max_chars]
    return text, (time.perf_counter_ns() - started) / 1_000_000


def normalize_transcript(transcript, detected_language):
    prompt = (llm_english_transcription_prompt
              if detected_language == "en" else llm_transcription_prompt)
    wrapper = (f"Input: «{transcript}»\nOutput:"
               if detected_language == "en" else f"Вход: «{transcript}»\nВыход:")
    request_body = json.dumps({
        "model": llm_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": wrapper},
        ],
        "options": {"temperature": 0, "num_predict": llm_normalization_max_tokens},
    }).encode()
    request = urllib.request.Request(llm_url, request_body, {"Content-Type": "application/json"})
    started = time.perf_counter_ns()
    response = json.load(urllib.request.urlopen(request, timeout=llm_timeout))
    normalized = " ".join(response["message"]["content"].split())
    normalized = normalized.strip().strip('"«»').strip()
    if not normalized or len(normalized) > normalized_transcript_max_chars:
        raise ValueError("normalized transcript has invalid length")
    if cyrillic_chars(transcript) and not cyrillic_chars(normalized):
        raise ValueError("normalized transcript changed language")
    if detected_language == "en" and not any(char.isascii() and char.isalpha() for char in normalized):
        raise ValueError("normalized English transcript changed language")
    if re.match(r"(?i)^(?:(?:нормализованный|исправленный|очищенный)\s+текст|выход(?:ит)?|output)\s*:", normalized):
        raise ValueError("normalized transcript contains a preamble")
    return normalized, (time.perf_counter_ns() - started) / 1_000_000


def remember_turn(call_id, transcript, reply):
    conversation = conversations.setdefault(call_id, {"messages": [], "last_seen": time.time()})
    conversation["messages"].extend((
        {"role": "user", "content": transcript},
        {"role": "assistant", "content": reply},
    ))
    conversation["messages"] = conversation["messages"][-history_turns * 2:]
    conversation["last_seen"] = time.time()


def deliver_reply(call_id, text, voice):
    body = json.dumps({"text": text, "voice": voice}).encode()
    request = urllib.request.Request(
        f"{voice_agent_url}/calls/{urllib.parse.quote(call_id, safe='')}/reply",
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {control_token}"},
    )
    urllib.request.urlopen(request, timeout=3).read()


def recording_session(call_id):
    state = recordings.get(call_id)
    if state:
        return state
    session_id = hashlib.sha256(call_id.encode()).hexdigest()[:20]
    path = recording_root / session_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = {"session_id": session_id, "path": path, "turns": 0, "audio_bytes": 0,
             "started_at": time.time(), "transcript_chars": 0, "speakers": {}}
    recordings[call_id] = state
    notice = ("PRIVATE LOCAL RECORDING\n"
              "Created only by an explicit call to the transcription service.\n"
              f"Configured retention: {recording_retention_days} days.\n"
              "Review and delete this directory according to the declared policy.\n")
    (path / "README.txt").write_text(notice, encoding="utf-8")
    return state


def save_recording_turn(call_id, pcm8, transcript, result, speaker):
    if not recording_enabled:
        return None
    state = recording_session(call_id)
    audio_bytes = int(pcm8.nbytes)
    if state["audio_bytes"] + audio_bytes > recording_max_bytes:
        return {"session_id": state["session_id"], "saved": False, "limit_reached": True}
    state["turns"] += 1
    state["audio_bytes"] += audio_bytes
    state["transcript_chars"] += len(transcript)
    turn_name = f"turn-{state['turns']:04d}"
    wav_path = state["path"] / f"{turn_name}.wav"
    with wave.open(str(wav_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(pcm8.astype("<i2", copy=False).tobytes())
    if transcript:
        with (state["path"] / "transcript.txt").open("a", encoding="utf-8") as target:
            target.write(f"[{speaker}/{result.get('detected_language') or 'und'}] {transcript.strip()}\n")
    private_metadata = {
        "turn": state["turns"], "audio_file": wav_path.name,
        "audio_duration_seconds": result["audio_duration_seconds"],
        "audio_sha256": result["audio_sha256"],
        "transcript_chars": len(transcript),
        "normalization_applied": result.get("normalization_applied", False),
        "raw_transcript_chars": result.get("transcript_chars"),
        "normalization_processing_ms": result.get("normalization_processing_ms"),
        "detected_language": result.get("detected_language"),
        "speaker": speaker,
        "processing_ms": result.get("processing_ms"),
    }
    with (state["path"] / "manifest.jsonl").open("a", encoding="utf-8") as target:
        target.write(json.dumps(private_metadata, ensure_ascii=False) + "\n")
    return {"session_id": state["session_id"], "saved": True,
            "turn": state["turns"], "audio_bytes": audio_bytes}


def finalize_call(call_id):
    # SIP endpoints commonly suppress RTP during silence. Flush the last
    # transcription turn on BYE because no trailing silent frames may arrive.
    for key in [key for key in buffers if key.startswith(call_id + ":")]:
        buffered = buffers.pop(key)
        buffered_event = buffered.get("event") or {}
        if (buffered["in_speech"] and buffered["speech_bytes"] >= min_utterance_bytes
                and buffered_event.get("service_mode") in {"transcribe", "bilingual_test"}):
            process_utterance(bytes(buffered["utterance"]), buffered_event,
                              buffered.get("received_at", time.time()), "call-ended")
    state = recordings.pop(call_id, None)
    if state:
        completed = {"completed_at": time.time(), "turns": state["turns"],
                     "audio_bytes": state["audio_bytes"],
                     "transcript_chars": state["transcript_chars"],
                     "retention_days": recording_retention_days}
        (state["path"] / "completed.json").write_text(
            json.dumps(completed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"AI recording_finalized session={state['session_id']} turns={state['turns']} "
              f"audio_bytes={state['audio_bytes']} transcript_chars={state['transcript_chars']}", flush=True)
    conversations.pop(call_id, None)
    reply_counts.pop(call_id, None)
    turn_counts.pop(call_id, None)


def process_events():
    while True:
        event = work.get()
        try:
            if event.get("control") == "end_call":
                finalize_call(event["call_id"])
            else:
                process_event(event)
        except Exception as exc:
            print(f"AI processing_failed type={type(exc).__name__} error={exc}", flush=True)
        finally:
            work.task_done()


def process_event(event):
    service_mode = event.get("service_mode", "observe")
    current_silence_bytes_required = (dialogue_silence_bytes_required
                                      if service_mode == "bilingual_test"
                                      else silence_bytes_required)
    current_max_utterance_bytes = (dialogue_max_utterance_bytes
                                   if service_mode == "bilingual_test"
                                   else max_utterance_bytes)
    if event.get("direction") != "caller_to_core" and service_mode != "bilingual_test":
        return
    received_at = event.get("received_at", time.time())
    encoded = event.get("audio_ulaw_b64", "")
    try:
        chunk = base64.b64decode(encoded, validate=True)
    except ValueError:
        return
    if event.get("codec") != "PCMU" or event.get("sample_rate_hz") != 8000 or not chunk:
        return
    if hashlib.sha256(chunk).hexdigest() != event.get("audio_sha256"):
        print("AI rejected audio hash mismatch", flush=True)
        return
    event_call_ids = event.get("call_ids") or []
    event_call_id = event_call_ids[0] if len(event_call_ids) == 1 else "unbound"
    # SSRC values may be reused by a UE across calls. Call-ID is therefore
    # part of the transient buffer key to prevent cross-dialog audio mixing.
    stream_key = f"{event_call_id}:{event.get('ssrc', 'unknown')}"
    now = time.time()
    expire_transient(now)
    if stream_key not in buffers and len(buffers) >= buffer_max:
        oldest = min(buffers, key=lambda key: buffers[key]["last_seen"])
        buffers.pop(oldest, None)
    state = buffers.setdefault(stream_key, {"utterance": bytearray(), "preroll": bytearray(),
                                             "speech_bytes": 0, "silence_bytes": 0,
                                             "in_speech": False, "last_seen": now})
    observed_at = event.get("observed_at")
    previous_observed_at = state.get("observed_at")
    if (service_mode == "bilingual_test" and state["in_speech"]
            and state["speech_bytes"] >= min_utterance_bytes
            and isinstance(observed_at, (int, float))
            and isinstance(previous_observed_at, (int, float))
            and observed_at - previous_observed_at >= dialogue_event_gap_seconds):
        # Silence-suppressing SIP clients send no RTP frames from which the VAD
        # could count silence. A gap between two batches is the media-level
        # equivalent and must close the previous phrase before the new one.
        process_utterance(bytes(state["utterance"]), state.get("event", event),
                          state.get("received_at", received_at), "stream-gap")
        state.update({"utterance": bytearray(), "preroll": bytearray(),
                      "speech_bytes": 0, "silence_bytes": 0, "in_speech": False})
    state["last_seen"] = now
    state["observed_at"] = observed_at
    state["received_at"] = received_at
    state["event"] = {key: value for key, value in event.items()
                      if key != "audio_ulaw_b64"}
    for offset in range(0, len(chunk), 160):
        frame = chunk[offset:offset + 160]
        if len(frame) < 160:
            continue
        voiced = frame_rms(frame) >= vad_rms
        if voiced:
            if not state["in_speech"]:
                state["utterance"].extend(state["preroll"])
                state["preroll"].clear()
                state["in_speech"] = True
            state["utterance"].extend(frame)
            state["speech_bytes"] += len(frame)
            state["silence_bytes"] = 0
        elif state["in_speech"]:
            state["utterance"].extend(frame)
            state["silence_bytes"] += len(frame)
        else:
            state["preroll"].extend(frame)
            del state["preroll"][:-preroll_bytes]

        end_reason = None
        if (state["in_speech"] and state["speech_bytes"] >= min_utterance_bytes
                and state["silence_bytes"] >= current_silence_bytes_required):
            end_reason = "silence"
        elif (state["in_speech"]
              and len(state["utterance"]) >= current_max_utterance_bytes):
            end_reason = "maximum-duration"
        if end_reason:
            ulaw = bytes(state["utterance"])
            state.update({"utterance": bytearray(), "preroll": bytearray(),
                          "speech_bytes": 0, "silence_bytes": 0, "in_speech": False})
            process_utterance(ulaw, event, received_at, end_reason)


def process_utterance(ulaw, event, received_at, end_reason):
    service_mode = event.get("service_mode", "observe")
    audio = decode_audio(ulaw)
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    started = time.perf_counter_ns()
    transcript = ""
    detected_language = None
    language_probability = None
    if model is not None and rms > 0.005:
        requested_language = None if service_mode == "bilingual_test" else (language or None)
        segments, info = model.transcribe(audio, language=requested_language, task="transcribe",
                                          beam_size=1, vad_filter=True,
                                          condition_on_previous_text=False)
        transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        detected_language = info.language
        language_probability = info.language_probability
    processed_at = time.time()
    result = {key: value for key, value in event.items()
              if key not in {"audio_sha256", "audio_ulaw_b64", "received_at"}}
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else None
    if call_id:
        turn_counts[call_id] = turn_counts.get(call_id, 0) + 1
    result.update({
        "backend_id": f"{backend}:{model_size}:{device}:{compute_type}",
        "model_revision": model_revision,
        "audio_sha256": hashlib.sha256(ulaw).hexdigest(),
        "audio_duration_seconds": len(ulaw) / 8000,
        "audio_rms": rms,
        "transcript_chars": len(transcript),
        "transcript_cyrillic_chars": cyrillic_chars(transcript),
        "detected_language": detected_language,
        "language_probability": language_probability,
        "received_at": received_at,
        "processed_at": processed_at,
        "utterance_end_reason": end_reason,
        "turn_index": turn_counts.get(call_id) if call_id else None,
        "service_mode": service_mode,
        "processing_ms": (time.perf_counter_ns() - started) / 1_000_000,
        "adapter_to_worker_ms": ((received_at - event["observed_at"]) * 1000
                                  if isinstance(event.get("observed_at"), (int, float)) else None),
    })
    if call_id and service_mode in {"transcribe", "bilingual_test"}:
        normalized_transcript = transcript
        if service_mode == "bilingual_test":
            recording = recording_session(call_id)
            source_key = event.get("source_stream_id") or str(event.get("ssrc"))
            speaker = recording["speakers"].setdefault(
                source_key, f"speaker_{len(recording['speakers']) + 1}")
        else:
            speaker = "caller"
        if transcript:
            try:
                normalized_transcript, normalization_ms = normalize_transcript(
                    transcript, detected_language)
                result.update({
                    "normalization_applied": True,
                    "normalization_llm_model": llm_model,
                    "normalization_processing_ms": normalization_ms,
                    "normalized_transcript_chars": len(normalized_transcript),
                    "normalized_transcript_cyrillic_chars": cyrillic_chars(normalized_transcript),
                })
                print(f"AI transcript_normalized model={llm_model} input_chars={len(transcript)} "
                      f"output_chars={len(normalized_transcript)} llm_ms={normalization_ms:.3f} "
                      f"calls={call_ids}", flush=True)
            except Exception as exc:
                # Fail closed for text persistence: keep the WAV so the turn can
                # be reprocessed, but never label raw STT output as normalized.
                normalized_transcript = ""
                result.update({"normalization_applied": False,
                               "normalization_error_type": type(exc).__name__})
                print(f"AI transcript_normalization_failed model={llm_model} "
                      f"type={type(exc).__name__} calls={call_ids}", flush=True)
        saved = save_recording_turn(call_id, decode_pcm8(ulaw), normalized_transcript,
                                    result, speaker)
        if saved:
            result.update({"recording_session_id": saved["session_id"],
                           "recording_saved": saved["saved"],
                           "recording_turn": saved.get("turn"),
                           "recording_limit_reached": saved.get("limit_reached", False)})
    if (transcript and call_id and service_mode in {"translate", "assistant"}
            and reply_counts.get(call_id, 0) < max_replies_per_call):
        try:
            reply, llm_ms = generate_reply(call_id, transcript, service_mode)
            if reply:
                latin_chars = sum(char.isascii() and char.isalpha() for char in reply)
                reply_cyrillic = cyrillic_chars(reply)
                if (service_mode == "translate"
                        and (latin_chars < translation_min_latin
                             or reply_cyrillic > translation_max_cyrillic)):
                    raise ValueError("translation output language mismatch")
                reply_voice = translation_voice if service_mode == "translate" else os.environ["TTS_VOICE"]
                deliver_reply(call_id, reply, reply_voice)
                reply_counts[call_id] = reply_counts.get(call_id, 0) + 1
                remember_turn(call_id, transcript, reply)
                while len(reply_counts) > buffer_max:
                    evicted = next(iter(reply_counts))
                    reply_counts.pop(evicted, None)
                    turn_counts.pop(evicted, None)
                    conversations.pop(evicted, None)
                result.update({"llm_model": llm_model, "llm_response_chars": len(reply),
                               "llm_response_cyrillic_chars": reply_cyrillic,
                               "llm_response_latin_chars": latin_chars,
                               "reply_voice": reply_voice,
                               "llm_processing_ms": llm_ms, "reply_delivered": True,
                               "reply_index": reply_counts[call_id]})
                print(f"AI reply_delivered model={llm_model} prompt_chars={len(transcript)} "
                      f"response_chars={len(reply)} llm_ms={llm_ms:.3f} calls={call_ids}", flush=True)
        except Exception as exc:
            result.update({"llm_model": llm_model, "reply_delivered": False,
                           "llm_error_type": type(exc).__name__})
            print(f"AI reply_failed model={llm_model} type={type(exc).__name__} calls={call_ids}", flush=True)
    with lock:
        events.append(result)
        expire_events(processed_at)
    print(f"AI utterance_processed backend={result['backend_id']} "
          f"audio_seconds={result['audio_duration_seconds']:.3f} rms={rms:.5f} "
          f"transcript_chars={len(transcript)} language={detected_language} "
          f"end={end_reason} calls={event.get('call_ids')}", flush=True)


class Api(BaseHTTPRequestHandler):
    def authorized(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {control_token}")

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204 if model is not None else 503); self.end_headers(); return
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        with lock:
            expire_events(time.time())
            body = json.dumps({"status": "ok" if model is not None else "loading",
                               "mode": "OBSERVE", "backend": backend, "model": model_size,
                               "model_revision": model_revision,
                               "device": device, "model_error": model_error,
                               "queue_depth": work.qsize(), "buffered_streams": len(buffers),
                               "active_conversations": len(conversations),
                               "events": events}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if self.path != "/observe":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > request_max_bytes:
            self.send_response(413); self.end_headers(); return
        try:
            event = json.loads(self.rfile.read(length))
            event["received_at"] = time.time()
            work.put_nowait(event)
            print(f"AI stream_received packets={event.get('packets')} audio={event.get('audio_bytes', 0)} "
                  f"calls={event.get('call_ids')}", flush=True)
        except (json.JSONDecodeError, TypeError):
            self.send_response(400); self.end_headers(); return
        except queue.Full:
            self.send_response(429); self.end_headers(); return
        self.send_response(202); self.end_headers()

    def do_DELETE(self):
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        if not self.path.startswith("/calls/"):
            self.send_response(404); self.end_headers(); return
        call_id = urllib.parse.unquote(self.path.removeprefix("/calls/"))
        if not call_id_pattern.fullmatch(call_id):
            self.send_response(400); self.end_headers(); return
        try:
            work.put_nowait({"control": "end_call", "call_id": call_id})
        except queue.Full:
            self.send_response(429); self.end_headers(); return
        self.send_response(202); self.end_headers()

    def log_message(self, *_):
        pass


threading.Thread(target=load_model, daemon=True).start()
threading.Thread(target=process_events, daemon=True).start()
port = int(os.environ["AI_WORKER_PORT"])
print(f"AI Worker listening :{port} mode=OBSERVE backend={backend} model={model_size} device={device}", flush=True)
ThreadingHTTPServer(("0.0.0.0", port), Api).serve_forever()
