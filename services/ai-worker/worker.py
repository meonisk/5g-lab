import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

events = []
lock = threading.Lock()

class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock: body = json.dumps({"status": "ok", "mode": "OBSERVE", "events": events[-100:]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        event = json.loads(self.rfile.read(length) or b"{}")
        # Deterministic first MVP inference: classify an RTP window as audio activity.
        event["inference"] = "speech_activity" if event.get("packets", 0) > 0 else "silence"
        event["processed_at"] = time.time()
        with lock: events.append(event)
        print(f"AI inference={event['inference']} packets={event.get('packets')} calls={event.get('call_ids')}", flush=True)
        self.send_response(202); self.end_headers()
    def log_message(self, *_): pass

port = int(os.environ["AI_WORKER_PORT"])
print(f"AI Worker listening :{port} mode=OBSERVE", flush=True)
ThreadingHTTPServer(("0.0.0.0", port), Api).serve_forever()
