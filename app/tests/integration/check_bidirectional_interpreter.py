"""Prove two isolated IMS legs exchange only translated synthetic speech."""

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fixture_checks import verify_interpreter_fixture

ROOT = Path(__file__).resolve().parents[3]
API_CODE = """
import json,os,sys,urllib.request
token=open(os.environ['SERVICE_CONTROL_TOKEN_FILE']).read().strip()
url='http://127.0.0.1:'+os.environ[sys.argv[1]]+sys.argv[2]
request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
print(urllib.request.urlopen(request,timeout=3).read().decode())
"""


def run(*args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout).stdout


def config():
    values = {}
    for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


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


def parallel(commands):
    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        list(pool.map(lambda item: control(*item), commands))


def wait_until(check, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError(message)


def recreate_dialogue_clients():
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / "app/config/lab.env"),
        "--env-file",
        str(ROOT / "local/secrets/ims.env"),
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-f",
        str(ROOT / "app/tests/fixtures/docker-compose.interpreter.yml"),
    ]
    run(*compose, "up", "-d", "--no-deps", "--force-recreate", "sipue1", "sipue2", timeout=60)
    wait_until(
        lambda: all(
            "Response msg 200/REGISTER" in run("docker", "logs", f"lab-sipue{i}") for i in (1, 2)
        ),
        60,
        "IMS interpreter clients did not register",
    )


def translated_events(started, calls, cfg):
    events = [
        event
        for event in ai().get("events", [])
        if event.get("processed_at", 0) >= started
        and event.get("call_ids") == [calls.get(event.get("service_mode"))]
        and event.get("reply_delivered")
    ]
    ru_source = [
        event
        for event in events
        if event.get("service_mode") == "interpret_ru"
        and event.get("reply_destination_mode") == "interpret_en"
        and event.get("reply_voice") == cfg["TTS_TRANSLATION_VOICE"]
        and event.get("llm_response_latin_chars", 0) >= int(cfg["TRANSLATION_MIN_LATIN_CHARS"])
        and event.get("llm_response_cyrillic_chars", 1)
        <= int(cfg["TRANSLATION_MAX_CYRILLIC_CHARS"])
    ]
    en_source = [
        event
        for event in events
        if event.get("service_mode") == "interpret_en"
        and event.get("reply_destination_mode") == "interpret_ru"
        and event.get("reply_voice") == cfg["TTS_VOICE"]
        and event.get("llm_response_cyrillic_chars", 0)
        >= int(cfg["REVERSE_TRANSLATION_MIN_CYRILLIC_CHARS"])
        and event.get("llm_response_latin_chars", 1)
        <= int(cfg["REVERSE_TRANSLATION_MAX_LATIN_CHARS"])
    ]
    return ru_source, en_source


def completed_tts(calls, cfg, required):
    events = voice().get("events", [])
    english = [
        event
        for event in events
        if event.get("call_id") == calls["interpret_en"]
        and event.get("event") == "tts_sent"
        and event.get("reason") == "llm_reply"
        and event.get("voice") == cfg["TTS_TRANSLATION_VOICE"]
    ]
    russian = [
        event
        for event in events
        if event.get("call_id") == calls["interpret_ru"]
        and event.get("event") == "tts_sent"
        and event.get("reason") == "llm_reply"
        and event.get("voice") == cfg["TTS_VOICE"]
    ]
    return (english, russian) if len(english) >= required and len(russian) >= required else None


def latency_rows(ai_events, tts_events):
    completed = {event.get("reply_id"): event for event in tts_events}
    rows = []
    for event in ai_events:
        tts = completed.get(event.get("reply_id"))
        if not tts:
            continue
        rows.append(
            {
                "source_language": event.get("detected_language"),
                "sentence_assembly_ms": round(event.get("sentence_assembly_ms", 0), 1),
                "queue_wait_ms": round(event.get("queue_wait_ms", 0), 1),
                "stt_ms": round(event.get("stt_processing_ms", 0), 1),
                "llm_ms": round(event.get("llm_processing_ms", 0), 1),
                "reply_dispatch_ms": round(event.get("reply_dispatch_ms", 0), 1),
                "tts_synthesis_ms": round(tts.get("synthesis_ms", 0), 1),
                "rtp_playout_ms": round(tts.get("rtp_playout_ms", 0), 1),
                "sentence_to_audio_complete_ms": round(
                    (tts.get("at", 0) - event.get("sentence_ready_at", 0)) * 1000, 1
                ),
            }
        )
    return rows


