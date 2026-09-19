"""Environment configuration and shared state for this service process."""

import ipaddress
import os
import socket

bind_ip = os.environ["SIP_AS_IP"]
bind_port = int(os.environ["SIP_AS_PORT"])
scscf = (os.environ["SCSCF_IP"], int(os.environ["SCSCF_SIP_PORT"]))
adapter_url = os.environ["MEDIA_ADAPTER_URL"].rstrip("/") + "/sessions"
voice_url = os.environ["VOICE_AGENT_URL"].rstrip("/") + "/calls"
voice_number = os.environ["VOICE_TRANSLATOR_MSISDN"]
transcriber_number = os.environ["VOICE_TRANSCRIBER_MSISDN"]
interpreter_ru_number = os.environ["VOICE_INTERPRETER_RU_MSISDN"]
interpreter_en_number = os.environ["VOICE_INTERPRETER_EN_MSISDN"]
voice_user = os.environ["VOICE_AGENT_SIP_USER"]
transcriber_user = os.environ["VOICE_TRANSCRIBER_SIP_USER"]
interpreter_ru_user = os.environ["VOICE_INTERPRETER_RU_SIP_USER"]
interpreter_en_user = os.environ["VOICE_INTERPRETER_EN_SIP_USER"]
voice_ip = os.environ["VOICE_AGENT_IP"]
voice_rtp_port = int(os.environ["VOICE_AGENT_RTP_PORT"])
rtpengine_ip = str(ipaddress.ip_address(os.environ["RTPENGINE_IP"]))
rtp_port_min = int(os.environ["RTPENGINE_PORT_MIN"])
rtp_port_max = int(os.environ["RTPENGINE_PORT_MAX"])
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((bind_ip, bind_port))
transactions = {}
agent_calls = {}
service_targets = {
    voice_number: "translate",
    voice_user: "translate",
    transcriber_number: "transcribe",
    transcriber_user: "transcribe",
    interpreter_ru_number: "interpret_ru",
    interpreter_ru_user: "interpret_ru",
    interpreter_en_number: "interpret_en",
    interpreter_en_user: "interpret_en",
}
service_users = {
    "translate": voice_user,
    "transcribe": transcriber_user,
    "interpret_ru": interpreter_ru_user,
    "interpret_en": interpreter_en_user,
}
