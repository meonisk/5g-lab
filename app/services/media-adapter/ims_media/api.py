"""Сессии наблюдения: Call-ID и порты без SIP-идентичностей абонентов."""

import base64
import re
import threading
from urllib.parse import quote

from flask import abort, jsonify
from lab_common.http import create_api, json_object, request_json, require, valid_call_id

from . import runtime
from .rtpengine import play_media

api = create_api(__name__, runtime.control_token)


def notify_worker(method, path, payload=None):
    """Отказ AI не должен разрывать обычный абонентский звонок."""
    try:
        request_json(
            method,
            runtime.worker_base_url + path,
            payload=payload,
            token=runtime.control_token,
        )
    except Exception as exc:
        print(f"MEDIA worker unavailable type={type(exc).__name__}", flush=True)


def start_worker_call(call_id, service_mode):
    notify_worker("POST", "/calls", {"call_id": call_id, "service_mode": service_mode})


def end_worker_call(call_id):
    notify_worker("DELETE", "/calls/" + quote(call_id, safe=""))


@api.get("/healthz")
def health():
    return "", 204


@api.get("/sessions")
def sessions():
    with runtime.lock:
        return jsonify(status="ok", mode="OBSERVE", sessions=list(runtime.sessions))


@api.post("/sessions")
def start_session():
    incoming = json_object()
    call_id = incoming.get("call_id")
    mode = incoming.get("service_mode", "observe")
    port = incoming.get("rtpengine_port")
    require(valid_call_id(call_id))
    require(isinstance(mode, str) and mode in runtime.allowed_service_modes)
    require(
        port is None
        or (type(port) is int and runtime.port_min <= port <= runtime.port_max and port % 2 == 0)
    )
    observed_at = incoming.get("observed_at", 0)
    require(type(observed_at) in {int, float})
    # Копируем только разрешённые поля, даже если вызывающий прислал лишнее.
    with runtime.lock:
        runtime.sessions[call_id] = {
            "call_id": call_id,
            "observed_at": observed_at,
            "service_mode": mode,
            "rtpengine_port": port,
        }
    threading.Thread(target=start_worker_call, args=(call_id, mode), daemon=True).start()
    print(f"MEDIA session call_id={call_id} service={mode} relay_port={port}", flush=True)
    return "", 202


@api.delete("/sessions/<call_id>")
def end_session(call_id):
    require(valid_call_id(call_id))
    with runtime.lock:
        removed = runtime.sessions.pop(call_id, None)
    if removed:
        threading.Thread(target=end_worker_call, args=(call_id,), daemon=True).start()
    print(f"MEDIA session_ended call_id={call_id} existed={removed is not None}", flush=True)
    return "", 204


TAG = re.compile(r"^[A-Za-z0-9_.+~-]{1,64}$")


def fetch_announcement(text, voice):
    """WAV уведомления синтезирует Voice Agent: голоса и TTS живут только там."""
    data = request_json(
        "POST",
        runtime.voice_agent_url + "/announcements",
        payload={"text": text, "voice": voice},
        token=runtime.control_token,
        timeout=30,
    )
    return base64.b64decode(data["wav_base64"])


@api.post("/sessions/<call_id>/announce")
def announce(call_id):
    """Уведомление о записи каждой стороне звонка без MRF: RTPengine play media по SIP tag."""
    require(valid_call_id(call_id))
    parties = json_object(8192).get("parties")
    require(isinstance(parties, list) and 1 <= len(parties) <= 2)
    require(
        all(
            isinstance(party, dict)
            and isinstance(party.get("tag"), str)
            and TAG.fullmatch(party["tag"]) is not None
            and isinstance(party.get("text"), str)
            and isinstance(party.get("voice"), str)
            for party in parties
        )
    )
    try:
        for party in parties:
            wav = fetch_announcement(party["text"], party["voice"])
            play_media(call_id, party["tag"], wav)
    except Exception as exc:
        print(f"MEDIA announce_failed call_id={call_id} type={type(exc).__name__}", flush=True)
        abort(502)
    print(f"MEDIA announced call_id={call_id} parties={len(parties)}", flush=True)
    return "", 204
