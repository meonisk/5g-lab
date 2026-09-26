"""Bounded UERANSIM CLI registry inspection and explicit stale-record quarantine."""

from __future__ import annotations

import re
import subprocess
import uuid

TABLE = "/tmp/UERANSIM.proc-table"
QUARANTINE = "/tmp/UERANSIM.proc-table-quarantine"
SNAPSHOT = r"""
set -eu
count=0
for comm in /proc/[0-9]*/comm; do
    [ "$(cat "$comm")" = nr-ue ] || continue
    pid=${comm#/proc/}; pid=${pid%/comm}
    count=$((count + 1))
    start=$(awk '{print $22}' "/proc/$pid/stat")
    command=$(tr '\000' ' ' < "/proc/$pid/cmdline")
    printf 'PROC\t%s\t%s\t%s\n' "$pid" "$start" "$command"
    for fd in /proc/"$pid"/fd/*; do
        link=$(readlink "$fd" 2>/dev/null || true)
        case "$link" in socket:\[*\]) printf 'FD\t%s\n' "${link#socket:[}" | tr -d ']' ;; esac
    done
done
[ "$count" -eq 1 ] || exit 42
awk 'NR>1 {print "UDP\t" $2 "\t" $10}' /proc/net/udp
for file in /tmp/UERANSIM.proc-table/*; do
    [ -f "$file" ] && [ ! -L "$file" ] || continue
    name=${file##*/}
    size=$(stat -c %s "$file")
    [ "$size" -le 256 ] || exit 43
    hash=$(sha256sum "$file" | cut -d ' ' -f1)
    record=$(cat "$file")
    printf 'FILE\t%s\t%s\t%s\n' "$name" "$hash" "$record"
done
"""
MOVE = r"""
set -eu
node=$1; pid=$2; start=$3; active_port=$4; target=$5
shift 5
[ "$(cat "/proc/$pid/comm")" = nr-ue ] || exit 51
[ "$(tr '\000' ' ' < "/proc/$pid/cmdline")" = 'nr-ue -c ue.yaml ' ] || exit 51
[ "$(awk '{print $22}' "/proc/$pid/stat")" = "$start" ] || exit 52
hex=$(printf '%04X' "$active_port")
inode=$(awk -v local="0100007F:$hex" 'NR>1 && $2==local {print $10}' /proc/net/udp)
[ -n "$inode" ] || exit 53
owned=0
for fd in /proc/"$pid"/fd/*; do
    [ "$(readlink "$fd" 2>/dev/null || true)" = "socket:[$inode]" ] && owned=1
done
[ "$owned" -eq 1 ] || exit 54
for item do
    name=${item%%:*}; expected=${item#*:}
    file=/tmp/UERANSIM.proc-table/$name
    [ -f "$file" ] && [ ! -L "$file" ] || exit 55
    [ "$(sha256sum "$file" | cut -d ' ' -f1)" = "$expected" ] || exit 56
    record=$(cat "$file")
    rec_pid=$(printf '%s\n' "$record" | awk '{print $4}')
    rec_node=$(printf '%s\n' "$record" | awk '{print $7}')
    port=$(printf '%s\n' "$record" | awk '{print $5}')
    [ "$rec_pid" = "$pid" ] && [ "$rec_node" = "$node" ] || exit 57
    stale_hex=$(printf '%04X' "$port")
    stale_inode=$(awk -v local="0100007F:$stale_hex" 'NR>1 && $2==local {print $10}' /proc/net/udp)
    if [ -n "$stale_inode" ]; then
        for fd in /proc/"$pid"/fd/*; do
            [ "$(readlink "$fd" 2>/dev/null || true)" = "socket:[$stale_inode]" ] && exit 58
        done
    fi
done
[ ! -e "$target" ] || exit 59
mkdir -p "$target"
for item do
    name=${item%%:*}
    mv -- "/tmp/UERANSIM.proc-table/$name" "$target/$name"
    printf 'MOVED\t%s\n' "$name"
done
"""


class RegistryError(RuntimeError):
    """CLI registry is ambiguous or changed during an attempted quarantine."""


