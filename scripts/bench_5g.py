"""Бенчмарк задержек через 5G (OAI rfsim): сеть, SIP и AI одной командой.

Что измеряется, всё на одном хосте и одних часах:
- путь: маршрут к P-CSCF из namespace UE идёт в oaitun_ue1, счётчики туннеля растут;
- сеть: RTT ping UE -> P-CSCF через 5G и тот же ping напрямую с хоста;
- SIP: REGISTER с Digest (TX -> 200), INVITE UE1 -> UE2 (TX -> 180 и 200),
  INVITE UE1 -> переводчик (TX -> 200);
- AI (номер переводчика): конец речи -> первый RTP ответа и этапы (сборка фразы,
  очередь, STT, перевод, синтез) из событий AI Worker и Voice Agent.

Радио поднимается и останавливается само, если оно не было запущено. Отчёт печатается
и сохраняется в local/bench/5g-latency-<время>.json. Запуск от пользователя: sudo
нужен для ip netns и chroot.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from provision import read_env  # noqa: E402

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


def tunnel_packets(n):
    stats = json.loads(ns(n, "ip", "-s", "-j", "link", "show", "oaitun_ue1"))[0]["stats64"]
    return stats["tx"]["packets"], stats["rx"]["packets"]


def ping(command):
    output = sh(*command, check=False)
    loss = re.search(r"([\d.]+)% packet loss", output)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms", output)
    if not rtt:
        raise RuntimeError(f"ping без ответа: {' '.join(command[-3:])}")
    keys = ("min_ms", "avg_ms", "max_ms", "mdev_ms")
    return {"loss_pct": float(loss.group(1)), **dict(zip(keys, map(float, rtt.groups())))}


def summary(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "n": len(values),
        "median": round(statistics.median(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


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
    sh(
        "sudo",
        "chroot",
        str(JAIL),
        "espeak-ng",
        "-v",
        voice,
        "-s",
        rate,
        "-w",
        "/tmp/bench.wav",
        PHRASE,
    )
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

    def say_once(self, phrase_seconds):
        offset = self.mark()
        self.send("cl\n")
        time.sleep(1)
        rows = re.findall(r"^Port #0*(\d+)\[[^\]]*\]\s+(\S+)", "\n".join(self.lines(offset)), re.M)
        player = [number for number, label in rows if label.endswith(".wav")][-1]
        call = [number for number, label in rows if label.startswith("sip:")][-1]
        self.send(f"cc\n{player}\n{call}\n")
        time.sleep(phrase_seconds + 0.5)
        self.send(f"cd\n{player}\n{call}\n")

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


def network(settings):
    rows = {}
    for n in (1, 2):
        ns(n, "ip", "route", "replace", settings["LAB_NETWORK_CIDR"], "dev", "oaitun_ue1")
        route = ns(n, "ip", "route", "get", settings["PCSCF_IP"])
        before = tunnel_packets(n)
        result = ping(["sudo", "ip", "netns", "exec", f"ue{n}", "ping", "-c", "30", "-i", "0.2",
                       settings["PCSCF_IP"]])  # fmt: skip
        after = tunnel_packets(n)
        result["route_via_tunnel"] = " dev oaitun_ue1 " in f" {route} "
        result["tunnel_tx_packets"] = after[0] - before[0]
        result["tunnel_rx_packets"] = after[1] - before[1]
        rows[f"ue{n}_via_5g"] = result
    rows["host_direct"] = ping(["ping", "-c", "30", "-i", "0.2", settings["PCSCF_IP"]])
    return rows


def ai_round(client, settings, phrase_seconds):
    started, offset = time.time(), client.mark()
    client.send(f"m\nsip:{settings['VOICE_TRANSLATOR_MSISDN']}@{settings['IMS_DOMAIN']}\n")
    setup = client.between_ms(r"TX .*Request msg INVITE", r"Response msg 200/INVITE", offset)

    def voice(reason):
        events = query("lab-voice-agent", "VOICE_AGENT_HTTP_PORT", "/status").get("events", [])
        return [e for e in events if e.get("event") == "tts_sent" and e.get("reason") == reason
                and e.get("at", 0) >= started]  # fmt: skip

    wait_for(lambda: voice("greeting"), 30, "нет приветствия Voice Agent")
    client.say_once(phrase_seconds)

    def utterances():
        events = query("lab-ai-worker", "AI_WORKER_PORT", "/events").get("events", [])
        return [e for e in events if e.get("processed_at", 0) >= started]

    def reply():
        sent = {e.get("reply_id"): e for e in voice("llm_reply")}
        for event in utterances():
            if event.get("reply_delivered") and event.get("reply_id") in sent:
                return event, sent[event["reply_id"]]
        return None

    # Ожидание по этапам: при отказе видно, где именно остановился конвейер.
    try:
        wait_for(utterances, 60, "AI Worker не получил или не распознал фразу")
        wait_for(lambda: any(e.get("reply_delivered") for e in utterances()), 60,
                 "AI Worker распознал фразу, но не отправил перевод")  # fmt: skip
        event, tts = wait_for(reply, 60, "перевод отправлен, но Voice Agent его не озвучил")
    finally:
        client.send("ha\n")
        time.sleep(3)
    speech_end, audible = event.get("last_voice_packet_at"), tts.get("first_voice_rtp_at")
    return {
        "invite_to_200_ms": setup,
        "speech_end_to_reply_rtp_ms": round((audible - speech_end) * 1000, 1),
        # От начала речи до готовой фразы: сама речь плюс пауза AI_UTTERANCE_SILENCE_MS.
        "speech_plus_pause_ms": round(event.get("sentence_assembly_ms", 0), 1),
        "queue_wait_ms": round(event.get("queue_wait_ms", 0), 1),
        "stt_ms": round(event.get("stt_processing_ms", 0), 1),
        "translation_ms": round(event.get("llm_processing_ms", 0), 1),
        "tts_synthesis_ms": round(tts.get("synthesis_ms", 0), 1),
    }


def sip_rounds(clients, settings, rounds):
    register = [c.between_ms(r"TX .*Request msg REGISTER", r"Response msg 200/REGISTER", 0, 60)
                for c in clients]  # fmt: skip
    ringing, answered = [], []
    caller = clients[0]
    for _ in range(rounds):
        offset = caller.mark()
        caller.send(f"m\nsip:{settings['UE2_MSISDN']}@{settings['IMS_DOMAIN']}\n")
        invite = r"TX .*Request msg INVITE"
        answered.append(caller.between_ms(invite, r"Response msg 200/INVITE", offset))
        # С --auto-answer=200 вызываемый может ответить сразу, без 180: тогда пропуск.
        if caller.first(r"Response msg 180/INVITE", offset):
            ringing.append(caller.between_ms(invite, r"Response msg 180/INVITE", offset))
        time.sleep(2)
        caller.send("ha\n")
        time.sleep(3)
    return {"register_ms": register, "invite_to_180_ms": ringing, "invite_to_200_ms": answered}


def report(result):
    net, sip, ai = result["network"], result["sip"], result["ai"]
    via = [net[f"ue{n}_via_5g"]["avg_ms"] for n in (1, 2)]
    print("\n===== Путь =====")
    for n in (1, 2):
        row = net[f"ue{n}_via_5g"]
        ok = row["route_via_tunnel"] and row["tunnel_tx_packets"] >= 30
        print(f"UE{n}: маршрут в oaitun_ue1, пакеты туннеля TX {row['tunnel_tx_packets']} "
              f"RX {row['tunnel_rx_packets']} — {'через 5G' if ok else 'ПРОВЕРЬТЕ ПУТЬ'}")  # fmt: skip
    print("\n===== Сеть (RTT ping до P-CSCF, мс) =====")
    for name, row in net.items():
        print(f"{name:14} avg {row['avg_ms']:7.2f}  min {row['min_ms']:7.2f}  "
              f"max {row['max_ms']:7.2f}  потери {row['loss_pct']}%")  # fmt: skip
    print(f"5G добавляет к RTT: {statistics.mean(via) - net['host_direct']['avg_ms']:.2f} мс")
    print("\n===== Медианы, мс (min–max, n) =====")
    rows = {
        "SIP REGISTER с Digest": summary(sip["register_ms"]),
        "INVITE UE1->UE2 до 180": summary(sip["invite_to_180_ms"]),
        "INVITE UE1->UE2 до 200": summary(sip["invite_to_200_ms"]),
    }
    for key in ai[0] if ai else []:
        rows[f"переводчик: {key}"] = summary([r[key] for r in ai])
    for name, row in rows.items():
        if row:
            print(f"{name:45} {row['median']:9.1f}  ({row['min']}–{row['max']}, n={row['n']})")
    if ai:
        total = summary([r["speech_end_to_reply_rtp_ms"] + statistics.mean(via) for r in ai])
        print(f"\nОценка «конец речи -> перевод в трубке» (AI + RTT 5G): {total['median']:.0f} мс")
    for error in result.get("ai_errors", []):
        print(f"ОТКАЗ переводчика: {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=3, help="повторов вызовов (по умолчанию 3)")
    args = parser.parse_args()
    settings = read_env()
    sh("sudo", "-v", timeout=300)
    WORK.mkdir(parents=True, exist_ok=True)

    started_radio = not (tunnel_ip(1) and tunnel_ip(2))
    if started_radio:
        subprocess.run([str(ROOT / "scripts/rfsim.sh"), "up"], check=True)
    clients = []
    try:
        addresses = {n: tunnel_ip(n) for n in (1, 2)}
        print(f"UE1 {addresses[1]}, UE2 {addresses[2]}: сеть...", flush=True)
        result = {"mode": settings.get("AI_MODE"), "network": network(settings)}
        prepare_jail()
        phrase_seconds = prepare_phrase(settings)
        clients = [Client(n, addresses[n], settings) for n in (1, 2)]
        print("SIP...", flush=True)
        result["sip"] = sip_rounds(clients, settings, args.rounds)
        print("AI...", flush=True)
        result["ai"], result["ai_errors"] = [], []
        for _ in range(args.rounds):
            # Плеер PJSUA продвигается, только пока подключён к вызову: после первого
            # раунда он стоит в паузе файла. Новый клиент играет фразу с начала.
            clients[0].stop()
            clients[0] = Client(1, addresses[1], settings)
            # Отказ одного вызова не отменяет уже снятые замеры сети и SIP.
            try:
                result["sip"]["register_ms"].append(
                    clients[0].between_ms(
                        r"TX .*Request msg REGISTER", r"Response msg 200/REGISTER", 0, 60
                    )
                )
                result["ai"].append(ai_round(clients[0], settings, phrase_seconds))
            except (RuntimeError, TimeoutError, IndexError) as error:
                print(f"  переводчик: {error}", flush=True)
                result["ai_errors"].append(str(error))
    finally:
        for client in clients:
            client.stop()
        if started_radio:
            subprocess.run([str(ROOT / "scripts/rfsim.sh"), "down"], check=False)

    report(result)
    folder = ROOT / "local/bench"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"5g-latency-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
