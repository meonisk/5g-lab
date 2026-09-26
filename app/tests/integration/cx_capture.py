"""Capture bounded, raw Cx traffic from PyHSS into a private Ethernet PCAP."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

# This code runs inside lab-pyhss. It records packets only; it does not infer
# Diameter messages or correlate them with a subscriber or call.
_CAPTURE_CODE = r"""
import select, socket, struct, sys, time

port = int(sys.argv[1])
duration = float(sys.argv[2])
sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
sock.setblocking(False)
out = sys.stdout.buffer
out.write(struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
out.flush()
print('CX_CAPTURE_READY', file=sys.stderr, flush=True)

def wanted(frame):
    if len(frame) < 34:
        return False
    kind = int.from_bytes(frame[12:14], 'big')
    offset = 14
    if kind in (0x8100, 0x88a8):
        if len(frame) < 38:
            return False
        kind = int.from_bytes(frame[16:18], 'big')
        offset = 18
    if kind != 0x0800 or len(frame) < offset + 20:
        return False
    ip = frame[offset:]
    ihl = (ip[0] & 15) * 4
    if ip[0] >> 4 != 4 or ihl < 20 or ip[9] != 6 or len(ip) < ihl + 4:
        return False
    if int.from_bytes(ip[6:8], 'big') & 0x1fff:
        return False
    source, destination = struct.unpack_from('!HH', ip, ihl)
    return source == port or destination == port

deadline = time.monotonic() + duration
while time.monotonic() < deadline:
    readable, _, _ = select.select([sock, sys.stdin.buffer], [], [], min(0.5, max(0, deadline - time.monotonic())))
    if sys.stdin.buffer in readable:
        if sys.stdin.buffer.read(1):
            break
        break
    if sock in readable:
        frame = sock.recv(65535)
        if wanted(frame):
            now = time.time()
            seconds = int(now)
            micros = int((now - seconds) * 1000000)
            out.write(struct.pack('<IIII', seconds, micros, len(frame), len(frame)))
            out.write(frame)
            out.flush()
sock.close()
"""


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            process.stdin.write(b"q")
            process.stdin.flush()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    if process.stdin:
        process.stdin.close()
    if process.stderr:
        process.stderr.close()


@contextmanager
def capture(path: Path, seconds: int = 150, port: int = 3868):
    """Yield a private PCAP path once capture is ready; stop it on scope exit."""
    if not 1 <= seconds <= 3600 or not 1 <= port <= 65535:
        raise ValueError("Invalid Cx capture duration or port")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    process = None
    timer = None
    ready_ok = False
    try:
        with os.fdopen(fd, "wb") as output:
            process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-i",
                    "lab-pyhss",
                    "python3",
                    "-u",
                    "-c",
                    _CAPTURE_CODE,
                    str(port),
                    str(seconds),
                ],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.PIPE,
            )
            ready = queue.Queue(maxsize=1)

            def drain_stderr():
                first = process.stderr.readline()
                ready.put(first)
                for _ in process.stderr:
                    pass

            reader = threading.Thread(target=drain_stderr, daemon=True)
            reader.start()
            try:
                line = ready.get(timeout=10)
            except queue.Empty as error:
                raise RuntimeError("Cx capture did not become ready") from error
            if line.strip() != b"CX_CAPTURE_READY":
                raise RuntimeError("Cx capture failed before readiness")
            ready_ok = True
            # Bound the host Docker CLI as well as the in-container raw socket.
            timer = threading.Timer(
                seconds + 5, lambda: process.kill() if process.poll() is None else None
            )
            timer.daemon = True
            timer.start()
            yield path
    finally:
        if timer is not None:
            timer.cancel()
        if process is not None:
            _stop(process)
        if not ready_ok:
            path.unlink(missing_ok=True)
