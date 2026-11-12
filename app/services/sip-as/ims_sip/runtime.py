"""Environment configuration and shared state for this service process."""

import ipaddress
import os
import socket

from .core.subscribers import language_table


def leg_b_route_mode(value: str | None) -> str:
    """isc — нога B с ISC-меткой ноги A; orig — fallback F1 spike: цепочка заново."""
    mode = value or "isc"
    if mode not in ("isc", "orig"):
        raise ValueError(f"SIP_AS_LEG_B_ROUTE={mode}: допустимы isc или orig")
    return mode


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
ims_domain = os.environ["IMS_DOMAIN"]
leg_b_route = leg_b_route_mode(os.environ.get("SIP_AS_LEG_B_ROUTE"))
languages = language_table(os.environ)
default_language = os.environ.get("DEFAULT_LANGUAGE") or "ru"
own_call_ids = set()
record_marks = set()
ai_worker_url = os.environ["AI_WORKER_URL"].rstrip("/")
voice_status_url = os.environ["VOICE_AGENT_URL"].rstrip("/") + "/status"
voice_max_calls = int(os.environ["VOICE_AGENT_MAX_CALLS"])
b2bua_calls = {}
b2bua_branches = {}
answer_hooks = {}
record_invites = {}
announcements = {
    "ru": (os.environ["RECORDING_ANNOUNCEMENT_RU"], os.environ["TTS_VOICE"]),
    "en": (os.environ["RECORDING_ANNOUNCEMENT_EN"], os.environ["TTS_TRANSLATION_VOICE"]),
}
