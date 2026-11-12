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
