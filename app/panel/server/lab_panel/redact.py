"""Что панель не показывает: ключи и одноразовые значения аутентификации.

SIP-сообщения показываются целиком, но значения nonce/response/cnonce/opaque,
ключи IPsec (ck/ik) и ключи SRTP заменяются на «***». Строки журналов, похожие на
ключи (Ki, OPc, RAND, AUTN, пароли), скрываются целиком — тот же список, что у
scripts/stand_check.py collect.
"""

import re

MASK = "***"

# Параметры заголовков Authorization / WWW-Authenticate / Security-*; кавычки сохраняются.
SIP_PARAMETER = re.compile(
    r'(?i)\b(nonce|response|cnonce|opaque|nextnonce|rspauth|ck|ik|auts)\s*=\s*("[^"]*"|[^\s,;]+)'
)
# SDP: a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:<ключ>
SDP_KEY = re.compile(r"(?i)(inline:)[^\s|]+")
LOG_SECRET = re.compile(
    r"(?i)(nonce|response=|\bck=|\bik=|opc|\bki\b|authorization|password|\brand\b|\bautn\b|\bsqn\b)"
)
# Цвета терминала в журналах Kamailio: в браузере это мусор.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HIDDEN_LINE = "[строка скрыта: похожа на ключ]"


def _mask(match: re.Match) -> str:
    value = match.group(2)
    return f"{match.group(1)}=" + (f'"{MASK}"' if value.startswith('"') else MASK)


def sip_text(text: str) -> str:
    """Текст SIP-сообщения для показа: структура та же, секреты заменены."""
    return SDP_KEY.sub(rf"\1{MASK}", SIP_PARAMETER.sub(_mask, text))


def log_line(line: str) -> str:
    line = ANSI.sub("", line)
    return HIDDEN_LINE if LOG_SECRET.search(line) else line