def _docker(container: str, script: str, *args: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
        raise RegistryError("Invalid container name")
    try:
        result = subprocess.run(
            ["docker", "exec", container, "sh", "-c", script, "sh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RegistryError("UERANSIM registry inspection timed out") from None
    if result.returncode:
        raise RegistryError(f"UERANSIM registry operation failed ({result.returncode})")
    return result.stdout


def classify_registry(snapshot: str, node: str) -> dict:
    """Use exact node, process start, FD inodes and UDP ports; fail on ambiguity."""
    if not re.fullmatch(r"imsi-[0-9]{5,16}", node):
        raise RegistryError("Invalid UE node name")
    process = []
    fds = set()
    udp = {}
    files = []
    for line in snapshot.splitlines():
        parts = line.split("\t")
        if parts[0] == "PROC" and len(parts) == 4:
            process.append((parts[1], parts[2], parts[3]))
        elif parts[0] == "FD" and len(parts) == 2:
            fds.add(parts[1])
        elif parts[0] == "UDP" and len(parts) == 3:
            if parts[1].startswith("0100007F:"):
                udp.setdefault(int(parts[1].split(":")[1], 16), set()).add(parts[2])
        elif parts[0] == "FILE" and len(parts) == 4:
            files.append(parts[1:])
        else:
            raise RegistryError("Malformed registry snapshot")
    if len(process) != 1 or not all(re.fullmatch(r"[0-9]+", x) for x in process[0][:2]):
        raise RegistryError("Expected exactly one current nr-ue")
    pid, start, command = process[0]
    if command != "nr-ue -c ue.yaml ":
        raise RegistryError("Unexpected current nr-ue command")
    candidates = []
    for name, digest, record in files:
        fields = record.split()
        if len(fields) != 7 or fields[6] != node:
            continue
        if not re.fullmatch(r"[0-9a-f]{32}", name) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RegistryError("Invalid registry filename or hash")
        if fields[:3] != ["3", "2", "6"] or fields[5] != "1" or fields[3] != pid:
            raise RegistryError("Registry record does not bind current nr-ue")
        if not fields[4].isdigit() or not 1 <= int(fields[4]) <= 65535:
            raise RegistryError("Invalid CLI port")
        port = int(fields[4])
        candidates.append(
            {
                "name": name,
                "sha256": digest,
                "port": port,
                "active": bool(udp.get(port, set()) & fds),
            }
        )
    if not candidates or len({item["name"] for item in candidates}) != len(candidates):
        raise RegistryError("Missing or duplicate CLI registry records")
    active = [item for item in candidates if item["active"]]
    if len(active) != 1 or len({item["port"] for item in candidates}) != len(candidates):
        raise RegistryError("CLI port ownership is ambiguous")
    stale = [item for item in candidates if not item["active"]]
    return {
        "node": node,
        "pid": pid,
        "start_time": start,
        "active_port": active[0]["port"],
        "active_sha256": active[0]["sha256"],
        "stale": stale,
    }


def inspect_registry(container: str, node: str) -> dict:
    """Read Docker namespace state without invoking the potentially hung nr-cli."""
    return classify_registry(_docker(container, SNAPSHOT), node)


def quarantine_registry(container: str, node: str, plan: dict) -> dict:
    """Move only proven stale records after a fresh snapshot and in-container checks."""
    current = inspect_registry(container, node)
    if current != plan or not current["stale"]:
        raise RegistryError("CLI registry plan changed or has no stale records")
    target = f"{QUARANTINE}/{uuid.uuid4().hex}"
    items = [f"{item['name']}:{item['sha256']}" for item in current["stale"]]
    output = _docker(
        container,
        MOVE,
        node,
        current["pid"],
        current["start_time"],
        str(current["active_port"]),
        target,
        *items,
    )
    moved = [line.split("\t", 1)[1] for line in output.splitlines() if line.startswith("MOVED\t")]
    if moved != [item["name"] for item in current["stale"]]:
        raise RegistryError("CLI registry quarantine receipt is incomplete")
    return {
        "container": container,
        "node": node,
        "pid": current["pid"],
        "start_time": current["start_time"],
        "active_port": current["active_port"],
        "backup_dir": target,
        "files": current["stale"],
    }
