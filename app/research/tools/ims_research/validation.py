"""Enforce design stages, artifact checksums, and evidence privacy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    IMSI_RE,
    RAW_CORRELATION_RE,
    SCHEMA_VERSION,
    TRANSCRIPT_CONTENT_RE,
    load_json,
    sha256_file,
    utc_now,
    write_json,
)
from .privacy import Pseudonymizer, sensitive_values


def validate_design(design: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "design_id",
        "design_status",
        "stage",
        "evidence_class",
        "scientific_claim_allowed",
        "purpose",
        "capture",
        "privacy",
    }
    missing = sorted(required - design.keys())
    if missing:
        raise ValueError(f"design missing fields: {', '.join(missing)}")
    if design["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported design schema_version")
    if design["stage"] not in {"ADMISSION", "PILOT", "MAIN", "CLOSED_ANALYSIS"}:
        raise ValueError("executable design has invalid stage")
    if design["stage"] in {"ADMISSION", "PILOT"} and design["scientific_claim_allowed"]:
        raise ValueError("admission/pilot designs cannot allow scientific claims")
    if design["stage"] == "MAIN":
        if design["design_status"] != "FROZEN_FOR_MAIN":
            raise ValueError("MAIN requires design_status=FROZEN_FOR_MAIN")
        if int(design.get("repetitions", 0)) < 2:
            raise ValueError("MAIN requires a frozen repetition count greater than one")
    privacy = design["privacy"]
    if privacy.get("raw_audio") != "FORBIDDEN" or privacy.get("raw_payloads") != "FORBIDDEN":
        raise ValueError("the v1 harness only permits designs that forbid raw audio and payloads")


def validate(root: Path, design_path: Path, run_id: str) -> None:
    run_dir = root / "local/evidence" / "runs" / run_id
    manifest = load_json(run_dir / "manifest.json")
    design = load_json(design_path)
    validate_design(design)
    errors: list[str] = []
    for field in (
        "schema_version",
        "run_id",
        "created_at_utc",
        "stage",
        "evidence_class",
        "scientific_claim_allowed",
        "design",
        "repository",
        "host",
        "privacy",
    ):
        if field not in manifest:
            errors.append(f"manifest missing {field}")
    if manifest.get("collection_status") != "COLLECTED":
        errors.append("run has not been collected")
    gates = manifest.get("capture", {}).get("gates", [])
    expected_gates = design.get("capture", {}).get("gates", [])
    if len(gates) != len(expected_gates):
        errors.append("required admission gates were not all captured")
    for gate in gates:
        if gate.get("returncode") != 0:
            errors.append(f"admission gate failed: {gate.get('id')}")
    if manifest.get("design", {}).get("sha256") != sha256_file(design_path):
        errors.append("design hash mismatch")
    checksum_path = run_dir / "checksums.sha256"
    if not checksum_path.exists():
        errors.append("checksums missing")
    else:
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            path = run_dir / Path(relative)
            if not path.is_file() or sha256_file(path) != expected:
                errors.append(f"checksum mismatch: {relative}")
    _, secret_values = sensitive_values(root)
    shareable_files = [p for p in (run_dir / "shareable").rglob("*") if p.is_file()]
    shareable_files.append(run_dir / "manifest.json")
    for path in shareable_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if IMSI_RE.search(text):
            errors.append(f"direct subscriber identifier in {path.relative_to(run_dir)}")
        if RAW_CORRELATION_RE.search(text):
            errors.append(f"unprotected call correlation id in {path.relative_to(run_dir)}")
        if TRANSCRIPT_CONTENT_RE.search(text):
            errors.append(f"transcript content in shareable evidence: {path.relative_to(run_dir)}")
        if any(secret in text for secret in secret_values):
            errors.append(f"secret value in {path.relative_to(run_dir)}")
    if manifest.get("stage") in {"ADMISSION", "PILOT"} and manifest.get("scientific_claim_allowed"):
        errors.append("admission/pilot run incorrectly permits a scientific claim")
    report = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "validated_at_utc": utc_now(),
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "claim_boundary": manifest.get("claim_boundary"),
    }
    write_json(run_dir / "validation.json", report)
    if errors:
        raise RuntimeError("RESEARCH READINESS: FAIL\n- " + "\n- ".join(errors))
    print("RESEARCH READINESS: PASS (instrumentation only; not a scientific outcome)")


def verify(root: Path) -> None:
    smoke = root / "app/research" / "designs" / "local-instrumentation-smoke-v1.json"
    conversational = root / "app/research" / "designs" / "local-conversational-loop-smoke-v1.json"
    russian = root / "app/research" / "designs" / "local-russian-conversation-smoke-v1.json"
    language_services = root / "app/research" / "designs" / "local-language-services-smoke-v1.json"
    language_services_v2 = (
        root / "app/research" / "designs" / "local-language-services-smoke-v2.json"
    )
    candidate = load_json(root / "app/research" / "designs" / "ai-scale-study-v1.json")
    design = load_json(smoke)
    validate_design(design)
    validate_design(load_json(conversational))
    validate_design(load_json(russian))
    validate_design(load_json(language_services))
    validate_design(load_json(language_services_v2))
    if candidate.get("design_status") != "DRAFT_REQUIRES_PILOT_FREEZE":
        raise ValueError("AI scale candidate must remain explicitly unfrozen")
    for schema in ("run-manifest.schema.json", "metric-record.schema.json"):
        load_json(root / "app/research" / "schemas" / schema)
    key = b"x" * 32
    raw_identity = "999990000000001"
    raw_secret = "0123456789ABCDEF0123456789ABCDEF"
    p = Pseudonymizer(key, {"UE1_IMSI": raw_identity, "SUBSCRIBER_K": raw_secret})
    first = p.text(f"imsi-{raw_identity} call-id=abcde calls=['fghij'] secret={raw_secret}")
    second = p.text(f"subscriber {raw_identity}")
    if raw_identity in first + second or raw_secret in first or first.count("<ue1_imsi:") != 1:
        raise AssertionError("pseudonymization self-test failed")
    if p.alias("ue1_imsi", raw_identity) not in second:
        raise AssertionError("pseudonyms are not stable within a run")
    if "fghij" in first:
        raise AssertionError("call-list correlation identifiers were not pseudonymized")
    print("RESEARCH TOOLING OFFLINE VALIDATION: PASS")
    print("AI scale design status: DRAFT_REQUIRES_PILOT_FREEZE (correctly not a result)")
