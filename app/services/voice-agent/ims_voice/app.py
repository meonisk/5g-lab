"""Service startup; importing pipeline modules does not start worker threads."""

import threading

from lab_common.http import run_api

from . import runtime
from .api import api
from .calls import expire_calls
from .media import receive_audio


def main():
    threading.Thread(target=receive_audio, daemon=True).start()
    threading.Thread(target=expire_calls, daemon=True).start()
    print(
        f"Voice Agent HTTP :{runtime.http_port}, RTP {runtime.agent_ip}:{runtime.rtp_port}, codec=PCMU/8000, "
        f"tts={runtime.tts_backend}:{runtime.tts_voice}",
        flush=True,
    )
    run_api(api, "0.0.0.0", runtime.http_port)
