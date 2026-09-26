"""Read-only PyHSS MySQL evidence for AKA identity and subscriber ownership."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def main(imsis: list[str], require_both: bool = True) -> None:
    # Runs inside lab-pyhss. Use the rendered runtime configuration, not the
    # mounted template, and do not import PyHSS Database/logging modules.
    import MySQLdb
    import MySQLdb.cursors
    import yaml

    settings = yaml.safe_load(Path("/pyhss/config.yaml").read_text())["database"]
    connection = MySQLdb.connect(
        host=settings["server"],
        user=settings["username"],
        passwd=settings["password"],
        db=settings["database"],
        connect_timeout=5,
        cursorclass=MySQLdb.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auc WHERE imsi IN (%s, %s)", tuple(imsis))
            auc = list(cursor.fetchall())
            ids = [row["auc_id"] for row in auc]
            if require_both and len(ids) != 2:
                raise RuntimeError("Expected two target AuC rows")
            query = "SELECT subscriber_id, imsi, auc_id FROM subscriber WHERE imsi IN (%s, %s)"
            parameters = tuple(imsis)
            if ids:
                query += " OR auc_id IN (" + ", ".join(["%s"] * len(ids)) + ")"
                parameters += tuple(ids)
            cursor.execute(query, parameters)
            subscriber = list(cursor.fetchall())
            cursor.execute(
                "SELECT ims_subscriber_id, imsi FROM ims_subscriber WHERE imsi IN (%s, %s)",
                tuple(imsis),
            )
            ims_subscriber = list(cursor.fetchall())
    finally:
        connection.close()
    print(
        json.dumps(
            {"auc": auc, "subscriber": subscriber, "ims_subscriber": ims_subscriber}, default=str
        )
    )


def read_pyhss_rows(imsis: list[str], require_both: bool = True) -> dict:
    """Return captured private rows; callers must never print the result."""
    if len(imsis) != 2 or len(set(imsis)) != 2 or any(not value.isdigit() for value in imsis):
        raise RuntimeError("Expected two distinct numeric IMSIs")
    script = Path(__file__).read_text(encoding="utf-8")
    invocation = script + "\nmain(" + json.dumps(imsis) + ", " + repr(require_both) + ")\n"
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "lab-pyhss", "python3", "-"],
            input=invocation,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("PyHSS database read failed")
        rows = json.loads(result.stdout)
        if set(rows) != {"auc", "subscriber", "ims_subscriber"}:
            raise RuntimeError("PyHSS database response incomplete")
        return rows
    except Exception as error:
        raise RuntimeError("PyHSS database read failed") from error
