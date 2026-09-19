"""Compare one/two/one live translation calls without changing service behavior.

Only synthetic UE audio is used. Reports omit call identities and speech text.
The stand must be idle; cleanup hangs up only the clients this test started.
"""

import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_CODE = """
import json,os,sys,urllib.request
token=open(os.environ['SERVICE_CONTROL_TOKEN_FILE']).read().strip()
url='http://127.0.0.1:'+os.environ[sys.argv[1]]+sys.argv[2]
request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
print(urllib.request.urlopen(request,timeout=3).read().decode())
"""


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=15).stdout


def query(container, port, path):
    return json.loads(run("docker", "exec", container, "python", "-c", API_CODE, port, path))


def voice():
    return query("lab-voice-agent", "VOICE_AGENT_HTTP_PORT", "/status")


def adapter():
    return query("lab-media-adapter", "MEDIA_ADAPTER_PORT", "/sessions")


def ai():
    return query("lab-ai-worker", "AI_WORKER_PORT", "/events")


def control(client, command):
    run(
        "docker",
        "exec",
        client,
        "sh",
        "-c",
        'printf "%s" "$1" > /tmp/pjsua-control',
        "control",
        command,
    )


def together(clients, command):
    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        list(pool.map(lambda client: control(client, command), clients))


def wait_until(check, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError("Timed out waiting for a test precondition")


def scenario(count, config, wait_seconds):
    if voice()["calls"] or adapter()["sessions"]:
        raise RuntimeError("Stand is busy: active calls/sessions must finish before this test")
    clients = [f"lab-sipue{i}" for i in range(1, count + 1)]
    started = time.time()
    result = {"requested_calls": count}
    try:
        uri = f"sip:{config['VOICE_TRANSLATOR_MSISDN']}@{config['IMS_DOMAIN']}"
        together(clients, f"m\n{uri}\n")
        status = wait_until(lambda: s if len((s := voice())["calls"]) == count else None, 30)
        ids = set(status["calls"])
        result["simultaneous_calls"] = len(ids)
        wait_until(
            lambda: all(
                any(
                    e.get("call_id") == cid
                    and e.get("reason") == "greeting"
                    and e.get("event") == "tts_sent"
                    for e in voice()["events"]
                )
                for cid in ids
            ),
            30,
        )
        result["adapter_sessions"] = len(adapter()["sessions"])
        together(clients, "cc\n1\n4\n")
        time.sleep(float(config["AI_UTTERANCE_MAX_SECONDS"]) + 0.5)
        together(clients, "cd\n1\n4\n")
        peak_queue = 0
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            state = ai()
            peak_queue = max(peak_queue, state.get("queue_depth", 0))
            matching = [
                e
                for e in state.get("events", [])
                if e.get("processed_at", 0) >= started and ids.intersection(e.get("call_ids", []))
            ]
            replied = {
                e["call_ids"][0]
                for e in matching
                if len(e.get("call_ids", [])) == 1 and e.get("reply_delivered")
            }
            status = voice()
            tts = [
                e
                for e in status["events"]
                if e.get("call_id") in ids
                and e.get("reason") == "llm_reply"
                and e.get("event") == "tts_sent"
            ]
            if replied == ids and {e["call_id"] for e in tts} == ids:
                break
            time.sleep(1)
        result.update(
            {
                "media_received_packets": sorted(
                    c.get("received_packets", 0) for cid, c in status["calls"].items() if cid in ids
                ),
                "processed_utterances": len(matching),
                "ambiguous_call_events": sum(len(e.get("call_ids", [])) != 1 for e in matching),
                "service_modes": sorted({e.get("service_mode", "") for e in matching}),
                "calls_with_ai_reply": len(replied),
                "calls_with_completed_reply_rtp": len({e["call_id"] for e in tts}),
                "peak_observed_queue_depth": peak_queue,
                "stt_ms": [round(e.get("processing_ms", 0), 1) for e in matching],
                "elapsed_seconds": round(time.time() - started, 1),
            }
        )
        result["pass"] = (
            replied == ids
            and len({e["call_id"] for e in tts}) == count
            and result["ambiguous_call_events"] == 0
        )
    finally:
        together(clients, "cd\n1\n4\nha\n")
        wait_until(lambda: not voice()["calls"] and not adapter()["sessions"], 30)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response-wait", type=float, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = {}
    for line in (ROOT / "lab.env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            config[key] = value.strip('"')
    if ai().get("status") != "ok":
        raise RuntimeError("Speech model is not ready")
    report = {
        "test": "one-two-one-parallel-translation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "commit": run("git", "-C", str(ROOT), "rev-parse", "HEAD").strip(),
        "claim": "Functional concurrency probe, not a capacity benchmark",
        "scenarios": [],
    }
    for count in (1, 2, 1):
        print(f"Starting {count} simultaneous translation call(s)", flush=True)
        report["scenarios"].append(scenario(count, config, args.response_wait))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    raise SystemExit(0 if all(s["pass"] for s in report["scenarios"]) else 1)


if __name__ == "__main__":
    main()
