"""HTTP принимает работу в очередь; распознавание не выполняется в запросе."""

import queue
import time

from flask import abort, jsonify
from lab_common.http import create_api, json_object, require, valid_call_id

from . import runtime, settings
from .maintenance import expire_events
from .recording import add_recording_legs

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


PAIR_LANGUAGES = {"ru", "en"}


@api.post("/pairs")
def register_pair():
    """SIP AS сообщает пару ног B2BUA: перевод каждой ноги уходит в ногу партнёра."""
    legs = json_object(4096).get("legs")
    require(isinstance(legs, list) and len(legs) == 2)
    require(
        all(
            isinstance(leg, dict)
            and valid_call_id(leg.get("call_id"))
            and leg.get("language") in PAIR_LANGUAGES
            for leg in legs
        )
    )
    first, second = legs
    require(first["call_id"] != second["call_id"] and first["language"] != second["language"])
    with runtime.lock:
        runtime.pairs[first["call_id"]] = second["call_id"]
        runtime.pairs[second["call_id"]] = first["call_id"]
    print(f"AI pair_registered calls={[first['call_id'], second['call_id']]}", flush=True)
    return "", 202


@api.delete("/pairs/<call_id>")
def remove_pair(call_id):
    require(valid_call_id(call_id))
    with runtime.lock:
        partner = runtime.pairs.pop(call_id, None)
        if partner is not None and runtime.pairs.get(partner) == call_id:
            runtime.pairs.pop(partner)
    return "", 204


SPEAKERS = {"caller", "callee"}


@api.post("/recordings")
def register_recording():
    """SIP AS (record + translate) просит писать обе ноги звонка в одну запись."""
    data = json_object(4096)
    session_call_id = data.get("session_call_id")
    legs = data.get("legs")
    require(valid_call_id(session_call_id))
    require(isinstance(legs, list) and 1 <= len(legs) <= 2)
    require(
        all(
            isinstance(leg, dict)
            and valid_call_id(leg.get("call_id"))
            and leg.get("speaker") in SPEAKERS
            for leg in legs
        )
    )
    with runtime.lock:
        add_recording_legs(session_call_id, [(leg["call_id"], leg["speaker"]) for leg in legs])
    print(f"AI recording_registered legs={len(legs)}", flush=True)
    return "", 202
