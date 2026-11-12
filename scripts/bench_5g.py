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
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "scripts/lib")]
from latency import stage_row, summary  # noqa: E402
from provision import read_env  # noqa: E402
from ue5g import (  # noqa: E402
    WORK,
    Client,
    ns,
    prepare_jail,
    prepare_phrase,
    sh,
    translator_call,
    tunnel_ip,
)


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
    setup, event, tts = translator_call(client, settings, phrase_seconds)
    return {"invite_to_200_ms": setup, **stage_row(event, tts)}


def sip_rounds(clients, settings, rounds):
    register = [c.registered_ms() for c in clients]
    ringing, answered = [], []
    # UE1 подписан на translate,record: замер SIP без услуг — вызов UE2 -> UE1.
    caller = clients[1]
    for _ in range(rounds):
        offset = caller.mark()
        caller.send(f"m\nsip:{settings['UE1_MSISDN']}@{settings['IMS_DOMAIN']}\n")
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
                result["sip"]["register_ms"].append(clients[0].registered_ms())
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
