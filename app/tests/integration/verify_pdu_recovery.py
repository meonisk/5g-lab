"""Real IMS PDU release/re-establishment and automatic SIP route recovery.

This proves access recovery, not removal of every old IMS Contact or handover.
"""

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from baseline_rtp import relay
from ue_cli_registry import inspect_registry, quarantine_registry
from ue_pdu_runtime import cli, sessions, snapshot
from verify_plain_call import logs, run, wait_for

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/research/tools"))
from ims_research.common import parse_env, sha256_file, write_json
from ims_research.execution import StandLock


def ready(cfg, ue):
    try:
        state = snapshot(cfg, ue)
        if "Response msg 200/REGISTER" not in logs(f"lab-sipue{ue}", state["client"]["started_at"]):
            return None
        return state
    except Exception:
        return None


def execute(ue):
    cfg = parse_env(ROOT / "app/config/lab.env")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = ROOT / "local/private" / f"pdu-recovery-{stamp}"
    directory.mkdir()
    report = {
        "status": "FAIL",
        "cleanup": "NOT_TESTED",
        "ue": ue,
        "scope": "real-pdu-address-and-route-recovery",
    }
    report["source_hashes"] = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in sorted(set(Path(__file__).parent.glob("ue_*.py")) | {Path(__file__)})
    }
    since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    timeout = int(cfg["UE_PDU_RECOVERY_TIMEOUT_SECONDS"])
    mutated = False
    with StandLock(ROOT):
        try:
            if not re.search(
                r"Current sessions total:\s*0(?:\s|$)", relay(cfg, "list", "numsessions")
            ):
                raise RuntimeError("PDU recovery requires idle relay")
            active = set(run("docker", "ps", "--format", "{{.Names}}").splitlines())
            if active & {"lab-sip-as", "lab-ai-worker", "lab-media-adapter", "lab-voice-agent"}:
                raise RuntimeError("PDU recovery requires base-only runtime")
            report["cli_registry"] = {}
            for index in (1, 2):
                container, node = f"lab-ue{index}", f"imsi-{cfg[f'UE{index}_IMSI']}"
                plan = inspect_registry(container, node)
                write_json(directory / f"ue{index}-registry-before.json", plan)
                report["cli_registry"][index] = (
                    quarantine_registry(container, node, plan)
                    if plan["stale"]
                    else {"status": "ALREADY_CURRENT"}
                )
            before = {
                index: wait_for(lambda i=index: ready(cfg, i), "Initial UE not ready", timeout)
                for index in (1, 2)
            }
            write_json(directory / "before.json", before)
            psi = before[ue]["pdu"]["ims"]["session_id"]
            mutated = True
            output = cli(cfg, ue, f"ps-release {psi}")
            (directory / "release.txt").write_text(output, encoding="utf-8")
            # Configured UERANSIM sessions normally return automatically. Avoid
            # a second establish request racing that state machine.
            deadline = time.monotonic() + timeout
            observed = []
            after = None
            while time.monotonic() < deadline:
                state = sessions(cfg, ue, require_active=False)
                observed.append(state)
                candidate = ready(cfg, ue)
                if (
                    candidate
                    and candidate["pdu"]["ims"]["address"] != before[ue]["pdu"]["ims"]["address"]
                    and candidate["interface"]["ifindex"] != before[ue]["interface"]["ifindex"]
                    and candidate["client"]["started_at"] != before[ue]["client"]["started_at"]
                ):
                    after = candidate
                    break
                time.sleep(1)
            write_json(directory / "pdu-observations.json", observed)
            if after is None:
                raise RuntimeError(
                    "No changed IMS address, TUN generation and fresh SIP registration"
                )
            peer = snapshot(cfg, 3 - ue)
            if peer != before[3 - ue]:
                raise RuntimeError("Other UE PDU, route or SIP process changed")
            unchanged = {
                sid: data for sid, data in before[ue]["pdu"]["sessions"].items() if sid != psi
            }
            if any(after["pdu"]["sessions"].get(sid) != data for sid, data in unchanged.items()):
                raise RuntimeError("Non-IMS session changed")
            ue_log = logs(f"lab-ue{ue}", since)
            (directory / "ue.log").write_text(ue_log, encoding="utf-8")
            if (
                not re.search(rf"Sending PDU Session Release Request for PSI\[{psi}\]", ue_log)
                or "PDU Session Release Command received" not in ue_log
                or "Performing local release of PDU session" not in ue_log
                or "PDU Session establishment is successful" not in ue_log
            ):
                raise RuntimeError("Missing UE release/establishment events")
            write_json(directory / "after.json", {ue: after, 3 - ue: peer})
            report.update(
                status="PASS",
                old_address=before[ue]["pdu"]["ims"]["address"],
                new_address=after["pdu"]["ims"]["address"],
                peer_unchanged=True,
                non_ims_session_unchanged=True,
                fresh_register_200=True,
            )
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            if isinstance(exc, RuntimeError):
                report["error"] = str(exc)
        finally:
            if mutated:
                # Restore usable service, not the old dynamically allocated IP.
                # Preserve the failed attempt even when recovery succeeds.
                if not ready(cfg, ue):
                    try:
                        state = sessions(cfg, ue, require_active=False)
                        if not state["ims"]:
                            cli(
                                cfg,
                                ue,
                                f"ps-establish IPv4 --sst {cfg['UE_PDU_SST']} --dnn {cfg['IMS_DNN']}",
                            )
                        run("docker", "restart", f"lab-sipue{ue}")
                    except Exception:
                        report["restoration_request_failed"] = True
                try:
                    for index in (1, 2):
                        wait_for(lambda i=index: ready(cfg, i), "Restored UE not ready", timeout)
                    report["cleanup"] = "PASS"
                except Exception:
                    report.update(status="FAIL", cleanup="FAIL")
            else:
                report["cleanup"] = "NO_PDU_MUTATION"
            for name in (f"lab-ue{ue}", "lab-smf", "lab-upf", f"lab-sipue{ue}"):
                try:
                    (directory / f"{name}.log").write_text(logs(name, since), encoding="utf-8")
                except Exception:
                    report.setdefault("diagnostic_errors", []).append(name)
            write_json(directory / "result.json", report)
    print(f"PDU recovery: {report['status']}; evidence: {directory}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue", type=int, choices=(1, 2), default=1)
    raise SystemExit(execute(parser.parse_args().ue))
