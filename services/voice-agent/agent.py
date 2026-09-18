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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

agent_ip = os.environ["VOICE_AGENT_IP"]
rtp_port = int(os.environ["VOICE_AGENT_RTP_PORT"])
http_port = int(os.environ["VOICE_AGENT_HTTP_PORT"])
greeting = os.environ["VOICE_AGENT_GREETING"]
reply_text = os.environ["VOICE_AGENT_REPLY"]
vad_rms = int(os.environ["VOICE_AGENT_VAD_RMS"])
silence_seconds = int(os.environ["VOICE_AGENT_SILENCE_MS"]) / 1000
call_timeout = int(os.environ["VOICE_AGENT_CALL_TIMEOUT"])

rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rtp.bind((agent_ip, rtp_port))
calls = {}
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
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    raw_path = f"/tmp/{key}.ulaw"
    if not os.path.exists(raw_path):
        with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
            subprocess.run(["espeak-ng", "-s", "145", "-w", wav.name, text], check=True)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav.name,
                            "-ar", "8000", "-ac", "1", "-f", "mulaw", raw_path], check=True)
    with open(raw_path, "rb") as source:
        return source.read()

def send_audio(call_id, text, reason):
    with lock:
        call = calls.get(call_id)
    if not call:
        return
    payload = synthesize(text)
    seq = call["seq"]
    timestamp = call["timestamp"]
    remote = (call["remote_ip"], call["remote_port"])
    sent = 0
    for offset in range(0, len(payload), 160):
        with lock:
            if call_id not in calls:
                return
        frame = payload[offset:offset + 160].ljust(160, b"\xff")
        header = struct.pack("!BBHII", 0x80, 0, seq, timestamp, call["ssrc"])
        rtp.sendto(header + frame, remote)
        seq = (seq + 1) & 0xffff
        timestamp = (timestamp + 160) & 0xffffffff
        sent += 1
        time.sleep(0.02)
    with lock:
        call["seq"] = seq
        call["timestamp"] = timestamp
        event = {"call_id": call_id, "event": "tts_sent", "reason": reason,
                 "text": text, "packets": sent, "at": time.time()}
        events.append(event)
    print(f"VOICE tts call_id={call_id} reason={reason} packets={sent}", flush=True)

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
                if peer[0] != call["remote_ip"]:
                    continue
                call["received_packets"] += 1
                if rms >= vad_rms:
                    call["speech_seen"] = True
                    call["last_voice"] = now
                elif call["speech_seen"] and not call["replied"] and now - call["last_voice"] >= silence_seconds:
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
        for call_id, received in expired:
            print(f"VOICE call_expired call_id={call_id} received={received}", flush=True)

class Api(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock:
            body = json.dumps({"status": "ok", "mode": "TERMINATE", "calls": calls, "events": events[-100:]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        call_id = data["call_id"]
        with lock:
            calls[call_id] = {"remote_ip": data["remote_ip"], "remote_port": int(data["remote_port"]),
                              "ssrc": int.from_bytes(hashlib.sha256(call_id.encode()).digest()[:4], "big"),
                              "seq": 1, "timestamp": 0, "received_packets": 0,
                              "speech_seen": False, "last_voice": 0, "replied": False,
                              "started_at": time.time()}
        print(f"VOICE call_started call_id={call_id} remote={data['remote_ip']}:{data['remote_port']}", flush=True)
        threading.Thread(target=send_audio, args=(call_id, greeting, "greeting"), daemon=True).start()
        self.send_response(202); self.end_headers()
    def do_DELETE(self):
        call_id = self.path.rsplit("/", 1)[-1]
        with lock: call = calls.pop(call_id, None)
        print(f"VOICE call_ended call_id={call_id} received={call.get('received_packets', 0) if call else 0}", flush=True)
        self.send_response(204); self.end_headers()
    def log_message(self, *_): pass

threading.Thread(target=receive_audio, daemon=True).start()
threading.Thread(target=expire_calls, daemon=True).start()
print(f"Voice Agent HTTP :{http_port}, RTP {agent_ip}:{rtp_port}, codec=PCMU/8000", flush=True)
ThreadingHTTPServer(("0.0.0.0", http_port), Api).serve_forever()
