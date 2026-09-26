"""Validate the frozen gate inventory and its collected results."""

from __future__ import annotations

import re
from typing import Any

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def expected_gate_ids(capture: Any) -> list[str]:
    if not isinstance(capture, dict):
        raise ValueError("design capture must be an object")
    gates = capture.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError("design capture.gates must be a nonempty list")
    ids: list[str] = []
    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            raise ValueError(f"design gate {index} must be an object")
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not SAFE_ID.fullmatch(gate_id):
            raise ValueError(f"design gate {index} has an unsafe id")
        if gate_id in ids:
            raise ValueError(f"duplicate design gate id: {gate_id}")
        command = gate.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
        ):
            raise ValueError(f"design gate {gate_id} requires a nonempty string command list")
        ids.append(gate_id)
    return ids


def captured_gate_errors(actual: Any, expected: list[str]) -> list[str]:
    if not isinstance(actual, list):
        return ["captured gates must be a list"]
    errors: list[str] = []
    seen: set[str] = set()
    for index, gate in enumerate(actual):
        if not isinstance(gate, dict):
            errors.append(f"captured gate {index} must be an object")
            continue
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not SAFE_ID.fullmatch(gate_id):
            errors.append(f"captured gate {index} has an invalid id")
            continue
        if gate_id in seen:
            errors.append(f"duplicate captured gate id: {gate_id}")
        seen.add(gate_id)
        code = gate.get("returncode")
        if type(code) is not int or code != 0:
            errors.append(f"admission gate failed: {gate_id}")
        if "status" in gate and gate["status"] != "COMPLETED":
            errors.append(f"admission gate did not complete: {gate_id}")
    missing = sorted(set(expected) - seen)
    unexpected = sorted(seen - set(expected))
    if missing:
        errors.append(f"required admission gates missing: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected admission gates: {', '.join(unexpected)}")
    return errors


def captured_log_errors(actual: Any, expected: Any) -> list[str]:
    if not isinstance(expected, list) or any(not isinstance(name, str) for name in expected):
        return ["design containers must be a container name list"]
    if not isinstance(actual, list) or any(not isinstance(name, str) for name in actual):
        return ["captured logs must be a container name list"]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        return ["required container logs were not all captured exactly once"]
    return []
