"""Диалоги SIP для вкладки «Звонки»: опрос lab-panel-sipcap и группировка по Call-ID."""

import collections
import json
import re
import threading
import time
import urllib.request

from . import docker, redact

HEADER = re.compile(r"(?im)^(from|f|to|t|cseq)\s*:\s*(.+?)\s*$")
USER = re.compile(r"(?i)<?(?:sips?|tel):([^@;>\s]+)")
COMPACT = {"f": "from", "t": "to"}


def first_line(text: str) -> str:
    return text.split("\n", 1)[0].strip()


def describe(message: dict) -> dict:
    """Метод или код ответа, CSeq, From/To — то, что нужно таблице и диаграмме."""
    line = first_line(message["text"])
    headers = {}
    for name, value in HEADER.findall(message["text"]):
        headers.setdefault(COMPACT.get(name.lower(), name.lower()), value)
    cseq_number, _, cseq_method = headers.get("cseq", "").partition(" ")
    if line.startswith("SIP/2.0"):
        parts = line.split(" ", 2)
        status, method = int(parts[1]), None
        label = " ".join(parts[1:])
    else:
        status, method = None, line.split(" ", 1)[0]
        label = method
    return {
        "status": status,
        "method": method,
        "label": label,
        "cseq": cseq_method.strip(),
        "cseq_number": cseq_number,
        "from": _user(headers.get("from", "")),
        "to": _user(headers.get("to", "")),
    }


def _user(value: str) -> str:
    match = USER.search(value)
    return match.group(1) if match else ""


def summarize(call_id: str, messages: list[dict]) -> dict:
    """Строка таблицы: первый запрос, итоговый ответ на него, длительность."""
    described = [(m, describe(m)) for m in messages]
    request = next((d for _, d in described if d["method"]), described[0][1])
    method = request["method"] or request["cseq"]
    # Последний окончательный ответ на этот метод: у REGISTER 401 и затем 200 -> 200.
    finals = [
        d["status"] for _, d in described if (d["status"] or 0) >= 200 and d["cseq"] == method
    ]
    final = finals[-1] if finals else None
    return {
        "call_id": call_id,
        "method": method,
        "from": request["from"],
        "to": request["to"],
        "start": messages[0]["t"],
        "end": messages[-1]["t"],
        "count": len(messages),
        "final": final,
        "bye": any(d["method"] == "BYE" for _, d in described),
    }


class Calls:
    def __init__(self, url: str, limit: int = 20000):
        self.url = url
        self.messages: collections.deque = collections.deque(maxlen=limit)
        self.cursor = 0
        self.lock = threading.Lock()
        self.online = False
        self.names: dict[str, str] = {}
        self.names_checked = 0.0
        self.listeners: list = []  # функции, получающие новые сообщения (метрики)

    def poll_forever(self, interval: float = 1.0) -> None:
        while True:
            try:
                self.poll()
            except Exception:  # noqa: BLE001 — sipcap мог перезапускаться; повтор
                self.online = False
            time.sleep(interval)

    def poll(self) -> None:
        with urllib.request.urlopen(f"{self.url}/messages?since={self.cursor}", timeout=3) as r:
            body = json.load(r)
        if body["next"] <= self.cursor and self.cursor:
            self.cursor = 0  # sipcap перезапустился: номера начались заново
        fresh = body["messages"]
        with self.lock:
            self.messages.extend(fresh)
        if fresh:
            self.cursor = fresh[-1]["seq"]
        self.online = True
        for listener in self.listeners:
            listener(fresh)

    def address_names(self) -> dict[str, str]:
        if time.monotonic() - self.names_checked > 30:
            self.names = docker.addresses()
            self.names_checked = time.monotonic()
        return self.names

    def grouped(self) -> dict[str, list[dict]]:
        with self.lock:
            snapshot = list(self.messages)
        groups: dict[str, list[dict]] = {}
        for message in snapshot:
            groups.setdefault(message["call_id"], []).append(message)
        return groups

    def list(self, kind: str = "calls", limit: int = 300) -> list[dict]:
        rows = [summarize(call_id, items) for call_id, items in self.grouped().items()]
        if kind == "calls":
            rows = [row for row in rows if row["method"] == "INVITE"]
        elif kind == "register":
            rows = [row for row in rows if row["method"] == "REGISTER"]
        elif kind == "other":
            rows = [row for row in rows if row["method"] not in ("INVITE", "REGISTER")]
        return sorted(rows, key=lambda row: row["start"], reverse=True)[:limit]

    def dialog(self, call_id: str) -> dict | None:
        items = self.grouped().get(call_id)
        if not items:
            return None
        names = self.address_names()
        messages = []
        for message in items:
            src_ip, dst_ip = message["src"].rsplit(":", 1)[0], message["dst"].rsplit(":", 1)[0]
            messages.append(
                {
                    **describe(message),
                    "t": message["t"],
                    "seq": message["seq"],
                    "src": message["src"],
                    "dst": message["dst"],
                    "src_name": names.get(src_ip, ""),
                    "dst_name": names.get(dst_ip, ""),
                    "text": redact.sip_text(message["text"]),
                }
            )
        return {"summary": summarize(call_id, items), "messages": messages}
