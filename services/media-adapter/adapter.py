import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
import urllib.request
import urllib.parse
import hmac
import ipaddress
import re
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port_min = int(os.environ["RTPENGINE_PORT_MIN"])
port_max = int(os.environ["RTPENGINE_PORT_MAX"])
http_port = int(os.environ["MEDIA_ADAPTER_PORT"])
interval = float(os.environ["MEDIA_OBSERVE_INTERVAL_SECONDS"])
session_ttl = float(os.environ["MEDIA_SESSION_TTL_SECONDS"])
audio_max_bytes = int(os.environ["MEDIA_AUDIO_MAX_BYTES"])
worker_base_url = os.environ["AI_WORKER_URL"].rstrip("/")
worker_url = worker_base_url + "/observe"
voice_agent_ip = str(ipaddress.ip_address(os.environ["VOICE_AGENT_IP"]))
ims_ue_network = ipaddress.ip_network(os.environ["IMS_UE_CIDR"])
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
call_id_pattern = re.compile(r"^[A-Za-z0-9_.+~-]{1,128}$")
allowed_service_modes = {"observe", "translate", "transcribe", "assistant", "bilingual_test"}
sessions = {}
counters = defaultdict(lambda: {"packets": 0, "payload_bytes": 0, "audio": bytearray()})
lock = threading.Lock()


def end_worker_call(call_id):
    try:
        request = urllib.request.Request(
            worker_base_url + "/calls/" + urllib.parse.quote(call_id, safe=""),
            method="DELETE", headers={"Authorization": f"Bearer {control_token}"})
        urllib.request.urlopen(request, timeout=2).read()
    except Exception as exc:
        print(f"MEDIA worker cleanup failed type={type(exc).__name__}", flush=True)

