"""Сценарии профилирования S1–S5: нагрузка, CPU узлов и задержка перевода по этапам.

  python3 scripts/profile/scenarios.py S1..S5 --out DIR [--rounds N] [--seconds S]
  python3 scripts/profile/scenarios.py S2 --out DIR --skip "причина"

Состояние rfsim задаёт scripts/profile.sh (S1, S3 — без него; S2, S4, S5 — с ним).
S3 — SIPUE1 из сети ядра на 1003, S4 — UE1 через 5G на 1003 (как bench_5g.py), S5 —
UE1 -> UE2 через translate B2BUA и одновременно SIPUE1 на 1003. Фраза одна и та же:
ue5g.PHRASE голосом Piper (как в тесте диалога) и 20 с тишины. Результат — DIR/scenarios/S?.json;
последняя строка — SCENARIO S?: DONE или STEP SKIP: причина.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "scripts/lib"),
    str(ROOT / "scripts"),
    str(ROOT / "scripts/profile"),
    str(ROOT / "app/tests/fixtures"),
]
from cpu_sampler import Sampler  # noqa: E402
from dialogue import phrase_wavs  # noqa: E402
from latency import conference_ports, stage_row, vad_wait_ms  # noqa: E402
from provision import LAB_ENV, read_env  # noqa: E402
from ue5g import (  # noqa: E402
    PHRASE,
    Client,
    prepare_jail,
    prepare_phrase,
    replies,
    sh,
    translator_call,
    tunnel_ip,
    voice_events,
    wait_for,
)

TITLES = {
    "S1": "простой стенд: IMS + AI, звонков нет",
    "S2": "rfsim без звонков",
    "S3": "один звонок на переводчик без rfsim (SIPUE1)",
    "S4": "один звонок на переводчик с rfsim (UE1 через 5G)",
    "S5": "два переводимых звонка с rfsim: UE1 -> UE2 и SIPUE1 -> переводчик",
}
COMPOSE = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(LAB_ENV),
           "-f", str(ROOT / "docker-compose.yml"), "--profile", "test"]  # fmt: skip
PLAYBACK = "profile-phrase.wav"
FIXTURES = ROOT / "local/private/interpreter"


class Skip(Exception):
    """Сценарий невозможен на этом стенде: SKIP с причиной, а не FAIL."""


def profile_row(event, tts):
    return {**stage_row(event, tts), "vad_wait_ms": vad_wait_ms(event),
            "service_mode": event.get("service_mode")}  # fmt: skip


def logs(container, since=None):
    command = ["docker", "logs", *(["--since", str(int(since))] if since else []), container]
    # PJSUA и сервисы пишут и в stdout, и в stderr контейнера: читаем оба потока.
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          check=False).stdout  # fmt: skip


def voice_slots():
    """VOICE_AGENT_MAX_CALLS работающего Voice Agent (режим AI мог заменить lab.env)."""
    env = subprocess.run(["docker", "inspect", "-f", "{{json .Config.Env}}", "lab-voice-agent"],
                         capture_output=True, encoding="utf-8", check=False).stdout  # fmt: skip
    values = dict(item.split("=", 1) for item in json.loads(env or "[]"))
    return int(values.get("VOICE_AGENT_MAX_CALLS", "0"))


def phrase_wav(folder, settings):
    """Фраза и 20 с тишины в /fixtures клиента SIPUE (тот же звук, что у UE в jail)."""
    del settings
    source = phrase_wavs([PHRASE], folder)[0]
    with wave.open(str(source), "rb") as raw:
        params, audio = raw.getparams(), raw.readframes(raw.getnframes())
    padded = folder / PLAYBACK
    with wave.open(str(padded), "wb") as target:
        target.setparams(params)
        target.writeframes(audio + bytes(params.sampwidth * params.framerate * 20))
    # Папку /fixtures мог создать Docker от root: копирует контейнер, а не хост.
    sh("docker", "run", "--rm", "--network", "none", "-v", f"{folder}:/src:ro", "-v",
       f"{FIXTURES}:/fixtures", "--entrypoint", "cp", "lab-pjsua", f"/src/{PLAYBACK}",
       "/fixtures/")  # fmt: skip
    return len(audio) / (params.sampwidth * params.framerate)


def remove_phrase_wav():
    subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{FIXTURES}:/fixtures",
                    "--entrypoint", "rm", "lab-pjsua", "-f", f"/fixtures/{PLAYBACK}"],
                   capture_output=True, check=False)  # fmt: skip


class SipUe:
    """lab-sipue1 из сети ядра: PJSUA в контейнере, команды через FIFO (как common.sh)."""

    def __init__(self):
        env = dict(
            os.environ, SIPUE1_PLAYBACK_FILE=f"fixtures/{PLAYBACK}", SIPUE_AUTO_CONFERENCE="0"
        )
        subprocess.run([*COMPOSE, "up", "-d", "--no-deps", "--force-recreate", "sipue1"], env=env,
                       capture_output=True, check=True)  # fmt: skip
        wait_for(lambda: "Response msg 200/REGISTER" in logs("lab-sipue1"), 40,
                 "SIPUE1 не зарегистрирован")  # fmt: skip

    def send(self, text, check=True):
        sh("docker", "exec", "lab-sipue1", "sh", "-c", 'printf "%b" "$1" > /tmp/pjsua-control',
           "control", text, check=check)  # fmt: skip

    def hangup(self):
        self.send("ha\n", check=False)

    def connect_player(self, connect=True):
        offset = len(logs("lab-sipue1").splitlines())
        self.send("cl\n")
        time.sleep(1)
        player, call = conference_ports("\n".join(logs("lab-sipue1").splitlines()[offset:]))
        if player is None or call is None:
            raise RuntimeError("SIPUE1: нет порта проигрывателя или вызова")
        self.send(f"{'cc' if connect else 'cd'}\n{player}\n{call}\n")

    def call_translator(self, settings, started):
        self.send(f"m\nsip:{settings['VOICE_TRANSLATOR_MSISDN']}@{settings['IMS_DOMAIN']}\n")
        wait_for(lambda: voice_events(started, "greeting"), 30, "SIPUE1: нет приветствия")

    @staticmethod
    def remove():
        subprocess.run([*COMPOSE, "rm", "-sf", "sipue1"], capture_output=True, check=False)


def idle(args, settings, record):
    time.sleep(args.seconds)


def sipue_rounds(args, settings, record):
    seconds = phrase_wav(args.work, settings)
    try:
        for _ in range(args.rounds):
            # Новый клиент играет фразу с начала: плеер стоит, пока не подключён к вызову.
            ue = SipUe()
            started = time.time()
            try:
                ue.call_translator(settings, started)
                ue.connect_player()
                time.sleep(seconds + 0.5)
                ue.connect_player(connect=False)
                pairs = wait_for(lambda: replies(started), 90, "SIPUE1: перевод не озвучен")
                record(row=profile_row(*pairs[0]))
            except (RuntimeError, TimeoutError) as error:
                record(error=str(error))
            finally:
                ue.hangup()
                time.sleep(3)
    finally:
        SipUe.remove()
        remove_phrase_wav()


def radio(settings):
    addresses = {n: tunnel_ip(n) for n in (1, 2)}
    if not all(addresses.values()):
        raise Skip("rfsim не запущен: нет адреса туннеля UE")
    prepare_jail()
    return addresses, prepare_phrase(settings)


def ue_rounds(args, settings, record):
    addresses, seconds = radio(settings)
    client = None
    try:
        for _ in range(args.rounds):
            if client:
                client.stop()
            client = Client(1, addresses[1], settings)
            try:
                client.registered_ms()
                setup, event, tts = translator_call(client, settings, seconds)
                record(row={"invite_to_200_ms": setup, **profile_row(event, tts)})
            except (RuntimeError, TimeoutError) as error:
                record(error=str(error))
    finally:
        if client:
            client.stop()


def concurrent(args, settings, record):
    """Два длинных звонка: плееры подключены всё время, фраза повторяется раз в период."""
    # Перевод UE1 -> UE2 занимает два места Voice Agent, звонок на 1003 — третье.
    slots = voice_slots()
    if slots < 3:
        raise Skip(f"VOICE_AGENT_MAX_CALLS={slots} в текущем режиме AI: двум звонкам с "
                   "переводом нужно 3 места Voice Agent")  # fmt: skip
    addresses, seconds = radio(settings)
    period = seconds + 20
    clients, ue = [], None
    try:
        sip_seconds = phrase_wav(args.work, settings)
        for n in (1, 2):
            clients.append(Client(n, addresses[n], settings))
            clients[-1].registered_ms()
        started = time.time()
        offset = clients[0].mark()
        clients[0].send(f"m\nsip:{settings['UE2_MSISDN']}@{settings['IMS_DOMAIN']}\n")
        try:
            clients[0].between_ms(
                r"TX .*Request msg INVITE", r"Response msg 200/INVITE", offset, 40
            )
            wait_for(lambda: "AS translate answered" in logs("lab-sip-as", started), 10, "")
        except TimeoutError:
            raise Skip("переводимый звонок UE1 -> UE2 не установлен (см. verify-services.sh)")
        # Уведомление о записи звучит до речи: иначе первая фраза попадёт на него.
        try:
            wait_for(lambda: "AS record started" in logs("lab-sip-as", started), 40, "")
        except TimeoutError:
            pass
        ue = SipUe()
        ue.call_translator(settings, started)
        clients[0].connect_player()
        ue.connect_player()
        time.sleep(args.rounds * max(period, sip_seconds + 20) + 15)
        for pair in replies(started):
            record(row=profile_row(*pair))
    finally:
        if ue:
            ue.hangup()
        for client in clients:
            client.stop()
        SipUe.remove()
        remove_phrase_wav()


RUNNERS = {"S1": idle, "S2": idle, "S3": sipue_rounds, "S4": ue_rounds, "S5": concurrent}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", choices=sorted(RUNNERS))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=5, help="раундов фразы (по умолчанию 5)")
    parser.add_argument("--seconds", type=int, default=30, help="длительность S1/S2, с")
    parser.add_argument("--skip", help="записать SKIP с причиной и выйти")
    args = parser.parse_args()
    args.work = (args.out / "work").resolve()
    args.work.mkdir(parents=True, exist_ok=True)
    path = args.out / f"scenarios/{args.scenario}.json"
    data = {"id": args.scenario, "title": TITLES[args.scenario], "rounds": [], "errors": []}
    if args.skip:
        write(path, {**data, "status": "skip", "reason": args.skip})
        return print(f"STEP SKIP: {args.skip}")

    # SIGTERM от profile.sh (таймаут, Ctrl-C) -> SystemExit: finally убирает клиентов.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    def record(row=None, error=None):
        if row:
            data["rounds"].append(row)
            print(f"  раунд: итог {row['speech_end_to_reply_rtp_ms']} мс, STT {row['stt_ms']} мс",
                  flush=True)  # fmt: skip
        if error:
            data["errors"].append(error)
            print(f"  отказ: {error}", flush=True)

    settings = read_env()
    sampler = Sampler()
    sampler.start()
    started = time.monotonic()
    try:
        RUNNERS[args.scenario](args, settings, record)
    except Skip as reason:
        data.update(status="skip", reason=str(reason), cpu=sampler.stop())
        write(path, data)
        return print(f"STEP SKIP: {reason}")
    finally:
        data["duration_s"] = round(time.monotonic() - started, 1)
        if "cpu" not in data:
            data["cpu"] = sampler.stop()
            calls = args.scenario in ("S3", "S4", "S5")
            data["status"] = "fail" if calls and not data["rounds"] else "done"
            write(path, data)
    if data["status"] == "fail":
        raise SystemExit(f"ERROR: {args.scenario}: ни одного измеренного раунда")
    print(f"SCENARIO {args.scenario}: DONE ({len(data['rounds'])} раундов, "
          f"{len(data['errors'])} отказов)")  # fmt: skip


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
