"""RTP sending, interruption, receiving, and call expiry."""

import queue
import struct
import time

from . import runtime
from .audio import synthesize, ulaw_rms


def send_audio(call_id, text, reason, voice, reply_id=None):
    """Synthesize and play one item; a per-call worker preserves order."""
    if voice not in runtime.allowed_tts_voices:
        return
    with runtime.lock:
        call = runtime.calls.get(call_id)
        if call:
            call["tts_generation"] += 1
            generation = call["tts_generation"]
    if not call:
        return
    total_started = time.perf_counter_ns()
    synthesis_started = time.perf_counter_ns()
    payload = synthesize(text, voice)
    synthesis_ms = (time.perf_counter_ns() - synthesis_started) / 1_000_000
    interrupted = False
    with runtime.lock:
        call = runtime.calls.get(call_id)
        if not call or call["tts_generation"] != generation:
            return
        call["tts_active"] = True
        seq = call["seq"]
        timestamp = call["timestamp"]
        remote = (call["remote_ip"], call["remote_port"])
        ssrc = call["ssrc"]
    sent = 0
    playout_started = time.perf_counter_ns()
    for offset in range(0, len(payload), 160):
        with runtime.lock:
            current = runtime.calls.get(call_id)
            if not current or current["tts_generation"] != generation:
                interrupted = True
                break
        frame = payload[offset : offset + 160].ljust(160, b"\xff")
        header = struct.pack("!BBHII", 0x80, 0, seq, timestamp, ssrc)
        runtime.rtp.sendto(header + frame, remote)
        seq = (seq + 1) & 0xFFFF
        timestamp = (timestamp + 160) & 0xFFFFFFFF
        sent += 1
        time.sleep(0.02)
    with runtime.lock:
        current = runtime.calls.get(call_id)
        if current:
            current["seq"] = seq
            current["timestamp"] = timestamp
            if current["tts_generation"] == generation:
                current["tts_active"] = False
        event = {
            "call_id": call_id,
            "event": "tts_interrupted" if interrupted else "tts_sent",
            "reason": reason,
            "backend": runtime.tts_backend,
            "voice": voice,
            "packets": sent,
            "at": time.time(),
            "reply_id": reply_id,
            "synthesis_ms": synthesis_ms,
            "rtp_playout_ms": (time.perf_counter_ns() - playout_started) / 1_000_000,
            "tts_total_ms": (time.perf_counter_ns() - total_started) / 1_000_000,
        }
        runtime.events.append(event)
        del runtime.events[: -runtime.event_retention]
    state = "interrupted" if interrupted else "sent"
    print(
        f"VOICE tts call_id={call_id} reason={reason} state={state} backend={runtime.tts_backend} "
        f"voice={voice} packets={sent}",
        flush=True,
    )


def enqueue_audio(call_id, text, reason, voice, reply_id=None):
    """Append speech without blocking HTTP or replacing an earlier reply."""
    with runtime.lock:
        reply_queue = runtime.reply_queues.get(call_id)
    if not reply_queue:
        return False
    try:
        reply_queue.put_nowait((text, reason, voice, reply_id))
        return True
    except queue.Full:
        return False


def play_queued_audio(call_id, reply_queue):
    """Preserve audible turn order while AI work continues in parallel."""
    while True:
        item = reply_queue.get()
        try:
            if item is None:
                return
            send_audio(call_id, *item)
        finally:
            reply_queue.task_done()


def receive_audio():
    while True:
        packet, peer = runtime.rtp.recvfrom(4096)
        if len(packet) < 12 or packet[0] >> 6 != 2 or packet[1] & 0x7F != 0:
            continue
        payload = packet[12:]
        rms = ulaw_rms(payload)
        now = time.time()
        responses = []
        with runtime.lock:
            for call_id, call in runtime.calls.items():
                if peer != (call["remote_ip"], call["remote_port"]):
                    continue
                call["received_packets"] += 1
                if rms >= runtime.vad_rms:
                    if call["tts_active"]:
                        call["tts_generation"] += 1
                        call["tts_active"] = False
                    call["speech_seen"] = True
                    call["last_voice"] = now
                elif (
                    not runtime.llm_mode
                    and call["speech_seen"]
                    and not call["replied"]
                    and now - call["last_voice"] >= runtime.silence_seconds
                ):
                    call["replied"] = True
                    responses.append(call_id)
        for call_id in responses:
            enqueue_audio(call_id, runtime.reply_text, "vad_reply", runtime.tts_voice)


def expire_calls():
    while True:
        time.sleep(min(30, max(1, runtime.call_timeout)))
        cutoff = time.time() - runtime.call_timeout
        with runtime.lock:
            expired = [
                (call_id, call["received_packets"])
                for call_id, call in runtime.calls.items()
                if call["started_at"] < cutoff
            ]
            for call_id, _ in expired:
                runtime.calls.pop(call_id, None)
                reply_queue = runtime.reply_queues.pop(call_id, None)
                if reply_queue:
                    try:
                        reply_queue.put_nowait(None)
                    except queue.Full:
                        pass
        for call_id, received in expired:
            print(f"VOICE call_expired call_id={call_id} received={received}", flush=True)
