"""Захват SIP для панели стенда: UDP SIP со всех интерфейсов хоста, буфер в памяти.

Запускается в контейнере с network_mode: host и единственной способностью NET_RAW.
Сокет AF_PACKET/SOCK_DGRAM отдаёт пакеты без заголовка канального уровня; берутся
IPv4/UDP с SIP внутри. Один пакет виден на veth и на мосту Docker (и дважды на lo),
поэтому повтор в течение DEDUP_SECONDS отбрасывается. Фрагменты IP и TCP не
разбираются. HTTP — только 127.0.0.1: GET /messages?since=N отдаёт новые сообщения.
Текст сообщений здесь не скрывается: это делает сервер панели перед показом.
"""

import collections
import hashlib
import http.server
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.parse

ETH_P_ALL = 0x0003
ETH_P_IP = 0x0800
DEDUP_SECONDS = 2.0
SIP_START = re.compile(rb"^(?:SIP/2\.0 \d{3} |[A-Z]{3,10} \S+ SIP/2\.0\r?\n)")
CALL_ID = re.compile(r"(?im)^(?:call-id|i)\s*:\s*(\S+)")


def parse_packet(data: bytes) -> dict | None:
    """IPv4-пакет -> адреса, порты и текст SIP; None, если это не целый UDP SIP."""
    if len(data) < 28 or data[0] >> 4 != 4:
        return None
    header = (data[0] & 0x0F) * 4
    total, ident, fragment, _, protocol = struct.unpack("!HHHBB", data[2:10])
    if protocol != 17 or fragment & 0x3FFF:  # не UDP или фрагмент
        return None
    total = min(total, len(data))
    source_port, destination_port = struct.unpack("!HH", data[header : header + 4])
    payload = data[header + 8 : total]
    if not SIP_START.match(payload):
        return None
    text = payload.decode("utf-8", errors="replace")
    match = CALL_ID.search(text)
    return {
        "src": f"{socket.inet_ntoa(data[12:16])}:{source_port}",
        "dst": f"{socket.inet_ntoa(data[16:20])}:{destination_port}",
        "ident": ident,
        "call_id": match.group(1) if match else "",
        "text": text,
    }


class Deduplicator:
    def __init__(self, seconds: float = DEDUP_SECONDS):
        self.seconds = seconds
        self.seen: dict[tuple, float] = {}

    def fresh(self, message: dict, now: float) -> bool:
        if len(self.seen) > 5000:
            self.seen = {k: t for k, t in self.seen.items() if now - t < self.seconds}
        digest = hashlib.blake2b(message["text"].encode(), digest_size=8).digest()
        key = (message["src"], message["dst"], message["ident"], digest)
        last = self.seen.get(key)
        self.seen[key] = now
        return last is None or now - last >= self.seconds


class Store:
    """Кольцевой буфер с номерами: клиент забирает всё после своего последнего номера."""

    def __init__(self, limit: int):
        self.items: collections.deque = collections.deque(maxlen=limit)
        self.next = 1
        self.lock = threading.Lock()

    def add(self, message: dict) -> None:
        with self.lock:
            message["seq"] = self.next
            self.next += 1
            self.items.append(message)

    def since(self, seq: int, limit: int = 2000) -> list[dict]:
        with self.lock:
            return [m for m in self.items if m["seq"] > seq][:limit]


def capture(store: Store) -> None:
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETH_P_ALL))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    dedup = Deduplicator()
    while True:
        data, address = sock.recvfrom(65535)
        if address[1] != ETH_P_IP:
            continue
        message = parse_packet(data)
        now = time.time()
        if message and dedup.fresh(message, now):
            message.pop("ident")
            message["t"] = now
            store.add(message)


def handler_for(store: Store):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/healthz":
                return self.reply({"ok": True})
            if url.path != "/messages":
                return self.reply({"error": "not found"}, 404)
            query = urllib.parse.parse_qs(url.query)
            try:
                since = int(query.get("since", ["0"])[0])
            except ValueError:
                return self.reply({"error": "since"}, 400)
            return self.reply({"next": store.next, "messages": store.since(since)})

        def reply(self, body, status=200):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # без журнала запросов: панель опрашивает раз в секунду

    return Handler


def main() -> None:
    store = Store(int(os.environ.get("PANEL_SIPCAP_MESSAGES", "20000")))
    threading.Thread(target=capture, args=(store,), daemon=True).start()
    port = int(os.environ["PANEL_SIPCAP_PORT"])
    print(f"SIPCAP listening 127.0.0.1:{port}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler_for(store)).serve_forever()


if __name__ == "__main__":
    main()
