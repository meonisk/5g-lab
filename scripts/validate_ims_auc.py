"""Validate an existing PyHSS AuC identity without exposing AKA material."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from .subscriber_key_backend import read_pyhss_rows
except ImportError:  # Direct script invocation from the provisioner.
    from subscriber_key_backend import read_pyhss_rows


FIELDS = ("ki", "opc", "amf")
ENV_KEYS = {"ki": "EXPECTED_IMS_K", "opc": "EXPECTED_IMS_OPC", "amf": "EXPECTED_IMS_AMF"}


def matching_keys(row: dict, expected: dict[str, str]) -> bool:
    return all(str(row.get(field, "")).lower() == expected[field].lower() for field in FIELDS)


def validate_existing(
    record: dict, imsi: str, auc_id: str, expected: dict[str, str], peer: str
) -> bool:
    if not isinstance(record, dict) or str(record.get("auc_id")) != auc_id:
        return False
    if record.get("imsi") is not None and str(record["imsi"]) != imsi:
        return False
    if all(record.get(field) is not None for field in FIELDS):
        return matching_keys(record, expected)

    # The REST read omits ki/opc on deployed PyHSS versions. Resolve all three
    # keys through a read-only DB query and bind the row to this AuC ID/IMSI.
    rows = read_pyhss_rows([imsi, peer], require_both=False)
    auc = [row for row in rows["auc"] if str(row.get("imsi")) == imsi]
    if len(auc) != 1 or str(auc[0].get("auc_id")) != auc_id:
        return False
    if any(
        record.get(field) is not None
        and str(record[field]).lower() != str(auc[0].get(field, "")).lower()
        for field in FIELDS
    ):
        return False
    return matching_keys(auc[0], expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--imsi", required=True)
    parser.add_argument("--auc-id", required=True)
    parser.add_argument("--peer-imsi", required=True)
    args = parser.parse_args()
    try:
        expected = {field: os.environ[ENV_KEYS[field]] for field in FIELDS}
        if not args.imsi.isdigit() or not args.peer_imsi.isdigit() or args.imsi == args.peer_imsi:
            return 1
        record = json.loads(args.record.read_text(encoding="utf-8"))
        return (
            0 if validate_existing(record, args.imsi, args.auc_id, expected, args.peer_imsi) else 1
        )
    except Exception:
        # Never echo raw API/DB errors: they may include authentication fields.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
