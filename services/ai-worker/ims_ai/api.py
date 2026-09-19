"""Authenticated HTTP ingress and metadata-only operational status."""

from __future__ import annotations

import hmac
import json
import queue
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

from . import runtime, settings
from .maintenance import expire_events


class Api(BaseHTTPRequestHandler):
    def authorized(self):
        return hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {runtime.control_token}"
        )

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204 if runtime.model is not None else 503)
            self.end_headers()
            return
        if self.path != "/events":
            self.send_response(404)
            self.end_headers()
            return
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
            return
        with runtime.lock:
            expire_events(time.time())
            body = json.dumps(
                {
                    "status": "ok" if runtime.model is not None else "loading",
                    "mode": "OBSERVE",
                    "backend": settings.backend,
                    "model": settings.model_size,
                    "model_revision": settings.model_revision,
                    "device": settings.device,
                    "model_error": runtime.model_error,
                    "queue_depth": runtime.work.qsize(),
                    "buffered_streams": len(runtime.buffers),
                    "active_conversations": len(runtime.conversations),
                    "events": runtime.events,
                }
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/observe":
            self.send_response(404)
            self.end_headers()
            return
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > settings.request_max_bytes:
            self.send_response(413)
            self.end_headers()
            return
        try:
            event = json.loads(self.rfile.read(length))
            event["received_at"] = time.time()
            runtime.work.put_nowait(event)
            print(
                f"AI stream_received packets={event.get('packets')} audio={event.get('audio_bytes', 0)} "
                f"calls={event.get('call_ids')}",
                flush=True,
            )
        except (json.JSONDecodeError, TypeError):
            self.send_response(400)
            self.end_headers()
            return
        except queue.Full:
            self.send_response(429)
            self.end_headers()
            return
        self.send_response(202)
        self.end_headers()

    def do_DELETE(self):
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
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
        try:
            runtime.work.put_nowait({"control": "end_call", "call_id": call_id})
        except queue.Full:
            self.send_response(429)
            self.end_headers()
            return
        self.send_response(202)
        self.end_headers()

    def log_message(self, *_):
        pass
