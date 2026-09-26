"""Exclusive stand ownership and bounded gate processes for research capture."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path

from .common import utc_now


class StandLock:
    """OS-owned lock: process death releases ownership without deleting stale files."""

    def __init__(self, root: Path):
        self.path = root / "local/evidence/stand.lock"
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"\0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError("stand is owned by another evidence collector") from exc
        return self

    def __exit__(self, *_):
        self.stream.close()


def stop_process(process: subprocess.Popen) -> None:
    # Gates spawn shell children. Killing only the shell can leave a live stimulus.
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_gate(root: Path, gate: dict, timeout: float) -> tuple[dict, str]:
    args = list(gate["command"])
    if args[0] == "bash":
        windows_bash = Path("C:/Program Files/Git/bin/bash.exe")
        args[0] = str(windows_bash) if windows_bash.exists() else shutil.which("bash") or "bash"
    record = {"id": gate["id"], "started_at_utc": utc_now(), "returncode": None}
    try:
        process = subprocess.Popen(
            args,
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
    except OSError:
        return {**record, "status": "ERROR", "finished_at_utc": utc_now()}, "gate launch failed"
    status = "COMPLETED"
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        status = "TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else "INTERRUPTED"
        stop_process(process)
        stdout, stderr = process.communicate(timeout=15)
    record.update(status=status, returncode=process.returncode, finished_at_utc=utc_now())
    return record, stdout + ("\n" + stderr if stderr else "")
