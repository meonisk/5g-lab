import json
import os
import socket
import struct
import threading
import time
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port_min = int(os.environ["RTPENGINE_PORT_MIN"])
port_max = int(os.environ["RTPENGINE_PORT_MAX"])
http_port = int(os.environ["MEDIA_ADAPTER_PORT"])
interval = float(os.environ["MEDIA_OBSERVE_INTERVAL_SECONDS"])
session_ttl = float(os.environ["MEDIA_SESSION_TTL_SECONDS"])
worker_url = os.environ["AI_WORKER_URL"].rstrip("/") + "/observe"
sessions = {}
counters = defaultdict(lambda: [0, 0])
lock = threading.Lock()

class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok", "mode": "OBSERVE", "sessions": list(sessions)}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        call_id = data.get("call_id", "")
        if call_id:
            with lock: sessions[call_id] = data
            print(f"MEDIA session call_id={call_id} mode=OBSERVE", flush=True)
        self.send_response(202); self.end_headers()
    def log_message(self, *_): pass

def capture():
    raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
    while True:
        packet = raw.recv(65535)
        if len(packet) < 42 or packet[23] != 17:
            continue
        ihl = (packet[14] & 15) * 4
        udp = 14 + ihl
        src_port, dst_port, length = struct.unpack("!HHH", packet[udp:udp+6])
        relay_port = src_port if port_min <= src_port <= port_max else dst_port
        if not (port_min <= relay_port <= port_max) or relay_port % 2:
            continue
        payload = packet[udp+8:udp+length]
        if len(payload) < 12 or payload[0] >> 6 != 2:
            continue
        ssrc = struct.unpack("!I", payload[8:12])[0]
        key = (ssrc, src_port, dst_port, payload[1] & 0x7f)
        with lock:
            counters[key][0] += 1
            counters[key][1] += len(payload) - 12

def publish():
    while True:
        time.sleep(interval)
        with lock:
            batch = dict(counters); counters.clear()
            cutoff = time.time() - session_ttl
            expired = [call_id for call_id, value in sessions.items() if value.get("observed_at", 0) < cutoff]
            for call_id in expired: sessions.pop(call_id, None)
            active = list(sessions)
        for (ssrc, src, dst, payload_type), (packets, payload_bytes) in batch.items():
            event = {"event": "normalized_audio_activity", "mode": "OBSERVE", "call_ids": active,
                     "ssrc": ssrc, "payload_type": payload_type, "packets": packets,
                     "payload_bytes": payload_bytes, "window_seconds": interval, "observed_at": time.time()}
            try:
                req = urllib.request.Request(worker_url, json.dumps(event).encode(), {"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=1).read()
                print(f"MEDIA delivered ssrc={ssrc} packets={packets} calls={len(active)}", flush=True)
            except Exception as exc:
                print(f"MEDIA AI unavailable (media relay unaffected): {exc}", flush=True)

threading.Thread(target=capture, daemon=True).start()
threading.Thread(target=publish, daemon=True).start()
print(f"Media Adapter listening :{http_port}, RTP range {port_min}-{port_max}", flush=True)
ThreadingHTTPServer(("0.0.0.0", http_port), Api).serve_forever()
