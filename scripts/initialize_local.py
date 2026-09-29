"""Create and validate local credentials without exposing them in Git or logs."""

import argparse
import re
import secrets
from pathlib import Path

from oai_config import render

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATH = ROOT / "local/secrets/ims.env"


def read_values(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def main(ims_only=False):
    domains = ("IMS",) if ims_only else ("5GS", "IMS")
    if not SECRET_PATH.exists():
        SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"IMS_DIGEST_PASSWORD={secrets.token_hex(16).upper()}",
        ]
        for ue in (1, 2):
            for domain in domains:
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
    added = []
    for name in () if ims_only else ("OAI_DB_PASSWORD", "OAI_DB_ROOT_PASSWORD"):
        if not values.get(name):
            values[name] = secrets.token_hex(24)
            added.append(f"{name}={values[name]}")
        if not re.fullmatch(r"[0-9a-fA-F]{48}", values[name]):
            raise ValueError(f"{name} must contain 48 hexadecimal characters")
    if added:
        with SECRET_PATH.open("a", encoding="utf-8", newline="\n") as output:
            output.write("\n" + "\n".join(added) + "\n")
    for ue in (1, 2):
        for domain in domains:
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
    if not ims_only:
        public = read_values(ROOT / "app/config/lab.env")
        render(ROOT, {**public, **values})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ims-only", action="store_true")
    main(ims_only=parser.parse_args().ims_only)
