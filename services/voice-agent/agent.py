import hashlib
import json
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
import math
import hmac
import ipaddress
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

agent_ip = os.environ["VOICE_AGENT_IP"]
rtp_port = int(os.environ["VOICE_AGENT_RTP_PORT"])
http_port = int(os.environ["VOICE_AGENT_HTTP_PORT"])
greeting = os.environ["VOICE_AGENT_GREETING"]
reply_text = os.environ["VOICE_AGENT_REPLY"]
tts_backend = os.environ["TTS_BACKEND"]
if tts_backend != "espeak-ng":
    raise ValueError(f"unsupported lightweight TTS backend: {tts_backend}")
tts_voice = os.environ["TTS_VOICE"]
tts_rate = int(os.environ["TTS_RATE"])
reply_max_chars = int(os.environ["VOICE_AGENT_REPLY_MAX_CHARS"])
llm_mode = os.environ["VOICE_AGENT_LLM_MODE"] == "1"
vad_rms = int(os.environ["VOICE_AGENT_VAD_RMS"])
silence_seconds = int(os.environ["VOICE_AGENT_SILENCE_MS"]) / 1000
call_timeout = int(os.environ["VOICE_AGENT_CALL_TIMEOUT"])
max_calls = int(os.environ["VOICE_AGENT_MAX_CALLS"])
event_retention = int(os.environ["VOICE_AGENT_EVENT_RETENTION"])
rtpengine_ip = str(ipaddress.ip_address(os.environ["RTPENGINE_IP"]))
rtp_port_min = int(os.environ["RTPENGINE_PORT_MIN"])
rtp_port_max = int(os.environ["RTPENGINE_PORT_MAX"])
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
call_id_pattern = re.compile(r"^[A-Za-z0-9_.+~-]{1,128}$")

rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rtp.bind((agent_ip, rtp_port))
calls = {}
send_locks = {}
events = []
lock = threading.Lock()

def ulaw_sample(value):
    value = (~value) & 0xff
    sign = value & 0x80
    exponent = (value >> 4) & 0x07
    mantissa = value & 0x0f
    sample = ((mantissa << 3) + 0x84) << exponent
    sample -= 0x84
    return -sample if sign else sample

def ulaw_rms(payload):
    if not payload:
        return 0
    return int(math.sqrt(sum(ulaw_sample(value) ** 2 for value in payload) / len(payload)))

def synthesize(text):
    key = hashlib.sha256(f"{tts_voice}\0{tts_rate}\0{text}".encode()).hexdigest()[:16]
    raw_path = f"/tmp/{key}.ulaw"
    if not os.path.exists(raw_path):
        with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
            subprocess.run(["espeak-ng", "-v", tts_voice, "-s", str(tts_rate),
                            "-w", wav.name, text], check=True, timeout=30)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav.name,
                            "-ar", "8000", "-ac", "1", "-f", "mulaw", raw_path],
                           check=True, timeout=30)
    with open(raw_path, "rb") as source:
        return source.read()

def send_audio(call_id, text, reason):
    with lock:
        call = calls.get(call_id)
        call_send_lock = send_locks.get(call_id)
        if call:
            call["tts_generation"] += 1
            generation = call["tts_generation"]
    if not call or not call_send_lock:
        return
    payload = synthesize(text)
    interrupted = False
    with call_send_lock:
        with lock:
            call = calls.get(call_id)
            if not call or call["tts_generation"] != generation:
                return
            call["tts_active"] = True
            seq = call["seq"]
            timestamp = call["timestamp"]
            remote = (call["remote_ip"], call["remote_port"])
            ssrc = call["ssrc"]
        sent = 0
        for offset in range(0, len(payload), 160):
            with lock:
                current = calls.get(call_id)
                if not current or current["tts_generation"] != generation:
                    interrupted = True
                    break
            frame = payload[offset:offset + 160].ljust(160, b"\xff")
            header = struct.pack("!BBHII", 0x80, 0, seq, timestamp, ssrc)
            rtp.sendto(header + frame, remote)
            seq = (seq + 1) & 0xffff
            timestamp = (timestamp + 160) & 0xffffffff
            sent += 1
            time.sleep(0.02)
        with lock:
            current = calls.get(call_id)
            if current:
                current["seq"] = seq
                current["timestamp"] = timestamp
                if current["tts_generation"] == generation:
                    current["tts_active"] = False
            event = {"call_id": call_id, "event": "tts_interrupted" if interrupted else "tts_sent",
                     "reason": reason, "backend": tts_backend, "voice": tts_voice,
                     "packets": sent, "at": time.time()}
            events.append(event)
            del events[:-event_retention]
    state = "interrupted" if interrupted else "sent"
    print(f"VOICE tts call_id={call_id} reason={reason} state={state} backend={tts_backend} "
          f"voice={tts_voice} packets={sent}", flush=True)

