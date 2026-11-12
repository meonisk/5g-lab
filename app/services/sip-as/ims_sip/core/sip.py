"""Разбор SIP без состояния: заголовки (полные и компактные имена), tag, Route, CSeq."""

import hashlib
import re
import time


def header(message: str, name: str) -> str:
    match = re.search(rf"(?im)^{re.escape(name)}\s*:\s*(.+)$", message)
    return match.group(1).strip() if match else ""


def all_headers(message: str, long_name: str, compact_name: str | None = None) -> list[str]:
    names = re.escape(long_name)
    if compact_name:
        names += "|" + re.escape(compact_name)
    # ``.`` захватывает и CR строки CRLF; оставленный, он дал бы ``\r\r\n`` в
    # локальном ответе, и Kamailio отверг бы обязательные заголовки.
    return [line.rstrip("\r") for line in re.findall(rf"(?im)^((?:{names})\s*:\s*.+)$", message)]


def request_method(message: str) -> str:
    return message.split("\r\n", 1)[0].split(" ", 1)[0]


def message_call_id(message: str) -> str:
    return header(message, "Call-ID") or header(message, "i")


def local_tag(call_id: str) -> str:
    """Детерминированный tag позволяет одинаково отвечать на retransmit."""
    return hashlib.sha256(call_id.encode()).hexdigest()[:16]


def transaction_branch(message: str) -> str:
    """Поддержать полное и компактное имя SIP-заголовка Via."""
    branch_match = re.search(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=([^;\s]+)", message)
    return branch_match.group(1) if branch_match else str(time.time_ns())


COMPACT = {"Call-ID": "i", "From": "f", "To": "t", "Via": "v", "Contact": "m", "Content-Type": "c"}


def value_of(message: str, name: str) -> str:
    """Значение заголовка только из части заголовков; компактное имя тоже подходит."""
    head = message.split("\r\n\r\n", 1)[0]
    return header(head, name) or (header(head, COMPACT[name]) if name in COMPACT else "")


def request_uri(message: str) -> str:
    return message.split("\r\n", 1)[0].split(" ")[1]


def route_values(message: str, name: str = "Route") -> list[str]:
    """Все значения <...> заголовка по порядку: и через запятую, и отдельными строками."""
    head = message.split("\r\n\r\n", 1)[0]
    return [value for line in all_headers(head, name) for value in re.findall(r"<[^>]+>", line)]


def top_route_host(message: str) -> str:
    """Хост первого Route: по нему S-CSCF адресует логический AS из iFC."""
    routes = route_values(message)
    match = re.match(r"<sips?:(?:[^@>]+@)?([^:;>]+)", routes[0]) if routes else None
    return match.group(1).lower() if match else ""


def tag_of(value: str) -> str:
    match = re.search(r";tag=([^;>\s]+)", value)
    return match.group(1) if match else ""


def status_code(message: str) -> int:
    return int(message.split(" ", 2)[1])


def angle_uri(value: str) -> str:
    """URI из <...> заголовка Contact/To; без скобок — до первого параметра."""
    match = re.search(r"<([^>]+)>", value)
    return match.group(1) if match else value.split(";", 1)[0].strip()


def cseq_method(message: str) -> str:
    value = header(message.split("\r\n\r\n", 1)[0], "CSeq")
    return value.split()[-1].upper() if value else ""
