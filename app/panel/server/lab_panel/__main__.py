"""Сервер панели стенда: python -m lab_panel (запускает scripts/panel.sh)."""

import os
import threading
from pathlib import Path

from waitress import serve

from .calls import Calls
from .jobs import Runner
from .metrics import Metrics
from .web import create_app

ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    port = int(os.environ.get("PANEL_PORT", "8090"))
    sipcap = f"http://127.0.0.1:{os.environ.get('PANEL_SIPCAP_PORT', '8097')}"

    metrics = Metrics()
    calls = Calls(sipcap)
    calls.listeners.append(metrics.on_sip)
    threading.Thread(target=calls.poll_forever, daemon=True).start()
    metrics.start()

    static = ROOT / "app/panel/web/dist"
    app = create_app(ROOT, Runner(ROOT), calls, metrics, static)
    print(f"PANEL http://127.0.0.1:{port} (через SSH-туннель)", flush=True)
    # Потоки SSE (журналы, задания) держат поток waitress, поэтому их много.
    serve(app, host="127.0.0.1", port=port, threads=32, expose_tracebacks=False)


if __name__ == "__main__":
    main()
