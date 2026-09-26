"""Read-only proof that a UE network namespace owns an exact UDP bind."""

from __future__ import annotations

import ipaddress
import subprocess


class SocketEvidenceError(RuntimeError):
    """The proc table was unavailable, malformed, or did not prove the bind."""


def bound_count(proc_udp: str, local_ip: str, local_port: int) -> int:
    """Count exact IPv4 UDP sockets, excluding wildcard and other interface binds."""
    target = ipaddress.IPv4Address(local_ip)
    if not 1 <= local_port <= 65535:
        raise ValueError("Invalid UDP port")
    lines = proc_udp.splitlines()
    if not lines or "local_address" not in lines[0]:
        raise SocketEvidenceError("Linux UDP proc table header is missing")
    count = 0
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 2 or not fields[0].endswith(":"):
            raise SocketEvidenceError("Malformed UDP proc row")
        try:
            address_hex, port_hex = fields[1].split(":")
            if len(address_hex) != 8 or len(port_hex) != 4:
                raise ValueError
            address = ipaddress.IPv4Address(bytes.fromhex(address_hex)[::-1])
            port = int(port_hex, 16)
        except ValueError:
            raise SocketEvidenceError("Malformed UDP local endpoint") from None
        count += address == target and port == local_port
    return count


def require_exact_bind(container: str, local_ip: str, local_port: int, timeout: int = 10) -> dict:
    """Read the container's namespace and require one exact non-wildcard bind."""
    try:
        call = subprocess.run(
            ["docker", "exec", container, "cat", "/proc/net/udp"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SocketEvidenceError("UDP socket table unavailable") from None
    if call.returncode:
        raise SocketEvidenceError("UDP socket table read failed")
    count = bound_count(call.stdout, local_ip, local_port)
    if count != 1:
        raise SocketEvidenceError("Expected exact UDP bind was not unique")
    return {"local_ip": local_ip, "local_port": local_port, "exact_bind_count": count}
