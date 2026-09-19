"""Create and validate local credentials without exposing them in Git or logs."""

import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATH = ROOT / "local/secrets/ims.env"


def read_values(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def main():
    if not SECRET_PATH.exists():
        SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"IMS_DIGEST_PASSWORD={secrets.token_hex(16).upper()}",
            f"SUBSCRIBER_K={secrets.token_hex(16).upper()}",
            f"SUBSCRIBER_OPC={secrets.token_hex(16).upper()}",
            "SUBSCRIBER_AMF=8000",
        ]
        SECRET_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("Created private laboratory credentials in local/secrets/ims.env")

    values = read_values(SECRET_PATH)
    for name in ("SUBSCRIBER_K", "SUBSCRIBER_OPC"):
        if not re.fullmatch(r"[0-9a-fA-F]{32}", values.get(name, "")):
            raise ValueError(f"{name} must contain exactly 32 hexadecimal characters")
    if not values.get("IMS_DIGEST_PASSWORD", "").strip() or values[
        "IMS_DIGEST_PASSWORD"
    ].startswith("replace-"):
        raise ValueError("IMS_DIGEST_PASSWORD must be a non-placeholder value")
    if not re.fullmatch(r"[0-9a-fA-F]{4}", values.get("SUBSCRIBER_AMF", "")):
        raise ValueError("SUBSCRIBER_AMF must contain four hexadecimal characters")

    (ROOT / "local/private/recordings").mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()
