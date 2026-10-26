"""Услуги 1005/1006, режим baseline: два независимых вызова обмениваются только переводом.

lab-sipue1 звонит на 1005 и проигрывает русские реплики, lab-sipue2 — на 1006 и
английские. AI Worker переводит каждую реплику в канал собеседника, Voice Agent
озвучивает её на его языке. Исходный звук между вызовами не передаётся.
Отчёт — JSON с числом реплик и задержками этапов; без текста и звука.
"""

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/tests/fixtures"))
sys.path.insert(0, str(ROOT / "scripts"))
from dialogue import verified_fixture  # noqa: E402
from provision import read_env  # noqa: E402

CLIENTS = ("lab-sipue1", "lab-sipue2")
COMPOSE = ["docker", "compose", "--project-directory", str(ROOT)]
COMPOSE += ["--env-file", str(ROOT / "app/config/lab.env"), "-f", str(ROOT / "docker-compose.yml")]
COMPOSE += ["--profile", "test"]
# Последняя фраза начинается почти в конце WAV: после проигрывания оставляем
# явный запас на STT, LLM, TTS и RTP.
POST_PLAYBACK_BUDGET_SECONDS = 90

# Выполняется внутри сервиса: только у него есть внутренний токен API.
API_CODE = """
import os, sys, urllib.request
token = open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="utf-8").read().strip()
url = "http://127.0.0.1:" + os.environ[sys.argv[1]] + sys.argv[2]
request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
print(urllib.request.urlopen(request, timeout=3).read().decode())
"""


def run(*args, timeout=30, env=None):
    return subprocess.run(
        args, capture_output=True, text=True, check=True, timeout=timeout, env=env
    ).stdout


def query(container, port, path):
    return json.loads(run("docker", "exec", container, "python", "-c", API_CODE, port, path))


def voice_status():
    return query("lab-voice-agent", "VOICE_AGENT_HTTP_PORT", "/status")


def adapter_sessions():
    return query("lab-media-adapter", "MEDIA_ADAPTER_PORT", "/sessions")["sessions"]


def ai_status():
    return query("lab-ai-worker", "AI_WORKER_PORT", "/events")


def pjsua(client, command):
    run("docker", "exec", client, "sh", "-c", 'printf "%s" "$1" > /tmp/pjsua-control', "_", command)


def in_parallel(commands):
    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        list(pool.map(lambda item: pjsua(*item), commands))


