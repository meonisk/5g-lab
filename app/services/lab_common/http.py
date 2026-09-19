"""Общая HTTP-обвязка: токен, ограничение JSON и безопасные ответы об ошибках."""

import hmac
import os
import re

import httpx
from flask import Flask, abort, request
from waitress import serve
from werkzeug.exceptions import HTTPException

CALL_ID = re.compile(r"^[A-Za-z0-9_.+~-]{1,128}$")


def create_api(name: str, token: str, max_body: int = 4096) -> Flask:
    """Все маршруты, кроме healthz, доступны только другим сервисам стенда."""
    app = Flask(name, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = max_body

    @app.before_request
    def authenticate():
        if request.path == "/healthz" and request.method in {"GET", "HEAD"}:
            return None
        supplied = request.headers.get("Authorization", "").encode("utf-8")
        expected = f"Bearer {token}".encode("utf-8")
        if not hmac.compare_digest(supplied, expected):
            return "", 401, {"WWW-Authenticate": "Bearer"}
        return None

    @app.errorhandler(HTTPException)
    def http_error(error):
        # Не возвращаем клиенту тело запроса, текст речи или внутренний traceback.
        return {"error": error.name}, error.code

    return app


def json_object(max_bytes: int | None = None) -> dict:
    """Flask разбирает JSON; здесь проверяется только контракт нашего API."""
    if max_bytes is not None:
        request.max_content_length = max_bytes
    if request.content_length is not None and request.content_length < 2:
        abort(413)
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        abort(400)
    return data


def require(condition: bool, status: int = 400) -> None:
    if not condition:
        abort(status)


def valid_call_id(value) -> bool:
    return isinstance(value, str) and CALL_ID.fullmatch(value) is not None


def run_api(app: Flask, host: str, port: int) -> None:
    """Один процесс владеет звонками; Waitress обслуживает HTTP в потоках."""
    serve(
        app,
        host=host,
        port=port,
        threads=int(os.environ["SERVICE_HTTP_THREADS"]),
        max_request_body_size=app.config["MAX_CONTENT_LENGTH"],
        expose_tracebacks=False,
    )


def request_json(method: str, url: str, *, payload=None, token=None, timeout=2):
    """HTTPX берёт на себя JSON и ошибки HTTP. Содержимое запросов не логируется."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = httpx.request(
        method, url, json=payload, headers=headers, timeout=timeout, trust_env=False
    )
    response.raise_for_status()
    return response.json() if response.content else None
