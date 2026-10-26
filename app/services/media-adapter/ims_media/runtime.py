"""Environment configuration and shared state for this service process."""

import ipaddress
import os
import threading
from collections import defaultdict

port_min = int(os.environ["RTPENGINE_PORT_MIN"])
port_max = int(os.environ["RTPENGINE_PORT_MAX"])
rtpengine_ip = str(ipaddress.ip_address(os.environ["RTPENGINE_IP"]))
rtpengine_ng_port = int(os.environ["RTPENGINE_NG_PORT"])
rtpengine_query_timeout = float(os.environ["RTPENGINE_QUERY_TIMEOUT_SECONDS"])
http_port = int(os.environ["MEDIA_ADAPTER_PORT"])
interval = float(os.environ["MEDIA_OBSERVE_INTERVAL_SECONDS"])
session_ttl = float(os.environ["MEDIA_SESSION_TTL_SECONDS"])
audio_max_bytes = int(os.environ["MEDIA_AUDIO_MAX_BYTES"])
worker_base_url = os.environ["AI_WORKER_URL"].rstrip("/")
worker_url = worker_base_url + "/observe"
voice_agent_ip = str(ipaddress.ip_address(os.environ["VOICE_AGENT_IP"]))
ims_ue_network = ipaddress.ip_network(os.environ["IMS_UE_CIDR"])
# Абонент — телефон из пула UE или тестовый клиент PJSUA: тесты ставят клиентов
# прямо в сеть ядра, без PDU-сессии, поэтому их адреса вне IMS_UE_CIDR.
subscriber_networks = (
    ims_ue_network,
    *(ipaddress.ip_network(os.environ[key]) for key in ("SIPUE1_IP", "SIPUE2_IP")),
)


def is_subscriber(address):
    ip = ipaddress.ip_address(address)
    return any(ip in network for network in subscriber_networks)


with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
allowed_service_modes = {
    "observe",
    "translate",
    "transcribe",
    "assistant",
    "bilingual_test",
    "interpret_ru",
    "interpret_en",
}
sessions = {}
counters = defaultdict(lambda: {"packets": 0, "payload_bytes": 0, "audio": bytearray()})
lock = threading.Lock()
