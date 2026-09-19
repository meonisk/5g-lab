"""Authenticated call lifecycle and reply HTTP API."""

import hashlib
import hmac
import ipaddress
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

from . import runtime
from .media import send_audio


class Api(BaseHTTPRequestHandler):
    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {runtime.control_token}")

    def reject_unauthorized(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", "Bearer")
        self.end_headers()

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204)
            self.end_headers()
            return
        if self.path != "/status":
            self.send_response(404)
            self.end_headers()
            return
        if not self.authorized():
            self.reject_unauthorized()
            return
        with runtime.lock:
            body = json.dumps(
                {
                    "status": "ok",
                    "mode": "TERMINATE",
                    "calls": runtime.calls,
                    "events": runtime.events,
                }
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.authorized():
            self.reject_unauthorized()
            return
        if self.path.startswith("/calls/") and self.path.endswith("/reply"):
            encoded_call_id = self.path.removeprefix("/calls/").removesuffix("/reply").rstrip("/")
            call_id = urllib.parse.unquote(encoded_call_id)
            length = int(self.headers.get("Content-Length", "0"))
            if not runtime.call_id_pattern.fullmatch(call_id) or length < 2 or length > 4096:
                self.send_response(400)
                self.end_headers()
                return
            try:
                data = json.loads(self.rfile.read(length))
                text = " ".join(data["text"].split())
                voice = data.get("voice", runtime.tts_voice)
            except (TypeError, KeyError, json.JSONDecodeError):
                self.send_response(400)
                self.end_headers()
                return
            if (
                not text
                or len(text) > runtime.reply_max_chars
                or any(ord(char) < 32 for char in text)
                or voice not in runtime.allowed_tts_voices
            ):
                self.send_response(400)
                self.end_headers()
                return
            with runtime.lock:
                if call_id not in runtime.calls:
                    self.send_response(404)
                    self.end_headers()
                    return
            threading.Thread(
                target=send_audio, args=(call_id, text, "llm_reply", voice), daemon=True
            ).start()
            self.send_response(202)
            self.end_headers()
            return
        if self.path != "/calls":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 4096:
            self.send_response(413)
            self.end_headers()
            return
        try:
            data = json.loads(self.rfile.read(length))
            call_id = data["call_id"]
            remote_ip = str(ipaddress.ip_address(data["remote_ip"]))
            remote_port = int(data["remote_port"])
            service_mode = data["service_mode"]
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.send_response(400)
            self.end_headers()
            return
        if (
            not runtime.call_id_pattern.fullmatch(call_id)
            or service_mode not in runtime.allowed_service_modes
            or remote_ip != runtime.rtpengine_ip
            or not runtime.rtp_port_min <= remote_port <= runtime.rtp_port_max
        ):
            self.send_response(400)
            self.end_headers()
            return
        with runtime.lock:
            if call_id not in runtime.calls and len(runtime.calls) >= runtime.max_calls:
                self.send_response(429)
                self.end_headers()
                return
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
                "service_mode": service_mode,
                "started_at": time.time(),
            }
            runtime.send_locks.setdefault(call_id, threading.Lock())
        print(
            f"VOICE call_started call_id={call_id} service={service_mode} "
            f"remote={data['remote_ip']}:{data['remote_port']}",
            flush=True,
        )
        prompt = runtime.transcriber_greeting if service_mode == "transcribe" else runtime.greeting
        threading.Thread(
            target=send_audio,
            args=(call_id, prompt, "greeting", runtime.tts_voice),
            daemon=True,
        ).start()
        self.send_response(202)
        self.end_headers()

    def do_DELETE(self):
        if not self.authorized():
            self.reject_unauthorized()
            return
        if not self.path.startswith("/calls/"):
            self.send_response(404)
            self.end_headers()
            return
        call_id = urllib.parse.unquote(self.path.removeprefix("/calls/"))
        if not runtime.call_id_pattern.fullmatch(call_id):
            self.send_response(400)
            self.end_headers()
            return
        with runtime.lock:
            call = runtime.calls.pop(call_id, None)
            runtime.send_locks.pop(call_id, None)
        print(
            f"VOICE call_ended call_id={call_id} received={call.get('received_packets', 0) if call else 0}",
            flush=True,
        )
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_):
        pass
