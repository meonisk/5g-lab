"""Copy a fresh stopped MySQL datadir into the persistent Compose volume.

Stop the lab first. This tool retains a cold backup and local rollback image;
it never stops, renames, deletes, or starts a container.
"""

import argparse
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

VOLUME = "lab-docker_mysql-data"
CONTAINER = "lab-mysql"
ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "local/private/mysql-storage-migration.json"


def checked(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def stopped_container_id():
    result = checked(
        ["docker", "inspect", CONTAINER, "--format", "{{.Id}}|{{.State.Status}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    container_id, state = result.split("|", 1)
    if state != "exited":
        raise RuntimeError(f"{CONTAINER} must be stopped; current state: {state}")
    return container_id


def validate_backup(directory):
    directory = directory.resolve(strict=True)
    if not directory.is_dir() or not (directory / "ibdata1").is_file():
        raise RuntimeError("Backup must be a MySQL datadir containing ibdata1")
    if not (directory / "mysql").is_dir() or not (directory / "ims_hss_db").is_dir():
        raise RuntimeError("Backup lacks mysql or ims_hss_db database directory")
    return directory


def require_new_volume():
    found = subprocess.run(
        ["docker", "volume", "inspect", VOLUME],
        capture_output=True,
        check=False,
    )
    if found.returncode == 0:
        raise RuntimeError(f"{VOLUME} already exists; refusing to overwrite it")


def require_new_backup(directory):
    directory = directory.resolve()
    if not directory.is_relative_to((ROOT / "local/private").resolve()):
        raise RuntimeError("Backup directory must be under local/private")
    if directory.exists() or RECEIPT.exists():
        raise RuntimeError("Backup directory or migration receipt already exists")
    return directory


def capture_backup(directory):
    directory.parent.mkdir(parents=True, exist_ok=True)
    checked(["docker", "cp", f"{CONTAINER}:/var/lib/mysql/.", str(directory)])
    return validate_backup(directory)


def commit_rollback_image():
    tag = f"lab-mysql-rollback:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    image_id = checked(
        ["docker", "commit", CONTAINER, tag], capture_output=True, text=True
    ).stdout.strip()
    return tag, image_id


def copy_backup(directory):
    checked(
        [
            "docker",
            "volume",
            "create",
            "--label",
            "com.docker.compose.project=lab-docker",
            "--label",
            "com.docker.compose.volume=mysql-data",
            VOLUME,
        ],
        stdout=subprocess.DEVNULL,
    )
    helper = subprocess.Popen(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--mount",
            f"type=volume,source={VOLUME},target=/target",
            "alpine:3.20",
            "sh",
            "-ec",
            "tar -xpf - -C /target && chown -R 101:101 /target",
        ],
        stdin=subprocess.PIPE,
    )
    try:
        with tarfile.open(fileobj=helper.stdin, mode="w|") as archive:
            for entry in directory.iterdir():
                archive.add(entry, arcname=entry.name)
    finally:
        helper.stdin.close()
    if helper.wait() != 0:
        raise RuntimeError(f"Copy failed; {CONTAINER} is untouched. Inspect {VOLUME} before retry")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    directory = require_new_backup(arguments.backup_dir)
    source_id = stopped_container_id()
    require_new_volume()
    if not arguments.apply:
        print("PREFLIGHT PASS: stopped legacy MySQL and new private backup path")
        return
    capture_backup(directory)
    rollback_tag, rollback_id = commit_rollback_image()
    copy_backup(directory)
    if stopped_container_id() != source_id:
        raise RuntimeError("MySQL container changed during migration; refusing receipt")
    receipt = {
        "source_container_id": source_id,
        "volume": VOLUME,
        "backup_dir": str(directory),
        "rollback_image": rollback_tag,
        "rollback_image_id": rollback_id,
    }
    temporary = RECEIPT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(RECEIPT)
    print(f"MIGRATED: {VOLUME} populated; rollback image {rollback_tag} retained")
    print("The next Compose up may recreate lab-mysql; verify databases and IMS gates")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        raise SystemExit(f"ERROR: {error}") from error
