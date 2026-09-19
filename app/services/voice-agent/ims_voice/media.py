"""Синтезирует речь, отправляет RTP и принимает голос абонента."""

import queue
import struct
import time
from dataclasses import dataclass

from . import runtime
from .audio import synthesize, ulaw_rms

PCMU_FRAME_BYTES = 160
PCMU_FRAME_SECONDS = 0.02
RTP_HEADER_BYTES = 12
RTP_VERSION = 2
PCMU_PAYLOAD_TYPE = 0


@dataclass
class PlaybackState:
    """Изменяемые RTP-счётчики одной операции воспроизведения."""

    generation: int
    sequence: int
    timestamp: int
    destination: tuple[str, int]
    ssrc: int
    packets_sent: int = 0
    interrupted: bool = False


def elapsed_ms(started_at_ns: int) -> float:
    return (time.perf_counter_ns() - started_at_ns) / 1_000_000


def begin_playback(call_id: str) -> PlaybackState | None:
    """Зарезервировать новое поколение TTS и скопировать RTP-адрес звонка."""
    with runtime.lock:
        call = runtime.calls.get(call_id)
        if call is None:
            return None

        call["tts_generation"] += 1
        call["tts_active"] = True

        return PlaybackState(
            generation=call["tts_generation"],
            sequence=call["seq"],
            timestamp=call["timestamp"],
            destination=(call["remote_ip"], call["remote_port"]),
            ssrc=call["ssrc"],
        )


def playback_is_current(call_id: str, generation: int) -> bool:
    """Поколение меняется при новом ответе, BYE или barge-in абонента."""
    with runtime.lock:
        call = runtime.calls.get(call_id)
        return call is not None and call["tts_generation"] == generation


def send_rtp_frames(call_id: str, audio_payload: bytes, playback: PlaybackState) -> None:
    """Отправить PCMU в реальном времени, проверяя прерывание между кадрами."""
    for frame_offset in range(0, len(audio_payload), PCMU_FRAME_BYTES):
        if not playback_is_current(call_id, playback.generation):
            playback.interrupted = True
            return

        frame = audio_payload[frame_offset : frame_offset + PCMU_FRAME_BYTES].ljust(
            PCMU_FRAME_BYTES, b"\xff"
        )
        rtp_header = struct.pack(
            "!BBHII",
            0x80,
            PCMU_PAYLOAD_TYPE,
            playback.sequence,
            playback.timestamp,
            playback.ssrc,
        )
        runtime.rtp.sendto(rtp_header + frame, playback.destination)

        playback.sequence = (playback.sequence + 1) & 0xFFFF
        playback.timestamp = (playback.timestamp + PCMU_FRAME_BYTES) & 0xFFFFFFFF
        playback.packets_sent += 1

        # Без pacing весь WAV попадёт в UDP быстрее, чем его сможет проиграть UE.
        time.sleep(PCMU_FRAME_SECONDS)


def finish_playback(
    call_id: str,
    playback: PlaybackState,
    reason: str,
    voice: str,
    reply_id: str | None,
    synthesis_ms: float,
    playout_ms: float,
    total_ms: float,
) -> None:
    """Сохранить RTP-счётчики и безопасные метрики без текста ответа."""
    with runtime.lock:
        current_call = runtime.calls.get(call_id)
        if current_call is not None:
            current_call["seq"] = playback.sequence
            current_call["timestamp"] = playback.timestamp

            if current_call["tts_generation"] == playback.generation:
                current_call["tts_active"] = False

        event_name = "tts_interrupted" if playback.interrupted else "tts_sent"
        runtime.events.append(
            {
                "call_id": call_id,
                "event": event_name,
                "reason": reason,
                "backend": runtime.tts_backend,
                "voice": voice,
                "packets": playback.packets_sent,
                "at": time.time(),
                "reply_id": reply_id,
                "synthesis_ms": synthesis_ms,
                "rtp_playout_ms": playout_ms,
                "tts_total_ms": total_ms,
            }
        )
        del runtime.events[: -runtime.event_retention]


