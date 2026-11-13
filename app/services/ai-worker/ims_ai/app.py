"""Start background inference and the authenticated HTTP server."""

import os
import threading

from lab_common.http import run_api

from . import settings
from .api import api
from .lifecycle import process_events
from .models import load_model
from .queueing import process_utterances
from .startup import unapplied_mode_error


def main():
    error = unapplied_mode_error(os.environ)
    if error:
        print(f"AI startup_refused: {error}", flush=True)
        raise SystemExit(2)
    threading.Thread(target=load_model, daemon=True).start()
    threading.Thread(target=process_events, daemon=True, name="media-assembler").start()
    for index in range(settings.processing_workers):
        threading.Thread(
            target=process_utterances,
            daemon=True,
            name=f"inference-{index + 1}",
        ).start()
    port = int(os.environ["AI_WORKER_PORT"])
    print(
        f"AI Worker listening :{port} mode=OBSERVE backend={settings.backend} "
        f"model={settings.model_size} device={settings.device} "
        f"processing_workers={settings.processing_workers}",
        flush=True,
    )
    run_api(api, os.environ["AI_WORKER_BIND"], port)
