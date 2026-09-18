import json
import os
import threading
import time
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

events = []
lock = threading.Lock()
event_retention = int(os.environ["AI_EVENT_RETENTION"])
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()

class Api(BaseHTTPRequestHandler):
    def authorized(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {control_token}")
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204); self.end_headers(); return
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        with lock: body = json.dumps({"status": "ok", "mode": "OBSERVE", "events": events}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path != "/observe":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 65536:
            self.send_response(413); self.end_headers(); return
        try:
            event = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_response(400); self.end_headers(); return
        # Deterministic first MVP inference: classify an RTP window as audio activity.
        event["inference"] = "speech_activity" if event.get("packets", 0) > 0 else "silence"
        event["processed_at"] = time.time()
        with lock:
            events.append(event)
            del events[:-event_retention]
        print(f"AI inference={event['inference']} packets={event.get('packets')} calls={event.get('call_ids')}", flush=True)
        self.send_response(202); self.end_headers()
    def log_message(self, *_): pass

port = int(os.environ["AI_WORKER_PORT"])
print(f"AI Worker listening :{port} mode=OBSERVE", flush=True)
ThreadingHTTPServer(("0.0.0.0", port), Api).serve_forever()