def send_audio(
    call_id: str,
    text: str,
    reason: str,
    voice: str,
    reply_id: str | None = None,
) -> None:
    """Синтезировать и воспроизвести один элемент очереди звонка."""
    if voice not in runtime.allowed_tts_voices:
        return

    total_started_at = time.perf_counter_ns()
    synthesis_started_at = time.perf_counter_ns()
    audio_payload = synthesize(text, voice)
    synthesis_ms = elapsed_ms(synthesis_started_at)

    playback = begin_playback(call_id)
    if playback is None:
        return

    playout_started_at = time.perf_counter_ns()
    send_rtp_frames(call_id, audio_payload, playback)

    playout_ms = elapsed_ms(playout_started_at)
    total_ms = elapsed_ms(total_started_at)
    finish_playback(
        call_id,
        playback,
        reason,
        voice,
        reply_id,
        synthesis_ms,
        playout_ms,
        total_ms,
    )

    delivery_state = "interrupted" if playback.interrupted else "sent"
    print(
        f"VOICE tts call_id={call_id} reason={reason} state={delivery_state} "
        f"backend={runtime.tts_backend} voice={voice} packets={playback.packets_sent}",
        flush=True,
    )


def enqueue_audio(
    call_id: str,
    text: str,
    reason: str,
    voice: str,
    reply_id: str | None = None,
) -> bool:
    """Добавить речь без блокировки HTTP и без замены предыдущего ответа."""
    with runtime.lock:
        playback_queue = runtime.reply_queues.get(call_id)

    if playback_queue is None:
        return False

    try:
        playback_queue.put_nowait((text, reason, voice, reply_id))
        return True
    except queue.Full:
        return False


def play_queued_audio(call_id: str, playback_queue: queue.Queue) -> None:
    """Сохранить слышимый порядок ответов одного звонка."""
    while True:
        with runtime.lock:
            call_is_active = runtime.reply_queues.get(call_id) is playback_queue

        if not call_is_active:
            return

        try:
            playback_item = playback_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            send_audio(call_id, *playback_item)
        except Exception as error:
            # Ошибка одного синтеза не должна навсегда остановить очередь звонка.
            print(
                f"VOICE synthesis_failed type={type(error).__name__}",
                flush=True,
            )
        finally:
            playback_queue.task_done()


def extract_pcmu_payload(packet: bytes) -> bytes | None:
    """Принять только минимальный RTP v2 с payload type 0 (PCMU)."""
    if len(packet) < RTP_HEADER_BYTES:
        return None

    rtp_version = packet[0] >> 6
    payload_type = packet[1] & 0x7F
    if rtp_version != RTP_VERSION or payload_type != PCMU_PAYLOAD_TYPE:
        return None

    return packet[RTP_HEADER_BYTES:]


def update_call_from_audio(call: dict, audio_rms: float, now: float) -> bool:
    """Обновить VAD звонка и вернуть True, когда нужен фиксированный ответ."""
    call["received_packets"] += 1

    if audio_rms >= runtime.vad_rms:
        # Перевод собеседника должен прозвучать целиком, даже при одновременной
        # речи. Прерывание ответа голосом остаётся только у обычного помощника.
        interpreter_call = call.get("service_mode") in {"interpret_ru", "interpret_en"}
        if call["tts_active"] and not interpreter_call:
            call["tts_generation"] += 1
            call["tts_active"] = False

        call["speech_seen"] = True
        call["last_voice"] = now
        return False

    silence_completed = (
        call["speech_seen"]
        and not call["replied"]
        and now - call["last_voice"] >= runtime.silence_seconds
    )
    if not runtime.llm_mode and silence_completed:
        call["replied"] = True
        return True

    return False


def calls_ready_for_fixed_reply(
    sender: tuple[str, int],
    audio_payload: bytes,
) -> list[str]:
    """Найти звонок по адресу RTPengine и обработать один входящий кадр."""
    audio_rms = ulaw_rms(audio_payload)
    now = time.time()
    ready_call_ids = []

    with runtime.lock:
        for call_id, call in runtime.calls.items():
            expected_sender = (call["remote_ip"], call["remote_port"])
            if sender != expected_sender:
                continue

            if update_call_from_audio(call, audio_rms, now):
                ready_call_ids.append(call_id)

    return ready_call_ids


def receive_audio() -> None:
    """Непрерывно принимать RTP; тяжёлая обработка выполняется вне этого цикла."""
    while True:
        packet, sender = runtime.rtp.recvfrom(4096)
        audio_payload = extract_pcmu_payload(packet)
        if audio_payload is None:
            continue

        ready_call_ids = calls_ready_for_fixed_reply(sender, audio_payload)
        for call_id in ready_call_ids:
            enqueue_audio(
                call_id,
                runtime.reply_text,
                "vad_reply",
                runtime.tts_voice,
            )
