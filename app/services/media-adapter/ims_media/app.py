"""Service startup; importing pipeline modules does not start worker threads."""

import threading

from lab_common.http import run_api

from . import runtime
from .api import api
from .capture import capture
from .publish import publish


def main():
    threading.Thread(target=capture, daemon=True).start()
    threading.Thread(target=publish, daemon=True).start()
    print(
        f"Media Adapter listening :{runtime.http_port}, RTP range {runtime.port_min}-{runtime.port_max}",
        flush=True,
    )
    run_api(api, "0.0.0.0", runtime.http_port)
