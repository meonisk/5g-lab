"""Download the pinned public voice at image build time, never during a call."""

import hashlib
import os
from pathlib import Path
from urllib.request import urlopen


def download_voice(prefix):
    destination = Path(os.environ[f"{prefix}_MODEL_PATH"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    base_url = os.environ[f"{prefix}_MODEL_URL"]

    for suffix, digest_name in (
        ("", f"{prefix}_MODEL_SHA256"),
        (".json", f"{prefix}_CONFIG_SHA256"),
    ):
        with urlopen(base_url + suffix, timeout=120) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != os.environ[digest_name]:
            raise ValueError(f"Piper asset checksum mismatch: {suffix or 'model'}")
        Path(str(destination) + suffix).write_bytes(content)


if __name__ == "__main__":
    for prefix in ("PIPER", "PIPER_EN"):
        download_voice(prefix)
