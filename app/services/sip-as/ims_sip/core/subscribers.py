"""Абоненты для SIP AS: язык по MSISDN/IMSI из lab.env, обслуживаемый и вызываемый номер."""

import re

from .sip import request_uri, value_of

PROFILES = ("UE1", "UE2", "SIPUE1", "SIPUE2")
LANGUAGES = ("ru", "en")


def language_table(environ) -> dict[str, str]:
    """MSISDN и IMSI каждого абонента -> язык; не задан — DEFAULT_LANGUAGE."""
    default = environ.get("DEFAULT_LANGUAGE") or "ru"
    if default not in LANGUAGES:
        raise ValueError(f"DEFAULT_LANGUAGE={default}: допустимы {', '.join(LANGUAGES)}")
    table = {}
    for prefix in PROFILES:
        language = environ.get(f"{prefix}_LANGUAGE") or default
        if language not in LANGUAGES:
            raise ValueError(f"{prefix}_LANGUAGE={language}: допустимы {', '.join(LANGUAGES)}")
        for key in (f"{prefix}_MSISDN", f"{prefix}_IMSI"):
            if environ.get(key):
                table[environ[key]] = language
    return table


def uri_user(value: str) -> str:
    match = re.search(r"(?:sips?|tel):([^@;>\s]+)", value)
    return match.group(1) if match else ""


def served_user(message: str) -> str:
    """Обслуживаемый абонент: P-Served-User от S-CSCF, иначе From."""
    return uri_user(value_of(message, "P-Served-User") or value_of(message, "From"))


def target_user(message: str) -> str:
    return uri_user(request_uri(message))


def language_for(user: str, table: dict[str, str], default: str) -> str:
    return table.get(user, default)
