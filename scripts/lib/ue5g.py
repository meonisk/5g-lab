"""Абоненты UE через 5G (OAI rfsim) и события сервисов: общее для bench_5g.py и profile/.

PJSUA запускается в namespace UE через chroot в корень образа lab-pjsua (Docker не
запускает контейнер в чужом namespace); команды консоли — через FIFO. События AI
Worker и Voice Agent читаются изнутри их контейнеров со служебным токеном.
"""

import json
import os
import re
import subprocess
import time
import wave
from pathlib import Path

from latency import conference_ports

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "local/rfsim"
JAIL = WORK / "pjsua-root"
PHRASE = "Добрый день. Как у вас дела?"
API_CODE = """
import os, sys, urllib.request
token = open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="utf-8").read().strip()
url = "http://127.0.0.1:" + os.environ[sys.argv[1]] + sys.argv[2]
request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
print(urllib.request.urlopen(request, timeout=3).read().decode())
"""
STAMP = re.compile(r"^(\d\d):(\d\d):(\d\d\.\d{3})")
INVITE_TX = r"TX .*Request msg INVITE"


def sh(*args, check=True, timeout=120):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(map(str, args[:6]))}: {result.stderr.strip()[-300:]}")
    return result.stdout


def ns(n, *args, check=True):
    return sh("sudo", "ip", "netns", "exec", f"ue{n}", *args, check=check)


def tunnel_ip(n):
    found = re.search(
        r"inet (\S+)/", ns(n, "ip", "-4", "-o", "addr", "show", "oaitun_ue1", check=False)
    )
    return found.group(1) if found else None


def query(container, port, path):
    return json.loads(sh("docker", "exec", container, "python", "-c", API_CODE, port, path))


def wait_for(check, seconds, message):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.5)
    raise TimeoutError(message)


def prepare_jail():
    """Корень образа lab-pjsua: Docker не запускает контейнер в чужом namespace."""
    if not (JAIL / "usr/local/bin/pjsua").exists():
        sh("sudo", "mkdir", "-p", str(JAIL))
        container = sh("docker", "create", "lab-pjsua").strip()
        sh("sh", "-c", f"docker export {container} | sudo tar -x -C '{JAIL}'", timeout=600)
        sh("docker", "rm", container)
    for name, minor in (("null", 3), ("random", 8), ("urandom", 9)):
        if not (JAIL / "dev" / name).is_char_device():
            sh("sudo", "rm", "-f", str(JAIL / "dev" / name))
            sh("sudo", "mknod", "-m", "666", str(JAIL / "dev" / name), "c", "1", str(minor))


def prepare_phrase(settings):
    """Фраза и 20 с тишины: плеер играет по кругу, агенту нужна пауза для ответа."""
    voice, rate = settings["TTS_VOICE"], settings["TTS_RATE"]
    sh("sudo", "chroot", str(JAIL), "espeak-ng", "-v", voice, "-s", rate, "-w",
       "/tmp/bench.wav", PHRASE)  # fmt: skip
    with wave.open(str(JAIL / "tmp/bench.wav"), "rb") as source:
        params, audio = source.getparams(), source.readframes(source.getnframes())
    padded = WORK / "bench-pause.wav"
    with wave.open(str(padded), "wb") as target:
        target.setparams(params)
        target.writeframes(audio + bytes(params.sampwidth * params.framerate * 20))
    sh("sudo", "cp", str(padded), str(JAIL / "tmp/bench-pause.wav"))
    return len(audio) / (params.sampwidth * params.framerate)


