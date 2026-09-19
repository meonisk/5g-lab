"""Service startup; importing pipeline modules does not start worker threads."""

import threading
from http.server import ThreadingHTTPServer

from . import runtime
from .api import Api
from .media import expire_calls, receive_audio


def main():
    threading.Thread(target=receive_audio, daemon=True).start()
    threading.Thread(target=expire_calls, daemon=True).start()
    print(
        f"Voice Agent HTTP :{runtime.http_port}, RTP {runtime.agent_ip}:{runtime.rtp_port}, codec=PCMU/8000, "
        f"tts={runtime.tts_backend}:{runtime.tts_voice}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", runtime.http_port), Api).serve_forever()
