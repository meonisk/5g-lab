"""Start background inference and the authenticated HTTP server."""

import os
import threading
from http.server import ThreadingHTTPServer

from . import settings
from .api import Api
from .lifecycle import process_events
from .models import load_model


def main():
    threading.Thread(target=load_model, daemon=True).start()
    threading.Thread(target=process_events, daemon=True).start()
    port = int(os.environ["AI_WORKER_PORT"])
    print(
        f"AI Worker listening :{port} mode=OBSERVE backend={settings.backend} "
        f"model={settings.model_size} device={settings.device}",
        flush=True,
    )
    ThreadingHTTPServer((os.environ["AI_WORKER_BIND"], port), Api).serve_forever()
