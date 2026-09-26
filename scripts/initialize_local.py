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
        ]
        for ue in (1, 2):
            for domain in ("5GS", "IMS"):
                lines.extend(
                    (
                        f"UE{ue}_{domain}_K={secrets.token_hex(16).upper()}",
                        f"UE{ue}_{domain}_OPC={secrets.token_hex(16).upper()}",
                        f"UE{ue}_{domain}_AMF=8000",
                    )
                )
        SECRET_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("Created private laboratory credentials in local/secrets/ims.env")

    values = read_values(SECRET_PATH)
    for ue in (1, 2):
        for domain in ("5GS", "IMS"):
            prefix = f"UE{ue}_{domain}"
            names = (f"{prefix}_K", f"{prefix}_OPC", f"{prefix}_AMF")
            legacy = ("SUBSCRIBER_K", "SUBSCRIBER_OPC", "SUBSCRIBER_AMF")
            selected = names if any(name in values for name in names) else legacy
            for name, length in zip(selected, (32, 32, 4), strict=True):
                if not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", values.get(name, "")):
                    raise ValueError(f"{name} must contain exactly {length} hexadecimal characters")
    if not values.get("IMS_DIGEST_PASSWORD", "").strip() or values[
        "IMS_DIGEST_PASSWORD"
    ].startswith("replace-"):
        raise ValueError("IMS_DIGEST_PASSWORD must be a non-placeholder value")
    (ROOT / "local/private/recordings").mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    main()
