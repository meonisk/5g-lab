"""Длинный разговор в обычном темпе: SIPUE1 (ru) звонит SIPUE2 (en) через translate + record.

  python3 scripts/profile/conversation.py [--out DIR]

Текст — app/tests/fixtures/conversation-long-v1.json, голос — Piper: внутри реплики паузы
между предложениями 350 мс, ответ собеседника начинается через 1,5 с после конца реплики.
Оба клиента играют свои WAV одновременно и не ждут перевода, как живые люди.

Результат в DIR (по умолчанию local/conversation/<время>/):
- report.md — числа по направлениям ru→en и en→ru: на сколько фраз AI разделил речь и
  почему, сколько переведено и озвучено, задержка, растёт ли она к концу, точность;
- conversation.log — все события по времени: предложение сказано, фраза закрыта на
  сервере и какие слова в неё попали, распознанный текст, перевод, когда он зазвучал;
- report.json — то же для программ.
Тексты берутся из приватной записи звонка (услуга record) и остаются в local/.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ("scripts/lib", "scripts", "scripts/profile")]
sys.path.append(str(ROOT / "app/tests/fixtures"))
from conversation_log import TARGET_MS, direction_metrics, journal, problems  # noqa: E402
from dialogue import conversation_wavs  # noqa: E402
from latency import conference_ports  # noqa: E402
from provision import LAB_ENV, read_env  # noqa: E402
from ue5g import query, sh, wait_for  # noqa: E402

COMPOSE = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(LAB_ENV),
           "-f", str(ROOT / "docker-compose.yml"), "--profile", "test"]  # fmt: skip
FIXTURES = ROOT / "local/private/interpreter"
WAVS = {"ue1": "conversation-ue1.wav", "ue2": "conversation-ue2.wav"}
CLIENTS = {"ue1": "lab-sipue1", "ue2": "lab-sipue2"}
# Направление: кто говорит и нога B2BUA, в которой звучит его речь.
DIRECTIONS = {"ru→en": ("ue1", "a"), "en→ru": ("ue2", "b")}
MIN_ACCURACY = 0.7
QUIET_SECONDS = 15
SETTINGS_SHOWN = ("AI_MODEL_SIZE", "AI_PROCESSING_WORKERS", "AI_STT_CPU_THREADS",
                  "AI_DIALOGUE_UTTERANCE_SILENCE_MS", "AI_DIALOGUE_UTTERANCE_MAX_SECONDS")  # fmt: skip


def logs(container, since=None):
    command = ["docker", "logs", *(["--since", str(int(since))] if since else []), container]
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          check=False).stdout  # fmt: skip


def pjsua(client, text):
    sh("docker", "exec", client, "sh", "-c", 'printf "%b" "$1" > /tmp/pjsua-control',
       "control", text)  # fmt: skip


def container_env(name):
    raw = sh("docker", "inspect", "-f", "{{json .Config.Env}}", name, check=False)
    return dict(item.split("=", 1) for item in json.loads(raw or "[]"))


def fixtures_command(*args):
    # Папку /fixtures мог создать Docker от root: файлы кладёт контейнер, а не хост.
    return ["docker", "run", "--rm", "--network", "none", "-v", f"{FIXTURES}:/fixtures", *args]


def install_wavs(work):
    timeline = conversation_wavs(work)
    sources = [f"/src/{name}" for name in WAVS.values()]
    sh(*fixtures_command("-v", f"{work}:/src:ro", "--entrypoint", "cp", "lab-pjsua", *sources,
                         "/fixtures/"))  # fmt: skip
    return timeline


def remove_wavs():
    targets = [f"/fixtures/{name}" for name in WAVS.values()]
    subprocess.run(fixtures_command("--entrypoint", "rm", "lab-pjsua", "-f", *targets),
                   capture_output=True, check=False)  # fmt: skip


def start_clients():
    env = dict(os.environ, SIPUE1_PLAYBACK_FILE=f"fixtures/{WAVS['ue1']}",
               SIPUE2_PLAYBACK_FILE=f"fixtures/{WAVS['ue2']}", SIPUE_AUTO_CONFERENCE="0")  # fmt: skip
    subprocess.run([*COMPOSE, "up", "-d", "--no-deps", "--force-recreate", "sipue1", "sipue2"],
                   env=env, capture_output=True, check=True)  # fmt: skip
    wait_for(lambda: all("Response msg 200/REGISTER" in logs(c) for c in CLIENTS.values()), 60,
             "тестовые клиенты не зарегистрированы")  # fmt: skip


def player_ports(client):
    offset = len(logs(client).splitlines())
    pjsua(client, "cl\n")
    time.sleep(1)
    player, call = conference_ports("\n".join(logs(client).splitlines()[offset:]))
    if player is None or call is None:
        raise RuntimeError(f"{client}: нет порта проигрывателя или вызова")
    return player, call


def switch_players(ports, command):
    """cc — оба проигрывателя в вызов одновременно, cd — отключить (иначе WAV пойдёт по кругу)."""
    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        list(pool.map(lambda item: pjsua(item[0], f"{command}\n{item[1][0]}\n{item[1][1]}\n"),
                      ports.items()))  # fmt: skip


def translated_call(settings, started):
    pjsua(CLIENTS["ue1"], f"m\nsip:{settings['SIPUE2_IMSI']}@{settings['IMS_DOMAIN']}\n")
    answered = wait_for(
        lambda: re.search(
            r"AS translate answered call_id=(\S+) leg_b=(\S+)", logs("lab-sip-as", started)
        ),  # fmt: skip
        40,
        "translate AS не ответил: нужен SIPUE1_SERVICES=translate,record (verify-services.sh)",
    )
    legs = dict(zip("ab", answered.groups()))
    # Уведомление о записи звучит до речи: иначе первые слова попадут на него.
    wait_for(lambda: f"AS record started call_id={legs['a']}" in logs("lab-sip-as", started), 40,
             "запись не началась: нужен SIPUE1_SERVICES=translate,record")  # fmt: skip
    return legs


def collect_tts(store, started):
    """Voice Agent хранит последние 100 событий: опрашиваем часто и копим у себя."""
    for event in query("lab-voice-agent", "VOICE_AGENT_HTTP_PORT", "/status").get("events", []):
        if event.get("reason") == "llm_reply" and event.get("at", 0) >= started:
            store[event.get("reply_id")] = event
    return len(store)


def wait_quiet(store, started):
    """После конца речи ждём, пока Voice Agent не перестанет озвучивать переводы."""
    count, quiet_since, limit = -1, time.monotonic(), time.monotonic() + 180
    while time.monotonic() - quiet_since < QUIET_SECONDS and time.monotonic() < limit:
        if (new := collect_tts(store, started)) != count:
            count, quiet_since = new, time.monotonic()
        time.sleep(3)


def recorded_phrases(settings, call_a, started):
    """timeline.jsonl записи звонка: по строке на фразу обеих ног."""
    session = hashlib.sha256(call_a.encode()).hexdigest()[:20]
    wait_for(lambda: f"AI recording_finalized session={session}" in logs("lab-ai-worker", started),
             40, "запись разговора не закрыта")  # fmt: skip
    raw = sh("docker", "exec", "lab-ai-worker", "cat",
             f"{settings['RECORDING_ROOT']}/{session}/timeline.jsonl", check=False)  # fmt: skip
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def cell(value):
    return "—" if value is None else str(value)


def markdown(report):
    d = report["directions"]
    names = list(d)

    def row(title, pick):
        return f"| {title} | " + " | ".join(cell(pick(d[n])) for n in names) + " |"

    def span(item):
        return item and f"{item['median']} / {item['max']}"

    lines = [
        f"# Длинный разговор, {report['created_at']}", "",
        f"Разговор {report['duration_s']} с. Настройки AI: " +
        ", ".join(f"{k}={v}" for k, v in report["settings"].items()) + ".", "",
        "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names),
        row("предложений / секунд речи", lambda x: f"{x['sentences']} / {x['speech_s']}"),
        row("фраз у AI (с текстом)", lambda x: f"{x['phrases']} ({x['phrases_with_text']})"),
        row("почему фраза закончилась", lambda x: ", ".join(f"{k} {v}" for k, v in
                                                           x["end_reasons"].items())),
        row("длина фразы, медиана / макс, с", lambda x: span(x["phrase_s"])),
        row("переведено фраз", lambda x: x["translated"]),
        row("озвучено полностью / прервано", lambda x: f"{x['voiced']} / {x['interrupted']}"),
        row("точность распознавания", lambda x: f"{x['accuracy']:.0%}"),
        row("задержка, медиана / макс, мс", lambda x: span(x["lag_ms"])),
        row(f"фраз не дольше {TARGET_MS} мс", lambda x: f"{x['within_target']} из "
                                                    f"{len(x['lag_by_phrase_ms'])}"),
        row("рост задержки к концу, мс", lambda x: x["lag_growth_ms"]),
        row("конец речи → конец перевода, с", lambda x: x["tail_s"]),
        row("озвучка перевода, с", lambda x: x["reply_audio_s"]),
        row("ожидание в очереди, макс, мс", lambda x: x["queue_wait_max_ms"]),
        "", "Задержка по фразам (от конца речи до первого звука перевода), мс:", "",
        *[f"- {n}: {', '.join(map(str, d[n]['lag_by_phrase_ms'])) or '—'}" for n in names],
        "", "Все события по времени — conversation.log рядом с отчётом.",
        "", f"Итог: {report['result']}" + "".join(f"\n- {p}" for p in report["problems"]),
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


def run(out):
    settings = read_env()
    timeline = install_wavs((out / "work").resolve())
    tts = {}
    try:
        start_clients()
        started = time.time()
        legs = translated_call(settings, started)
        ports = {client: player_ports(client) for client in CLIENTS.values()}
        switch_players(ports, "cc")
        print(f"разговор идёт {timeline['duration_ms'] / 1000:.0f} с", flush=True)
        deadline = time.monotonic() + timeline["duration_ms"] / 1000
        while time.monotonic() < deadline:
            collect_tts(tts, started)
            time.sleep(max(0, min(3, deadline - time.monotonic())))
        # В конце WAV 5 с тишины: проигрыватель отключается до повтора файла по кругу.
        switch_players(ports, "cd")
        wait_quiet(tts, started)
        pjsua(CLIENTS["ue1"], "ha\n")
        phrases = recorded_phrases(settings, legs["a"], started)
    finally:
        # Остановка клиентов завершает и незакрытый звонок (PJSUA отправляет BYE).
        subprocess.run([*COMPOSE, "rm", "-sf", "sipue1", "sipue2"], capture_output=True)
        remove_wavs()
    by_leg = {}
    for name, (speaker, leg) in DIRECTIONS.items():
        by_leg[name] = (speaker, [p for p in phrases if p.get("call_ids") == [legs[leg]]])
    directions = {
        name: direction_metrics(own, tts, [s for s in timeline["sentences"]
                                           if s["speaker"] == speaker])
        for name, (speaker, own) in by_leg.items()
    }  # fmt: skip
    found = problems(directions, MIN_ACCURACY)
    env = container_env("lab-ai-worker")
    report = {
        "test": "long-conversation", "fixture_id": timeline["fixture_id"],
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "duration_s": round(timeline["duration_ms"] / 1000), "target_ms": TARGET_MS,
        "settings": {k: env.get(k) for k in SETTINGS_SHOWN}, "directions": directions,
        "problems": found, "result": "FAIL" if found else "PASS",
    }  # fmt: skip
    return report, journal(timeline["sentences"], by_leg, tts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--out", type=Path, default=ROOT / "local/conversation" / stamp)
    out = parser.parse_args().out
    report, lines = run(out)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")  # fmt: skip
    (out / "conversation.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    text = markdown(report)
    (out / "report.md").write_text(text, encoding="utf-8")
    print(text, f"Отчёт: {out / 'report.md'}", f"Журнал: {out / 'conversation.log'}",
          f"CONVERSATION: {report['result']}", sep="\n")  # fmt: skip
    raise SystemExit(1 if report["problems"] else 0)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