class Client:
    """PJSUA абонента UEn в namespace UE; команды консоли — через FIFO."""

    def __init__(self, n, address, settings):
        self.n, self.log = n, WORK / f"bench-ue{n}.log"
        self.fifo = JAIL / f"tmp/bench-ue{n}"
        imsi, key = settings[f"UE{n}_IMSI"], settings[f"UE{n}_IMS_K"]
        domain, codec = settings["IMS_DOMAIN"], settings["SIP_UE_CODEC"]
        proxy = f"sip:{settings['PCSCF_IP']}:{settings['PCSCF_SIP_PORT']};transport=udp;lr"
        sh("sudo", "rm", "-f", str(self.fifo))
        sh("sudo", "mkfifo", "-m", "666", str(self.fifo))
        script = 'exec 3<>"$0"; exec stdbuf -oL -eL pjsua "$@" <&3'
        # --auto-update-nat=0: за NAT UPF клиент не перезапускает REGISTER посреди Digest.
        options = [
            "--log-level=4", "--app-log-level=4", "--null-audio", "--no-tcp", "--no-vad",
            "--auto-update-nat=0", "--clock-rate=8000", "--snd-clock-rate=8000",
            "--dis-codec=*", f"--add-codec={codec}", "--auto-answer=200",
            "--play-file=/tmp/bench-pause.wav", f"--id=sip:{imsi}@{domain}",
            f"--registrar=sip:{domain}", f"--proxy={proxy}", f"--realm={domain}",
            f"--username={imsi}@{domain}", f"--password={key}",
            f"--ip-addr={address}", f"--bound-addr={address}",
        ]  # fmt: skip
        command = ["sudo", "ip", "netns", "exec", f"ue{n}", "chroot", str(JAIL), "bash", "-c"]
        with open(self.log, "w", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [*command, script, f"/tmp/bench-ue{n}", *options],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )  # fmt: skip

    def send(self, text):
        # O_NONBLOCK: без читателя (клиент упал) запись в FIFO иначе висит вечно.
        descriptor = os.open(self.fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(descriptor, text.encode())
        finally:
            os.close(descriptor)

    def lines(self, offset=0):
        return self.log.read_text(encoding="utf-8", errors="replace").splitlines()[offset:]

    def mark(self):
        return len(self.lines())

    def first(self, pattern, offset=0):
        """Время (с от полуночи) первой строки журнала с шаблоном после offset."""
        for line in self.lines(offset):
            stamp = STAMP.match(line)
            if stamp and re.search(pattern, line):
                return int(stamp[1]) * 3600 + int(stamp[2]) * 60 + float(stamp[3])
        return None

    def between_ms(self, start, end, offset=0, seconds=30):
        stop = wait_for(lambda: self.first(end, offset), seconds, f"UE{self.n}: нет {end}")
        return round(((stop - self.first(start, offset)) % 86400) * 1000, 1)

    def registered_ms(self):
        return self.between_ms(r"TX .*Request msg REGISTER", r"Response msg 200/REGISTER", 0, 60)

    def connect_player(self, connect=True):
        """Проигрыватель WAV -> последний вызов (cc) или отключение (cd)."""
        offset = self.mark()
        self.send("cl\n")
        time.sleep(1)
        player, call = conference_ports("\n".join(self.lines(offset)))
        if player is None or call is None:
            raise RuntimeError(f"UE{self.n}: нет порта проигрывателя или вызова")
        self.send(f"{'cc' if connect else 'cd'}\n{player}\n{call}\n")

    def say_once(self, phrase_seconds):
        self.connect_player()
        time.sleep(phrase_seconds + 0.5)
        self.connect_player(connect=False)

    def stop(self):
        try:
            self.send("ha\nq\n")
        except OSError:
            pass
        time.sleep(1)
        pattern = f"[b]ench-ue{self.n} "
        sh("sudo", "pkill", "-f", pattern, check=False)
        # Следующий клиент займёт тот же адрес и порт SIP: ждём выхода прежнего.
        wait_for(
            lambda: not sh("pgrep", "-f", pattern, check=False).strip(), 10, "PJSUA не завершился"
        )


def voice_events(started, reason):
    """Озвучки Voice Agent с причиной reason (greeting, llm_reply) после started."""
    events = query("lab-voice-agent", "VOICE_AGENT_HTTP_PORT", "/status").get("events", [])
    return [e for e in events if e.get("event") == "tts_sent" and e.get("reason") == reason
            and e.get("at", 0) >= started]  # fmt: skip


def utterances(started):
    events = query("lab-ai-worker", "AI_WORKER_PORT", "/events").get("events", [])
    return [e for e in events if e.get("processed_at", 0) >= started]


def replies(started):
    """Пары (событие AI Worker, озвучка перевода) для доставленных после started реплик."""
    sent = {e.get("reply_id"): e for e in voice_events(started, "llm_reply")}
    return [(event, sent[event["reply_id"]]) for event in utterances(started)
            if event.get("reply_delivered") and event.get("reply_id") in sent]  # fmt: skip


def translator_call(client, settings, phrase_seconds):
    """Вызов номера переводчика, одна фраза: (INVITE -> 200 мс, событие, озвучка)."""
    started, offset = time.time(), client.mark()
    client.send(f"m\nsip:{settings['VOICE_TRANSLATOR_MSISDN']}@{settings['IMS_DOMAIN']}\n")
    setup = client.between_ms(INVITE_TX, r"Response msg 200/INVITE", offset)
    wait_for(lambda: voice_events(started, "greeting"), 30, "нет приветствия Voice Agent")
    client.say_once(phrase_seconds)

    # Ожидание по этапам: при отказе видно, где именно остановился конвейер.
    try:
        wait_for(lambda: utterances(started), 60, "AI Worker не получил или не распознал фразу")
        wait_for(lambda: any(e.get("reply_delivered") for e in utterances(started)), 60,
                 "AI Worker распознал фразу, но не отправил перевод")  # fmt: skip
        pairs = wait_for(lambda: replies(started), 60,
                         "перевод отправлен, но Voice Agent его не озвучил")  # fmt: skip
    finally:
        client.send("ha\n")
        time.sleep(3)
    event, tts = pairs[0]
    return setup, event, tts
