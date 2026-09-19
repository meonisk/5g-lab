"""Короткие HTTP-маршруты: проверить вход, вызвать действие, вернуть статус."""

import ipaddress

from flask import abort, jsonify
from lab_common.http import create_api, json_object, require, valid_call_id

from . import calls, runtime
from .media import enqueue_audio

api = create_api(__name__, runtime.control_token)


@api.get("/healthz")
def health():
    return "", 204


@api.get("/status")
def status():
    with runtime.lock:
        return jsonify(
            status="ok",
            mode="TERMINATE",
            calls=runtime.calls,
            events=runtime.events,
            reply_queue_depths={
                cid: pending.qsize() for cid, pending in runtime.reply_queues.items()
            },
        )


@api.post("/calls")
def start_call():
    data = json_object()
    call_id = data.get("call_id")
    mode = data.get("service_mode")
    port = data.get("remote_port")
    require(valid_call_id(call_id))
    require(isinstance(mode, str) and mode in runtime.allowed_service_modes)
    require(type(port) is int and runtime.rtp_port_min <= port <= runtime.rtp_port_max)
    try:
        address = str(ipaddress.ip_address(data.get("remote_ip", "")))
    except ValueError:
        abort(400)
    # Ответы разрешено отправлять только в наш RTPengine, не на произвольный адрес.
    require(address == runtime.rtpengine_ip)
    require(calls.start_call(call_id, address, port, mode), 429)
    return "", 202


@api.post("/calls/<call_id>/reply")
def reply(call_id):
    require(valid_call_id(call_id))
    data = json_object()
    require(isinstance(data.get("text"), str))
    text = " ".join(data["text"].split())
    voice = data.get("voice", runtime.tts_voice)
    reply_id = data.get("reply_id")
    require(bool(text) and len(text) <= runtime.reply_max_chars)
    require(not any(ord(char) < 32 for char in text))
    require(isinstance(voice, str) and voice in runtime.allowed_tts_voices)
    require(
        reply_id is None
        or (isinstance(reply_id, str) and runtime.reply_id_pattern.fullmatch(reply_id) is not None)
    )
    with runtime.lock:
        require(call_id in runtime.calls, 404)
    require(enqueue_audio(call_id, text, "llm_reply", voice, reply_id), 429)
    return "", 202


@api.delete("/calls/<call_id>")
def end_call(call_id):
    require(valid_call_id(call_id))
    calls.end_call(call_id)
    return "", 204