class Api(BaseHTTPRequestHandler):
    def authorized(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {control_token}")
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204); self.end_headers(); return
        if self.path != "/sessions":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        body = json.dumps({"status": "ok", "mode": "OBSERVE", "sessions": list(sessions)}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path != "/sessions":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 4096:
            self.send_response(413); self.end_headers(); return
        try:
            incoming = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_response(400); self.end_headers(); return
        # Data minimization boundary: subscriber SIP identities never enter the
        # analytics path. Only an opaque call correlation id and timing remain.
        data = {"call_id": incoming.get("call_id", ""),
                "observed_at": incoming.get("observed_at", 0),
                "service_mode": incoming.get("service_mode", "observe")}
        call_id = data.get("call_id", "")
        if call_id_pattern.fullmatch(call_id) and data["service_mode"] in allowed_service_modes:
            with lock: sessions[call_id] = data
            print(f"MEDIA session call_id={call_id} service={data['service_mode']}", flush=True)
        else:
            self.send_response(400); self.end_headers(); return
        self.send_response(202); self.end_headers()
    def do_DELETE(self):
        if not self.authorized():
            self.send_response(401); self.end_headers(); return
        if not self.path.startswith("/sessions/"):
            self.send_response(404); self.end_headers(); return
        call_id = urllib.parse.unquote(self.path.removeprefix("/sessions/"))
        if not call_id_pattern.fullmatch(call_id):
            self.send_response(400); self.end_headers(); return
        with lock:
            removed = sessions.pop(call_id, None)
        if removed:
            threading.Thread(target=end_worker_call, args=(call_id,), daemon=True).start()
        print(f"MEDIA session_ended call_id={call_id} existed={removed is not None}", flush=True)
        self.send_response(204); self.end_headers()
    def log_message(self, *_): pass

def rtp_payload(packet):
    if len(packet) < 12 or packet[0] >> 6 != 2:
        return b""
    offset = 12 + (packet[0] & 0x0f) * 4
    if len(packet) < offset:
        return b""
    if packet[0] & 0x10:
        if len(packet) < offset + 4:
            return b""
        extension_words = struct.unpack("!H", packet[offset + 2:offset + 4])[0]
        offset += 4 + extension_words * 4
    padding = packet[-1] if packet[0] & 0x20 else 0
    end = len(packet) - padding
    return packet[offset:end] if offset <= end else b""

def packet_direction(src_ip, dst_ip):
    if dst_ip == voice_agent_ip:
        return "caller_to_agent"
    if src_ip == voice_agent_ip:
        return "agent_to_caller"
    if ipaddress.ip_address(src_ip) in ims_ue_network:
        return "caller_to_core"
    if ipaddress.ip_address(dst_ip) in ims_ue_network:
        return "core_to_caller"
    return "other"

def capture():
    raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
    while True:
        packet = raw.recv(65535)
        if len(packet) < 42 or packet[23] != 17:
            continue
        ihl = (packet[14] & 15) * 4
        udp = 14 + ihl
        src_ip = socket.inet_ntoa(packet[26:30])
        dst_ip = socket.inet_ntoa(packet[30:34])
        src_port, dst_port, length = struct.unpack("!HHH", packet[udp:udp+6])
        relay_port = src_port if port_min <= src_port <= port_max else dst_port
        if not (port_min <= relay_port <= port_max) or relay_port % 2:
            continue
        rtp_packet = packet[udp+8:udp+length]
        if len(rtp_packet) < 12 or rtp_packet[0] >> 6 != 2:
            continue
        payload_type = rtp_packet[1] & 0x7f
        payload = rtp_payload(rtp_packet)
        if not payload:
            continue
        ssrc = struct.unpack("!I", rtp_packet[8:12])[0]
        direction = packet_direction(src_ip, dst_ip)
        key = (ssrc, src_port, dst_port, payload_type, direction)
        with lock:
            value = counters[key]
            value["packets"] += 1
            value["payload_bytes"] += len(payload)
            # Only packets sourced by an IMS-PDU subscriber cross the AI data
            # boundary. Agent TTS is tagged agent_to_caller and cannot feed STT.
            if direction == "caller_to_core" and payload_type == 0 and len(value["audio"]) < audio_max_bytes:
                remaining = audio_max_bytes - len(value["audio"])
                value["audio"].extend(payload[:remaining])

def publish():
    while True:
        time.sleep(interval)
        with lock:
            batch = dict(counters); counters.clear()
            cutoff = time.time() - session_ttl
            expired = [call_id for call_id, value in sessions.items() if value.get("observed_at", 0) < cutoff]
            for call_id in expired:
                sessions.pop(call_id, None)
            active = dict(sessions)
        for call_id in expired:
            threading.Thread(target=end_worker_call, args=(call_id,), daemon=True).start()
        active_call_ids = list(active)
        service_mode = active[active_call_ids[0]]["service_mode"] if len(active_call_ids) == 1 else "observe"
        for (ssrc, src, dst, payload_type, direction), value in batch.items():
            audio = bytes(value["audio"])
            event = {"event": "normalized_audio_activity", "mode": "OBSERVE",
                     "call_ids": active_call_ids, "service_mode": service_mode,
                     "ssrc": ssrc, "payload_type": payload_type, "packets": value["packets"],
                     "source_stream_id": hashlib.sha256(f"{src}:{ssrc}".encode()).hexdigest()[:16],
                     "direction": direction,
                     "payload_bytes": value["payload_bytes"], "window_seconds": interval,
                     "observed_at": time.time()}
            if audio:
                event.update({"codec": "PCMU", "sample_rate_hz": 8000,
                              "audio_bytes": len(audio), "audio_sha256": hashlib.sha256(audio).hexdigest(),
                              "audio_ulaw_b64": base64.b64encode(audio).decode("ascii")})
            try:
                req = urllib.request.Request(worker_url, json.dumps(event).encode(), {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {control_token}",
                })
                urllib.request.urlopen(req, timeout=1).read()
                print(f"MEDIA delivered direction={direction} ssrc={ssrc} packets={value['packets']} "
                      f"audio={len(audio)} calls={len(active_call_ids)} service={service_mode}", flush=True)
            except Exception as exc:
                print(f"MEDIA AI unavailable (media relay unaffected): {exc}", flush=True)

threading.Thread(target=capture, daemon=True).start()
threading.Thread(target=publish, daemon=True).start()
print(f"Media Adapter listening :{http_port}, RTP range {port_min}-{port_max}", flush=True)
ThreadingHTTPServer(("0.0.0.0", http_port), Api).serve_forever()