def receive_audio():
    while True:
        packet, peer = rtp.recvfrom(4096)
        if len(packet) < 12 or packet[0] >> 6 != 2 or packet[1] & 0x7f != 0:
            continue
        payload = packet[12:]
        rms = ulaw_rms(payload)
        now = time.time()
        responses = []
        with lock:
            for call_id, call in calls.items():
                if peer != (call["remote_ip"], call["remote_port"]):
                    continue
                call["received_packets"] += 1
                if rms >= vad_rms:
                    if call["tts_active"]:
                        call["tts_generation"] += 1
                        call["tts_active"] = False
                    call["speech_seen"] = True
                    call["last_voice"] = now
                elif (not llm_mode and call["speech_seen"] and not call["replied"] and
                      now - call["last_voice"] >= silence_seconds):
                    call["replied"] = True
                    responses.append(call_id)
        for call_id in responses:
            threading.Thread(target=send_audio, args=(call_id, reply_text, "vad_reply"), daemon=True).start()

def expire_calls():
    while True:
        time.sleep(min(30, max(1, call_timeout)))
        cutoff = time.time() - call_timeout
        with lock:
            expired = [(call_id, call["received_packets"]) for call_id, call in calls.items()
                       if call["started_at"] < cutoff]
            for call_id, _ in expired:
                calls.pop(call_id, None)
                send_locks.pop(call_id, None)
        for call_id, received in expired:
            print(f"VOICE call_expired call_id={call_id} received={received}", flush=True)

class Api(BaseHTTPRequestHandler):
    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {control_token}")
    def reject_unauthorized(self):
        self.send_response(401); self.send_header("WWW-Authenticate", "Bearer"); self.end_headers()
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(204); self.end_headers(); return
        if self.path != "/status":
            self.send_response(404); self.end_headers(); return
        if not self.authorized():
            self.reject_unauthorized(); return
        with lock:
            body = json.dumps({"status": "ok", "mode": "TERMINATE", "calls": calls, "events": events}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if not self.authorized():
            self.reject_unauthorized(); return
        if self.path.startswith("/calls/") and self.path.endswith("/reply"):
            encoded_call_id = self.path.removeprefix("/calls/").removesuffix("/reply").rstrip("/")
            call_id = urllib.parse.unquote(encoded_call_id)
            length = int(self.headers.get("Content-Length", "0"))
            if not call_id_pattern.fullmatch(call_id) or length < 2 or length > 4096:
                self.send_response(400); self.end_headers(); return
            try:
                data = json.loads(self.rfile.read(length))
                text = " ".join(data["text"].split())
            except (TypeError, KeyError, json.JSONDecodeError):
                self.send_response(400); self.end_headers(); return
            if not text or len(text) > reply_max_chars or any(ord(char) < 32 for char in text):
                self.send_response(400); self.end_headers(); return
            with lock:
                if call_id not in calls:
                    self.send_response(404); self.end_headers(); return
            threading.Thread(target=send_audio, args=(call_id, text, "llm_reply"), daemon=True).start()
            self.send_response(202); self.end_headers(); return
        if self.path != "/calls":
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 4096:
            self.send_response(413); self.end_headers(); return
        try:
            data = json.loads(self.rfile.read(length))
            call_id = data["call_id"]
            remote_ip = str(ipaddress.ip_address(data["remote_ip"]))
            remote_port = int(data["remote_port"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.send_response(400); self.end_headers(); return
        if (not call_id_pattern.fullmatch(call_id) or remote_ip != rtpengine_ip or
                not rtp_port_min <= remote_port <= rtp_port_max):
            self.send_response(400); self.end_headers(); return
        with lock:
            if call_id not in calls and len(calls) >= max_calls:
                self.send_response(429); self.end_headers(); return
            calls[call_id] = {"remote_ip": remote_ip, "remote_port": remote_port,
                              "ssrc": int.from_bytes(hashlib.sha256(call_id.encode()).digest()[:4], "big"),
                              "seq": 1, "timestamp": 0, "received_packets": 0,
                              "speech_seen": False, "last_voice": 0, "replied": False,
                              "tts_generation": 0, "tts_active": False,
                              "started_at": time.time()}
            send_locks.setdefault(call_id, threading.Lock())
        print(f"VOICE call_started call_id={call_id} remote={data['remote_ip']}:{data['remote_port']}", flush=True)
        threading.Thread(target=send_audio, args=(call_id, greeting, "greeting"), daemon=True).start()
        self.send_response(202); self.end_headers()
    def do_DELETE(self):
        if not self.authorized():
            self.reject_unauthorized(); return
        if not self.path.startswith("/calls/"):
            self.send_response(404); self.end_headers(); return
        call_id = urllib.parse.unquote(self.path.removeprefix("/calls/"))
        if not call_id_pattern.fullmatch(call_id):
            self.send_response(400); self.end_headers(); return
        with lock:
            call = calls.pop(call_id, None)
            send_locks.pop(call_id, None)
        print(f"VOICE call_ended call_id={call_id} received={call.get('received_packets', 0) if call else 0}", flush=True)
        self.send_response(204); self.end_headers()
    def log_message(self, *_): pass

threading.Thread(target=receive_audio, daemon=True).start()
threading.Thread(target=expire_calls, daemon=True).start()
print(f"Voice Agent HTTP :{http_port}, RTP {agent_ip}:{rtp_port}, codec=PCMU/8000, "
      f"tts={tts_backend}:{tts_voice}", flush=True)
ThreadingHTTPServer(("0.0.0.0", http_port), Api).serve_forever()
