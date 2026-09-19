"""Environment configuration and shared state for this service process."""

import ipaddress
import os
import re
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
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
call_id_pattern = re.compile(r"^[A-Za-z0-9_.+~-]{1,128}$")
allowed_service_modes = {
    "observe",
    "translate",
    "transcribe",
    "assistant",
    "bilingual_test",
}
sessions = {}
counters = defaultdict(lambda: {"packets": 0, "payload_bytes": 0, "audio": bytearray()})
lock = threading.Lock()
