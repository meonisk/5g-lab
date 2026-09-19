"""Environment configuration and shared state for this service process."""

import ipaddress
import os
import re
import socket
import threading

agent_ip = os.environ["VOICE_AGENT_IP"]
rtp_port = int(os.environ["VOICE_AGENT_RTP_PORT"])
http_port = int(os.environ["VOICE_AGENT_HTTP_PORT"])
greeting = os.environ["VOICE_AGENT_GREETING"]
transcriber_greeting = os.environ["VOICE_TRANSCRIBER_GREETING"]
reply_text = os.environ["VOICE_AGENT_REPLY"]
tts_backend = os.environ["TTS_BACKEND"]
if tts_backend != "espeak-ng":
    raise ValueError(f"unsupported lightweight TTS backend: {tts_backend}")
tts_voice = os.environ["TTS_VOICE"]
tts_translation_voice = os.environ["TTS_TRANSLATION_VOICE"]
tts_rate = int(os.environ["TTS_RATE"])
allowed_tts_voices = {tts_voice, tts_translation_voice}
allowed_service_modes = {"translate", "transcribe", "assistant"}
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
