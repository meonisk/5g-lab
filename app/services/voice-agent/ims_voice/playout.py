"""Очередь озвучки одного звонка: синтез следующего ответа идёт, пока звучит текущий.

Два потока на звонок. Синтезатор берёт текст из очереди звонка и готовит звук, плеер
отправляет готовый звук в RTP строго по порядку. Так время синтеза (300–800 мс) не
добавляется к задержке ответа, который ждал своей очереди.

Если в момент синтеза что-то ещё звучит или ждёт, перевод синтезируется быстрее
(VOICE_AGENT_CATCHUP_LENGTH_FACTOR, 0.85 — на 15% короче): озвучка догоняет речь
собеседника, и очередь не растёт к концу длинной реплики.
"""

import queue
import threading
import time
from dataclasses import dataclass

from . import runtime
from .audio import backend_for, synthesize
from .media import begin_playback, elapsed_ms, finish_playback, send_rtp_frames

CATCH_UP_REASONS = {"llm_reply"}


@dataclass
class PreparedAudio:
    payload: bytes
    reason: str
    voice: str
    reply_id: str | None
    synthesis_ms: float
    length_factor: float
    started_ns: int


def prepare_audio(text, reason, voice, reply_id=None, catch_up=False):
    """Синтез одного элемента очереди; None — голос не разрешён."""
    if voice not in runtime.allowed_tts_voices:
        return None
    started_ns = time.perf_counter_ns()
    factor = runtime.catchup_length_factor if catch_up and reason in CATCH_UP_REASONS else 1.0
    payload = synthesize(text, voice, factor)
    return PreparedAudio(payload, reason, voice, reply_id, elapsed_ms(started_ns), factor,
                         started_ns)  # fmt: skip


def play_prepared(call_id: str, item: PreparedAudio) -> None:
    playback = begin_playback(call_id)
    if playback is None:
        return
    playout_started_at = time.perf_counter_ns()
    send_rtp_frames(call_id, item.payload, playback)
    finish_playback(
        call_id,
        playback,
        item.reason,
        item.voice,
        item.reply_id,
        item.synthesis_ms,
        elapsed_ms(playout_started_at),
        elapsed_ms(item.started_ns),
        item.length_factor,
    )
    state = "interrupted" if playback.interrupted else "sent"
    print(
        f"VOICE tts call_id={call_id} reason={item.reason} state={state} "
        f"backend={backend_for(item.voice)} voice={item.voice} packets={playback.packets_sent} "
        f"length_factor={item.length_factor}",
        flush=True,
    )


def call_is_active(call_id: str, playback_queue: queue.Queue) -> bool:
    with runtime.lock:
        return runtime.reply_queues.get(call_id) is playback_queue


def playback_busy(call_id: str, ready: queue.Queue) -> bool:
    """Что-то звучит или уже ждёт плеера: следующий ответ нужно ускорить."""
    with runtime.lock:
        call = runtime.calls.get(call_id)
        playing = bool(call and call.get("tts_active"))
    return playing or not ready.empty()


def play_ready_audio(call_id: str, playback_queue: queue.Queue, ready: queue.Queue) -> None:
    while call_is_active(call_id, playback_queue):
        try:
            item = ready.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            play_prepared(call_id, item)
        except Exception as error:
            print(f"VOICE playback_failed type={type(error).__name__}", flush=True)


def play_queued_audio(call_id: str, playback_queue: queue.Queue) -> None:
    """Синтезатор звонка; сам запускает плеер. Оба заканчиваются вместе со звонком."""
    ready = queue.Queue(maxsize=1)
    threading.Thread(
        target=play_ready_audio, args=(call_id, playback_queue, ready), daemon=True
    ).start()
    while call_is_active(call_id, playback_queue):
        try:
            text, reason, voice, reply_id = playback_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            item = prepare_audio(text, reason, voice, reply_id, playback_busy(call_id, ready))
            while item and call_is_active(call_id, playback_queue):
                try:
                    ready.put(item, timeout=0.5)
                    break
                except queue.Full:
                    continue
        except Exception as error:
            # Ошибка одного синтеза не должна навсегда остановить очередь звонка.
            print(f"VOICE synthesis_failed type={type(error).__name__}", flush=True)
        finally:
            playback_queue.task_done()
