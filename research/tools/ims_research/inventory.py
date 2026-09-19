"""Capture host, repository, image, and resource provenance."""

from __future__ import annotations

import json
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import command, sha256_bytes, sha256_file


def git_snapshot(root: Path) -> dict[str, Any]:
    commit = command(["git", "rev-parse", "HEAD"], root)
    status = command(["git", "status", "--porcelain=v1"], root)
    diff = command(["git", "diff", "--binary", "HEAD"], root)
    return {
        "commit": commit,
        "dirty": bool(status),
        "status_sha256": sha256_bytes(status.encode()),
        "diff_sha256": sha256_bytes(diff.encode()),
    }


def host_snapshot(root: Path) -> dict[str, Any]:
    ps = (
        "$c=Get-CimInstance Win32_Processor|Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors;"
        "$s=Get-CimInstance Win32_ComputerSystem;"
        "$g=Get-CimInstance Win32_VideoController|Select-Object Name,DriverVersion;"
        "[pscustomobject]@{cpu=$c;memory_bytes=[int64]$s.TotalPhysicalMemory;gpus=@($g)}|ConvertTo-Json -Depth 4 -Compress"
    )
    raw = command(["powershell", "-NoProfile", "-Command", ps], root, required=False)
    try:
        hw = json.loads(raw)
    except json.JSONDecodeError:
        hw = {"cpu": {"Name": platform.processor()}, "memory_bytes": 0, "gpus": []}
    nvidia = command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ],
        root,
        required=False,
    )
    if nvidia:
        parsed_gpus = []
        for line in nvidia.splitlines():
            fields = [part.strip() for part in line.split(",")]
            if len(fields) == 3:
                parsed_gpus.append(
                    {
                        "name": fields[0],
                        "memory_mib": int(fields[1]),
                        "driver_version": fields[2],
                        "source": "nvidia-smi",
                    }
                )
        if parsed_gpus:
            hw["gpus"] = parsed_gpus
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": hw.get("cpu", {}),
        "memory_bytes": hw.get("memory_bytes", 0),
        "gpus": hw.get("gpus", []),
        "timezone": datetime.now().astimezone().tzname(),
        "clock": "host UTC wall clock; cross-host uncertainty not measured in this profile",
    }


def input_hashes(root: Path, design_path: Path) -> list[dict[str, str]]:
    paths = [design_path, root / "lab.env", root / "docker-compose.yml"]
    paths.extend(
        root / p
        for p in (
            "services/ai-worker/worker.py",
            "services/media-adapter/adapter.py",
            "services/sip-as/server.py",
            "services/voice-agent/agent.py",
            "services/ai-worker/Dockerfile",
            "services/ai-worker/requirements.txt",
            "services/ai-worker/MODEL_PROVENANCE.md",
            "services/media-adapter/Dockerfile",
            "scripts/verify-real-ai-stream.sh",
            "scripts/verify-transcription-recording.sh",
            "scripts/verify-bilingual-dialogue.sh",
            "fixtures/bilingual-dialogue-v1.json",
            "fixtures/interpreter-dialogue-v1.json",
            "docker-compose.interpreter.yml",
            "docker-compose.parallel.yml",
            "tests/integration/check_bidirectional_interpreter.py",
            "tests/integration/check_parallel_calls.py",
            "research/tools/research_run.py",
            "research/schemas/run-manifest.schema.json",
            "research/schemas/metric-record.schema.json",
        )
    )
    return [
        {"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(p)}
        for p in sorted(
            set(paths)
            | set((root / "services").rglob("*.py"))
            | set((root / "research/tools").rglob("*.py"))
            | set((root / "deploy/compose").glob("*.yml"))
            | set((root / "tests/integration").glob("*.sh"))
            | set((root / "tests/integration").glob("*.py"))
        )
        if p.is_file()
    ]


def docker_records(root: Path, project: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ids = command(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        root,
    )
    containers: list[dict[str, Any]] = []
    if ids:
        inspected = json.loads(command(["docker", "inspect", *ids.splitlines()], root, timeout=60))
        for item in inspected:
            labels = item.get("Config", {}).get("Labels", {}) or {}
            containers.append(
                {
                    "name": item.get("Name", "").lstrip("/"),
                    "service": labels.get("com.docker.compose.service"),
                    "image_reference": item.get("Config", {}).get("Image"),
                    "image_id": item.get("Image"),
                    "state": item.get("State", {}).get("Status"),
                    "started_at": item.get("State", {}).get("StartedAt"),
                }
            )
    stats: list[dict[str, Any]] = []
    raw_stats = command(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[c["name"] for c in containers],
        ],
        root,
        required=False,
        timeout=60,
    )
    for line in raw_stats.splitlines():
        try:
            stats.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return containers, stats
