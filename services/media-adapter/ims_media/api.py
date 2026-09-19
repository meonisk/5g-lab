"""Authenticated observation session lifecycle."""

import hmac
import json
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

from . import runtime


def end_worker_call(call_id):
    try:
        request = urllib.request.Request(
            runtime.worker_base_url + "/calls/" + urllib.parse.quote(call_id, safe=""),
            method="DELETE",
            headers={"Authorization": f"Bearer {runtime.control_token}"},
        )
        urllib.request.urlopen(request, timeout=2).read()
    except Exception as exc:
        print(f"MEDIA worker cleanup failed type={type(exc).__name__}", flush=True)


class Api(BaseHTTPRequestHandler):
    def authorized(self):
        return hmac.compare_digest(
            self.headers.get("Authorization", ""), f"Bearer {runtime.control_token}"
        )

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204)
            self.end_headers()
            return
        if self.path != "/sessions":
            self.send_response(404)
            self.end_headers()
            return
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps(
            {"status": "ok", "mode": "OBSERVE", "sessions": list(runtime.sessions)}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/sessions":
            self.send_response(404)
            self.end_headers()
            return
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 4096:
            self.send_response(413)
            self.end_headers()
            return
        try:
            incoming = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        # Data minimization boundary: subscriber SIP identities never enter the
        # analytics path. Only an opaque call correlation id and timing remain.
        data = {
            "call_id": incoming.get("call_id", ""),
            "observed_at": incoming.get("observed_at", 0),
            "service_mode": incoming.get("service_mode", "observe"),
        }
        call_id = data.get("call_id", "")
        if (
            runtime.call_id_pattern.fullmatch(call_id)
            and data["service_mode"] in runtime.allowed_service_modes
        ):
            with runtime.lock:
                runtime.sessions[call_id] = data
            print(
                f"MEDIA session call_id={call_id} service={data['service_mode']}",
                flush=True,
            )
        else:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(202)
        self.end_headers()

    def do_DELETE(self):
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
            return
        if not self.path.startswith("/sessions/"):
            self.send_response(404)
            self.end_headers()
            return
        call_id = urllib.parse.unquote(self.path.removeprefix("/sessions/"))
        if not runtime.call_id_pattern.fullmatch(call_id):
            self.send_response(400)
            self.end_headers()
            return
        with runtime.lock:
            removed = runtime.sessions.pop(call_id, None)
        if removed:
            threading.Thread(target=end_worker_call, args=(call_id,), daemon=True).start()
        print(
            f"MEDIA session_ended call_id={call_id} existed={removed is not None}",
            flush=True,
        )
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_):
        pass
