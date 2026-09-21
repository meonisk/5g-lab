"""Check Git publication hygiene; report locations, never credential values."""

import argparse
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_PARTS = {"local", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache"}
PRIVATE_SUFFIXES = {
    ".wav",
    ".flac",
    ".mp3",
    ".ogg",
    ".pcap",
    ".pcapng",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".bundle",
    ".zip",
}
SIGNATURE = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    rb"gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}"
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def private_path(name, *, historical=False):
    path = PurePosixPath(name)
    public_envs = {"app/config/lab.env"}
    if historical:
        public_envs.add("lab.env")  # Public configuration before the layout migration.
    return (
        bool(PRIVATE_PARTS.intersection(path.parts))
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or (path.name.endswith(".env") and name not in public_envs)
        or path.name.startswith(".env.")
        and not path.name.endswith(".example")
        or name == "docs/hardening/context.local.md"
    )


def local_credentials():
    path = ROOT / "local/secrets/ims.env"
    if not path.exists():
        return []
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 16 and not value.startswith("replace-"):
                values.append(value.encode())
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="Scan all reachable refs")
    args = parser.parse_args()
    errors = []
    objects = {}
    records = git("ls-files", "--stage", "-z").decode().split("\0")
    for record in filter(None, records):
        metadata, name = record.split("\t", 1)
        mode, oid, stage = metadata.split()
        objects[oid] = name
        if stage != "0":
            errors.append(f"{name}: unresolved merge")
        if name.endswith(".sh") and mode != "100755":
            errors.append(f"{name}: missing executable Git mode")
        if private_path(name):
            errors.append(f"{name}: private/generated file in index")

    if args.history:
        for record in git("rev-list", "--objects", "--all").decode().splitlines():
            oid, separator, name = record.partition(" ")
            if separator:
                objects.setdefault(oid, name)
                if private_path(name, historical=True):
                    errors.append(f"{name}: private/generated path in history")

    credentials = local_credentials()
    # A single batch avoids starting one Git process for every historical blob.
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        input=("\n".join(objects) + "\n").encode(),
        capture_output=True,
        check=True,
    ).stdout
    offset = 0
    checked = 0
    for oid, name in objects.items():
        end = result.index(b"\n", offset)
        header = result[offset:end].split()
        size = int(header[2])
        data = result[end + 1 : end + 1 + size]
        offset = end + size + 2
        if header[1] != b"blob":
            continue
        checked += 1
        if size > 10 * 1024 * 1024:
            errors.append(f"{name} ({oid[:12]}): blob exceeds 10 MiB")
        if SIGNATURE.search(data) or any(value in data for value in credentials):
            errors.append(f"{name} ({oid[:12]}): credential match; value redacted")
    if errors:
        raise SystemExit("\n".join(sorted(set(errors))))
    scope = "index and reachable history" if args.history else "index"
    print(f"GIT PUBLICATION HYGIENE: PASS ({scope}, {checked} blobs)")


if __name__ == "__main__":
    main()
