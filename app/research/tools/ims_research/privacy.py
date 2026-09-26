"""Within-run pseudonyms and private-key placement."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

from .common import (
    CALL_ID_RE,
    CALL_LIST_RE,
    IDENTITY_KEY_RE,
    IMSI_RE,
    SECRET_KEY_RE,
    SIP_RE,
    parse_env,
)
from .protocol_privacy import sanitize_protocol_log


class Pseudonymizer:
    def __init__(self, key: bytes, exact: dict[str, str]):
        self.key = key
        self.exact = {v: self.alias(k.lower(), v) for k, v in exact.items() if len(v) >= 4}

    def alias(self, kind: str, value: str) -> str:
        digest = hmac.new(self.key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:12]
        return f"<{kind}:{digest}>"

    def text(self, value: str) -> str:
        for raw in sorted(self.exact, key=len, reverse=True):
            value = value.replace(raw, self.exact[raw])
        value = IMSI_RE.sub(lambda m: self.alias("subscriber", m.group(0)), value)
        value = SIP_RE.sub(
            lambda m: m.group(1) + self.alias("sip-user", m.group(2)) + m.group(3),
            value,
        )
        value = CALL_ID_RE.sub(lambda m: m.group(1) + self.alias("call-id", m.group(2)), value)
        value = CALL_LIST_RE.sub(self._call_list, value)
        return value

    def shareable_log(self, value: str, source: str = "") -> str:
        # Protocol dumps are reduced before identifier pseudonymization because
        # authentication and media fields are not reliably token-shaped.
        return self.text(sanitize_protocol_log(value, source))

    def _call_list(self, match: re.Match[str]) -> str:
        body = re.sub(
            r"[A-Za-z0-9_.+~@-]{4,}",
            lambda m: self.alias("call-id", m.group(0)),
            match.group(2),
        )
        return match.group(1) + body + match.group(3)


def private_key_path(root: Path, run_id: str) -> Path:
    return root / "local/evidence" / "private" / f"{run_id}.pseudonym.key"


def sensitive_values(root: Path) -> tuple[dict[str, str], list[str]]:
    exact: dict[str, str] = {}
    secrets_for_scan: list[str] = []
    for path in (root / "app/config/lab.env", root / "local/secrets" / "ims.env"):
        for key, value in parse_env(path).items():
            if IDENTITY_KEY_RE.search(key):
                exact[key] = value
            if SECRET_KEY_RE.search(key) and len(value) >= 8:
                exact[key] = value
                secrets_for_scan.append(value)
    return exact, secrets_for_scan