def wait_until(check, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError(message)


def start_dialogue_clients(settings):
    """Пересоздаём клиентов с WAV диалога вместо фразы espeak и без auto-conf."""
    environment = {
        **os.environ,
        "SIPUE1_PLAYBACK_FILE": settings["INTERPRETER_DIALOGUE_UE1_FILE"],
        "SIPUE2_PLAYBACK_FILE": settings["INTERPRETER_DIALOGUE_UE2_FILE"],
        "SIPUE_AUTO_CONFERENCE": "0",
    }
    run(
        *COMPOSE,
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        *("sipue1", "sipue2"),
        timeout=60,
        env=environment,
    )
    wait_until(
        lambda: all("Response msg 200/REGISTER" in run("docker", "logs", c) for c in CLIENTS),
        60,
        "Тестовые клиенты не зарегистрировались",
    )


def connect_playback(client):
    """Находим порты проигрывателя WAV и вызова в конференц-мосту PJSUA и соединяем их."""
    pjsua(client, "cl\n")

    def ports():
        rows = re.findall(
            r"Port #(\d+)\[[^\r\n]*\]\s+(.+?)\s+transmitting to:", run("docker", "logs", client)
        )
        players = [number for number, label in rows if ".wav" in label]
        calls = [number for number, label in rows if label.startswith("sip:")]
        return (players[-1], calls[-1]) if players and calls else None

    player, call = wait_until(ports, 10, f"{client}: порты конференции не найдены")
    pjsua(client, f"cc\n{player}\n{call}\n")


def translated(started, calls, settings):
    """Реплики, переведённые в канал собеседника его голосом и прошедшие проверку языка."""
    events = [
        event
        for event in ai_status().get("events", [])
        if event.get("processed_at", 0) >= started
        and event.get("call_ids") == [calls.get(event.get("service_mode"))]
        and event.get("reply_delivered")
    ]
    ru_to_en = [
        e
        for e in events
        if e.get("service_mode") == "interpret_ru"
        and e.get("reply_destination_mode") == "interpret_en"
        and e.get("reply_voice") == settings["TTS_TRANSLATION_VOICE"]
        and e.get("llm_response_latin_chars", 0) >= int(settings["TRANSLATION_MIN_LATIN_CHARS"])
        and e.get("llm_response_cyrillic_chars", 1)
        <= int(settings["TRANSLATION_MAX_CYRILLIC_CHARS"])
    ]
    en_to_ru = [
        e
        for e in events
        if e.get("service_mode") == "interpret_en"
        and e.get("reply_destination_mode") == "interpret_ru"
        and e.get("reply_voice") == settings["TTS_VOICE"]
        and e.get("llm_response_cyrillic_chars", 0)
        >= int(settings["REVERSE_TRANSLATION_MIN_CYRILLIC_CHARS"])
        and e.get("llm_response_latin_chars", 1)
        <= int(settings["REVERSE_TRANSLATION_MAX_LATIN_CHARS"])
    ]
    return (ru_to_en, en_to_ru) if len(ru_to_en) >= 2 and len(en_to_ru) >= 2 else None


def sent_tts(calls, settings):
    events = voice_status().get("events", [])

    def leg(mode, voice):
        return [
            e
            for e in events
            if e.get("call_id") == calls[mode]
            and e.get("event") == "tts_sent"
            and e.get("reason") == "llm_reply"
            and e.get("voice") == voice
        ]

    english = leg("interpret_en", settings["TTS_TRANSLATION_VOICE"])
    russian = leg("interpret_ru", settings["TTS_VOICE"])
    return (english, russian) if len(english) >= 2 and len(russian) >= 2 else None


def latency_rows(ai_events, tts_events):
    """Задержки по этапам; граница — отправка RTP, без jitter buffer телефона."""
    sent = {event.get("reply_id"): event for event in tts_events}
    rows = []
    for event in ai_events:
        tts = sent.get(event.get("reply_id"))
        if not tts:
            continue
        audible = tts.get("first_voice_rtp_at")
        speech_end = event.get("last_voice_packet_at")
        rows.append(
            {
                "source_language": event.get("detected_language"),
                "speech_end_to_audible_rtp_ms": (
                    round((audible - speech_end) * 1000, 1) if audible and speech_end else None
                ),
                "sentence_assembly_ms": round(event.get("sentence_assembly_ms", 0), 1),
                "queue_wait_ms": round(event.get("queue_wait_ms", 0), 1),
                "stt_ms": round(event.get("stt_processing_ms", 0), 1),
                "llm_ms": round(event.get("llm_processing_ms", 0), 1),
                "tts_synthesis_ms": round(tts.get("synthesis_ms", 0), 1),
                "rtp_playout_ms": round(tts.get("rtp_playout_ms", 0), 1),
            }
        )
    return rows


def received_packets(client):
    totals = re.findall(r"RX pt=0.*?total\s+(\d+)pkt", run("docker", "logs", client), re.DOTALL)
    return int(totals[-1]) if totals else 0


def main():
    settings = read_env()
    if settings["AI_STREAMING_ENABLED"] == "1":
        raise SystemExit("Проверка рассчитана на пофразовый режим: AI_STREAMING_ENABLED=0")
    fixture = verified_fixture()
    start_dialogue_clients(settings)
    if voice_status()["calls"] or adapter_sessions():
        raise SystemExit("Стенд занят: для проверки не должно быть активных AI-вызовов")

    started = time.time()
    domain = settings["IMS_DOMAIN"]
    try:
        in_parallel(
            [
                ("lab-sipue1", f"m\nsip:{settings['VOICE_INTERPRETER_RU_MSISDN']}@{domain}\n"),
                ("lab-sipue2", f"m\nsip:{settings['VOICE_INTERPRETER_EN_MSISDN']}@{domain}\n"),
            ]
        )
        status = wait_until(
            lambda: s if len((s := voice_status())["calls"]) == 2 else None, 30, "Нет двух вызовов"
        )
        calls = {data["service_mode"]: call_id for call_id, data in status["calls"].items()}
        if set(calls) != {"interpret_ru", "interpret_en"}:
            raise RuntimeError("Языковые каналы не разделены")
        wait_until(
            lambda: all(
                any(
                    e.get("call_id") == call_id
                    and e.get("reason") == "greeting"
                    and e.get("event") == "tts_sent"
                    for e in voice_status()["events"]
                )
                for call_id in calls.values()
            ),
            30,
            "Приветствия каналов не прозвучали",
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(connect_playback, CLIENTS))
        timeout = fixture["playback_seconds"] + POST_PLAYBACK_BUDGET_SECONDS
        ru_events, en_events = wait_until(
            lambda: translated(started, calls, settings), timeout, "Нет четырёх переводов"
        )
        english_tts, russian_tts = wait_until(
            lambda: sent_tts(calls, settings), 60, "Перевод не озвучен в обоих каналах"
        )
    finally:
        try:
            in_parallel([(client, "ha\n") for client in CLIENTS])
            wait_until(
                lambda: not voice_status()["calls"] and not adapter_sessions(),
                30,
                "Вызовы не завершились",
            )
            # Счётчики RTP читаются из логов клиентов, поэтому удаляем их только после.
            rx = {client: received_packets(client) for client in CLIENTS}
        finally:
            # Тестовые клиенты живут только во время проверки и не остаются на стенде.
            subprocess.run([*COMPOSE, "rm", "-sf", "sipue1", "sipue2"], capture_output=True)

    latencies = latency_rows(ru_events + en_events, english_tts + russian_tts)
    limit = float(settings["INTERPRETER_MAX_RESPONSE_DELAY_MS"])
    delays = [row["speech_end_to_audible_rtp_ms"] for row in latencies]
    latency_pass = len(delays) == 4 and all(d is not None and 0 <= d <= limit for d in delays)
    report = {
        "test": "two-leg-bidirectional-ims-interpreter",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_id": fixture["fixture_id"],
        "ru_to_en_turns": len(ru_events),
        "en_to_ru_turns": len(en_events),
        "english_leg_tts": len(english_tts),
        "russian_leg_tts": len(russian_tts),
        "latency_by_turn": latencies,
        "response_delay_limit_ms": limit,
        "audible_rtp_latency_pass": latency_pass,
        "subscriber_rx_packets": rx,
        "pass": all(rx.values()) and len(ru_events) == len(en_events) == 2 and latency_pass,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
