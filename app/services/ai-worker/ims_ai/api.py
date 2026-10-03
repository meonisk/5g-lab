"""HTTP принимает работу в очередь; распознавание не выполняется в запросе."""

import queue
import time

from flask import abort, jsonify
from lab_common.http import create_api, json_object, require, valid_call_id

from . import runtime, settings
from .maintenance import expire_events

api = create_api(__name__, runtime.control_token, settings.request_max_bytes)


@api.get("/healthz")
def health():
    return "", 204 if runtime.model is not None else 503


@api.get("/events")
def events():
    """Отдаём метаданные: текст и аудио остаются внутри конвейера."""
    with runtime.lock:
        expire_events(time.time())
        return jsonify(
            status="ok" if runtime.model is not None else "loading",
            mode="OBSERVE",
            backend=settings.backend,
            model=settings.model_size,
            model_revision=settings.model_revision,
            device=settings.device,
            streaming_enabled=settings.streaming_enabled,
            translation_backend=settings.translation_backend,
            transcript_normalization=settings.transcript_normalization,
            model_error=runtime.model_error,
            queue_depth=runtime.work.qsize(),
            media_queue_depth=runtime.work.qsize(),
            utterance_queue_depth=runtime.utterance_work.qsize(),
            processing_workers=settings.processing_workers,
            pending_utterances=sum(runtime.pending_utterances.values()),
            buffered_streams=len(runtime.buffers),
            active_conversations=len(runtime.conversations),
            active_calls=len(runtime.active_calls),
            events=runtime.events,
        )


def enqueue(event: dict):
    try:
        runtime.work.put_nowait(event)
    except queue.Full:
        abort(429)
    return "", 202


@api.post("/observe")
def observe():
    event = json_object()
    # Управляющее событие создаёт только DELETE /calls, не аудиозапрос.
    require("control" not in event)
    event["received_at"] = time.time()
    response = enqueue(event)
    # Метаданные приёма нужны для проверки OBSERVE даже на тихом аудиоканале.
    print(
        f"AI stream_received packets={event.get('packets')} audio={event.get('audio_bytes', 0)} "
        f"calls={event.get('call_ids')}",
        flush=True,
    )
    return response


@api.post("/calls")
def register_call():
    data = json_object(4096)
    call_id = data.get("call_id")
    mode = data.get("service_mode")
    require(valid_call_id(call_id))
    require(isinstance(mode, str) and mode in settings.service_modes)
    with runtime.lock:
        runtime.active_calls[call_id] = {"service_mode": mode, "started_at": time.time()}
    return "", 202


@api.delete("/calls/<call_id>")
def end_call(call_id):
    require(valid_call_id(call_id))
    # BYE идёт через ту же очередь: принятый хвост аудио обрабатывается первым.
    return enqueue({"control": "end_call", "call_id": call_id})
