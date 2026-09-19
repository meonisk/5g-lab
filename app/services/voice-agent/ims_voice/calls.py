"""Жизненный цикл звонка: состояние, одна очередь озвучки и один её потребитель."""

import hashlib
import queue
import threading
import time

from . import runtime


def start_call(call_id: str, remote_ip: str, remote_port: int, mode: str) -> bool:
    """Повторное SIP-уведомление не создаёт второй поток и не сбрасывает RTP."""
    from .media import enqueue_audio, play_queued_audio

    with runtime.lock:
        if call_id in runtime.calls:
            return True
        if len(runtime.calls) >= runtime.max_calls:
            return False
        runtime.calls[call_id] = {
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "ssrc": int.from_bytes(hashlib.sha256(call_id.encode()).digest()[:4], "big"),
            "seq": 1,
            "timestamp": 0,
            "received_packets": 0,
            "speech_seen": False,
            "last_voice": 0,
            "replied": False,
            "tts_generation": 0,
            "tts_active": False,
            "service_mode": mode,
            "started_at": time.time(),
        }
        pending = queue.Queue(maxsize=runtime.reply_queue_max)
        runtime.reply_queues[call_id] = pending

    # Приветствие ставится первым, до приёма ответов AI.
    greetings = {
        "transcribe": (runtime.transcriber_greeting, runtime.tts_voice),
        "interpret_ru": (runtime.interpreter_ru_greeting, runtime.tts_voice),
        "interpret_en": (runtime.interpreter_en_greeting, runtime.tts_translation_voice),
    }
    text, voice = greetings.get(mode, (runtime.greeting, runtime.tts_voice))
    enqueue_audio(call_id, text, "greeting", voice)
    threading.Thread(target=play_queued_audio, args=(call_id, pending), daemon=True).start()
    print(f"VOICE call_started call_id={call_id} service={mode}", flush=True)
    return True


def end_call(call_id: str) -> None:
    """Удаление очереди останавливает её worker, в том числе при переполнении."""
    with runtime.lock:
        call = runtime.calls.pop(call_id, None)
        runtime.reply_queues.pop(call_id, None)
    received = call["received_packets"] if call else 0
    print(f"VOICE call_ended call_id={call_id} received={received}", flush=True)


def expire_calls():
    while True:
        time.sleep(min(30, max(1, runtime.call_timeout)))
        cutoff = time.time() - runtime.call_timeout
        with runtime.lock:
            expired = [cid for cid, call in runtime.calls.items() if call["started_at"] < cutoff]
        for call_id in expired:
            end_call(call_id)
