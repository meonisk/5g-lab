"""HTTP API панели и раздача собранного интерфейса.

Панель слушает только 127.0.0.1 и открывается через SSH-туннель, входа нет. Чтобы
чужая страница в том же браузере не управляла стендом: имя в Host — только
127.0.0.1/localhost (DNS rebinding), у изменяющих запросов — заголовок X-Panel и
Origin с тем же Host (CSRF: простая форма не ставит свои заголовки). Порт любой:
туннель может открыть панель на другом локальном порту (ssh -L 9000:localhost:8090).
"""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, abort, request, send_from_directory, stream_with_context

from . import logs, status


def sse(items, encode):
    """Поток Server-Sent Events; None от источника — комментарий, чтобы связь не рвалась."""
    for item in items:
        yield ": ping\n\n" if item is None else f"data: {json.dumps(encode(item))}\n\n"


def stream(generator, on_close=None) -> Response:
    def wrapped():
        try:
            yield from generator
        finally:
            if on_close:
                on_close()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(stream_with_context(wrapped()), mimetype="text/event-stream", headers=headers)


LOCAL = {"127.0.0.1", "localhost"}


def local_host(value: str) -> bool:
    """Host вида localhost:9000 или 127.0.0.1 — да; любое другое имя — нет."""
    try:
        return urlsplit(f"//{value}").hostname in LOCAL
    except ValueError:
        return False


def allowed(method: str, host: str, origin: str | None, marker: str | None) -> bool:
    if not local_host(host):
        return False
    if method == "GET":
        return True
    return marker == "1" and (origin is None or origin == f"http://{host}")


def create_app(root: Path, runner, calls, metrics, static: Path) -> Flask:
    app = Flask("lab_panel", static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 4096

    @app.before_request
    def guard():
        headers = request.headers
        if not allowed(request.method, request.host, headers.get("Origin"), headers.get("X-Panel")):
            abort(403)

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    def error(error):
        return {"error": getattr(error, "description", "error")}, error.code

    @app.get("/api/status")
    def get_status():
        summary = status.summary(root, runner.current())
        summary["sipcap"] = calls.online
        return summary

    @app.get("/api/actions")
    def actions():
        from .jobs import catalog

        return {"actions": catalog()}

    @app.post("/api/actions/<name>")
    def start(name):
        result = runner.start(name)
        if result == "unknown":
            abort(404, "действие не разрешено")
        if result == "busy":
            abort(409, "уже идёт изменяющее задание")
        return result.info(), 202

    @app.get("/api/jobs")
    def jobs():
        return {"jobs": runner.list()}

    @app.get("/api/jobs/<job_id>/stream")
    def job_stream(job_id):
        job = runner.get(job_id)
        if job is None:
            abort(404, "нет задания")

        def events():
            yield from sse(job.follow(), lambda line: {"line": line})
            yield f"event: end\ndata: {json.dumps(job.info())}\n\n"

        return stream(events())

    @app.get("/api/logs/sources")
    def log_sources():
        return {"sources": logs.sources()}

    @app.get("/api/logs/stream")
    def log_stream():
        names = [n for n in request.args.get("sources", "").split(",") if n]
        tail = min(max(request.args.get("tail", 200, type=int), 0), 2000)
        if not names:
            abort(404, "нет источников")
        source = logs.Stream(names, root, tail)
        encode = lambda item: {"source": item[0], "line": item[1]}  # noqa: E731
        return stream(sse(source.items(), encode), source.close)

    @app.get("/api/metrics/series")
    def metric_names():
        return {"series": metrics.names()}

    @app.get("/api/metrics")
    def metric_points():
        names = [n for n in request.args.get("series", "").split(",") if n][:300]
        since = request.args.get("since", time.time() - 900, type=float)
        return {"series": metrics.query(names, since), "now": time.time()}

    @app.get("/api/calls")
    def call_list():
        kind = request.args.get("kind", "calls")
        return {"calls": calls.list(kind), "online": calls.online}

    @app.get("/api/calls/<path:call_id>")
    def call_dialog(call_id):
        dialog = calls.dialog(call_id)
        if dialog is None:
            abort(404, "нет диалога")
        return dialog

    @app.get("/")
    @app.get("/<path:name>")
    def files(name="index.html"):
        if name.startswith("api/"):
            abort(404)
        if not (static / "index.html").is_file():
            return "Интерфейс не собран: scripts/panel.sh install", 503
        if not (static / name).is_file():
            name = "index.html"
        return send_from_directory(static, name)

    return app