def received_packets(client):
    logs = run("docker", "logs", client)
    totals = re.findall(r"RX pt=0.*?total\s+(\d+)pkt", logs, re.DOTALL)
    return int(totals[-1]) if totals else 0


def main():
    cfg = config()
    fixture = verify_interpreter_fixture(ROOT)
    recreate_dialogue_clients()
    if voice()["calls"] or adapter()["sessions"]:
        raise RuntimeError("Stand is busy: interpreter test requires no active calls")
    started = time.time()
    calls = {}
    try:
        domain = cfg["IMS_DOMAIN"]
        parallel(
            [
                (
                    "lab-sipue1",
                    f"m\nsip:{cfg['VOICE_INTERPRETER_RU_MSISDN']}@{domain}\n",
                ),
                (
                    "lab-sipue2",
                    f"m\nsip:{cfg['VOICE_INTERPRETER_EN_MSISDN']}@{domain}\n",
                ),
            ]
        )
        status = wait_until(
            lambda: state if len((state := voice())["calls"]) == 2 else None,
            30,
            "Both interpreter legs did not start",
        )
        calls = {data["service_mode"]: call_id for call_id, data in status["calls"].items()}
        if set(calls) != {"interpret_ru", "interpret_en"}:
            raise RuntimeError("Interpreter language legs were not isolated")
        wait_until(
            lambda: ai().get("active_calls", 0) >= 2,
            15,
            "AI worker did not register both interpreter legs",
        )
        wait_until(
            lambda: all(
                any(
                    event.get("call_id") == call_id
                    and event.get("reason") == "greeting"
                    and event.get("event") == "tts_sent"
                    for event in voice()["events"]
                )
                for call_id in calls.values()
            ),
            30,
            "Interpreter greetings did not complete",
        )
        parallel([("lab-sipue1", "cc\n1\n4\n"), ("lab-sipue2", "cc\n1\n4\n")])

        def translated():
            ru_events, en_events = translated_events(started, calls, cfg)
            return (ru_events, en_events) if len(ru_events) >= 2 and len(en_events) >= 2 else None

        ru_events, en_events = wait_until(
            translated, 180, "Four bidirectional translated turns did not complete"
        )
        english_tts, russian_tts = wait_until(
            lambda: completed_tts(calls, cfg, 2),
            60,
            "Translated RTP did not complete on both language legs",
        )
    finally:
        parallel(
            [
                ("lab-sipue1", "cd\n1\n4\nha\n"),
                ("lab-sipue2", "cd\n1\n4\nha\n"),
            ]
        )
        wait_until(
            lambda: not voice()["calls"] and not adapter()["sessions"],
            30,
            "Interpreter calls did not clean up",
        )
    rx = {client: received_packets(client) for client in ("lab-sipue1", "lab-sipue2")}
    latencies = latency_rows(ru_events + en_events, english_tts + russian_tts)
    report = {
        "test": "two-leg-bidirectional-ims-interpreter",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_id": fixture["fixture_id"],
        "separate_terminated_legs": len(calls) == 2,
        "original_speech_bridged": False,
        "ru_to_en_turns": len(ru_events),
        "en_to_ru_turns": len(en_events),
        "english_leg_tts": 2,
        "russian_leg_tts": 2,
        "processing_workers": ai().get("processing_workers"),
        "latency_by_turn": latencies,
        "subscriber_rx_packets": rx,
        "pass": (
            all(rx.values()) and len(ru_events) >= 2 and len(en_events) >= 2 and len(latencies) >= 4
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
