"""Проверка стенда перед звонками с настоящих SIM и наблюдение во время них.

  python3 scripts/stand_check.py            # preflight: всё ли готово к телефону
  python3 scripts/stand_check.py phones     # какие исследовательские SIM в IMS
  python3 scripts/stand_check.py watch      # живой журнал REGISTER/INVITE во время звонка
  python3 scripts/stand_check.py collect    # журналы в local/evidence/ для разбора

Команды только читают состояние. Исключение — самотест preflight: один
синтетический AI-вызов внутри lab-sip-as (183/PRACK/UPDATE/200/BYE). Не
запускайте его одновременно с интеграционными проверками: стенд общий.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from provision import PyHSS, read_env
from research_sims import load_sims

ROOT = Path(__file__).resolve().parents[1]
IMS = ("lab-dns", "lab-mysql", "lab-pyhss", "lab-icscf", "lab-scscf", "lab-pcscf", "lab-rtpengine")
AI = ("lab-sip-as", "lab-voice-agent", "lab-media-adapter", "lab-ai-worker")
CORE = ("oai-nrf", "oai-udr", "oai-udm", "oai-ausf", "oai-amf", "oai-smf", "oai-upf")
results: list[str] = []
# Строки с материалом аутентификации не печатаются и не сохраняются.
SECRET = re.compile(
    r"(?i)(nonce|response=|\bck=|\bik=|opc|\bki\b|authorization|password|\brand\b|\bautn\b)"
)


def docker(*arguments, stdin=None, timeout=30):
    try:
        done = subprocess.run(
            ["docker", *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return done.returncode, done.stdout + done.stderr
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, type(error).__name__


def report(status, name, hint=""):
    results.append(status)
    marker = {"PASS": "OK  ", "FAIL": "FAIL", "WARN": "WARN"}[status]
    print(f"[{marker}] {name}" + (f"\n         -> {hint}" if hint and status != "PASS" else ""))


def running(name):
    code, output = docker("inspect", "--format", "{{.State.Running}}", name)
    return code == 0 and output.strip() == "true"


def check_config(env):
    expected = f"ims.mnc{env['MNC'].zfill(3)}.mcc{env['MCC']}.3gppnetwork.org"
    report(
        "PASS" if env["IMS_DOMAIN"] == expected else "FAIL",
        f"lab.env: PLMN {env['MCC']}/{env['MNC']}, IMS-домен {env['IMS_DOMAIN']}",
        f"IMS_DOMAIN должен быть {expected}",
    )
    try:
        sims = load_sims(env)
    except ValueError as error:
        report("FAIL", "Список исследовательских SIM", str(error))
        return []
    report("PASS", f"Список SIM: {len(sims)} карт, номера {sims[0]['MSISDN']}…{sims[-1]['MSISDN']}")
    return sims


def check_containers():
    for name in IMS + AI + CORE:
        report(
            "PASS" if running(name) else "FAIL",
            f"Контейнер {name} запущен",
            "ядро: scripts/core-setup.sh apply; IMS и AI: scripts/setup.sh",
        )


def check_core_plmn(env):
    # AMF печатает PLMN из конфигурации при старте; надёжнее читать сам config.yaml.
    from core_subscribers import core_dir

    path = core_dir(env) / "conf/config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        report("FAIL", f"Конфигурация ядра {path}", str(error))
        return
    pairs = set(
        zip(
            re.findall(r"(?m)^\s*-?\s*mcc:\s*\"?(\d+)", text),
            re.findall(r"(?m)^\s*-?\s*mnc:\s*\"?(\d+)", text),
        )
    )
    ok = pairs == {(env["MCC"], env["MNC"])}
    report(
        "PASS" if ok else "FAIL",
        f"Ядро OAI: PLMN {sorted(pairs)}",
        f"нужно {env['MCC']}/{env['MNC']}: scripts/core-setup.sh apply",
    )


def check_versions():
    # Старый образ не знает preconditions: нужен пересобранный сервис.
    code, _ = docker("exec", "lab-sip-as", "test", "-f", "/app/ims_sip/core/preconditions.py")
    report(
        "PASS" if code == 0 else "FAIL",
        "SIP AS поддерживает 100rel/preconditions",
        "пересоберите стенд: scripts/setup.sh",
    )


def check_sims(env, sims):
    if not sims:
        return
    from core_subscribers import Udr, present

    imsis = [sim["IMSI"] for sim in sims]
    try:
        listed = PyHSS(env).call("GET", "/ims_subscriber/list?page=0&page_size=1000") or []
        in_hss = {row.get("imsi") for row in listed} & set(imsis)
        in_udr = set(present(Udr(env), env, imsis))
    except (RuntimeError, OSError) as error:
        report("FAIL", "Чтение баз абонентов", str(error))
        return
    for title, found, fix in (
        ("UDR ядра", in_udr, "scripts/core-setup.sh apply"),
        ("PyHSS", in_hss, "scripts/setup.sh (provision.py)"),
    ):
        report(
            "PASS" if len(found) == len(imsis) else "FAIL",
            f"{title}: заведено SIM {len(found)}/{len(imsis)}",
            fix,
        )


def check_ai_call():
    if not running("lab-sip-as") or not running("lab-voice-agent"):
        report("FAIL", "Самотест AI-вызова пропущен: SIP AS или Voice Agent не запущены")
        return
    script = (ROOT / "scripts/stand_check_uac.py").read_text(encoding="utf-8")
    _, output = docker("exec", "-i", "lab-sip-as", "python", "-", stdin=script, timeout=60)
    try:
        steps = json.loads(output.strip().splitlines()[-1])["steps"]
    except (ValueError, IndexError, KeyError):
        report(
            "FAIL", "Самотест AI-вызова с preconditions", "не запустился: docker logs lab-sip-as"
        )
        return
    for step in steps:
        report(
            step["status"],
            f"Самотест AI: {step['step']} ({step['response']})",
            "docker logs --tail 50 lab-sip-as; docker logs --tail 50 lab-voice-agent",
        )
    if len(steps) < 5:
        report("FAIL", "Самотест AI-вызова завершён не полностью")


def preflight():
    env = read_env()
    print("== 1. Конфигурация")
    sims = check_config(env)
    print("== 2. Контейнеры и ядро")
    check_containers()
    check_core_plmn(env)
    print("== 3. Версии сервисов")
    check_versions()
    print("== 4. Абоненты")
    check_sims(env, sims)
    print("== 5. Самотест AI-вызова (без телефона)")
    check_ai_call()

    failed = results.count("FAIL")
    print()
    if failed:
        print(f"СТЕНД НЕ ГОТОВ: {failed} проблем(ы); исправьте по подсказкам и повторите")
        return 1
    print("СТЕНД ГОТОВ К ТЕЛЕФОНУ: вставьте SIM, включите VoLTE/VoNR, позвоните на номер AI")
    return 0


def registered(sims, since="2h"):
    """IMSI -> IMS-адрес телефона по последнему «Contact valid» в S-CSCF."""
    _, logs = docker("logs", "--since", since, "lab-scscf", timeout=60)
    found = {}
    for sim in sims:
        for address in re.findall(rf"{sim['IMSI']}@([0-9.]+)[^\n]*Contact valid", logs):
            found[sim["IMSI"]] = address
    return found


def phones():
    sims = load_sims(read_env())
    found = registered(sims)
    for sim in sims:
        state = f"в IMS, адрес {found[sim['IMSI']]}" if sim["IMSI"] in found else "-"
        print(f"  {sim['MSISDN']}  IMSI {sim['IMSI']}  {state}")
    print(f"Зарегистрировано в IMS: {len(found)} из {len(sims)} (журнал S-CSCF за 2 ч)")
    return 0 if found else 1


def watch():
    env = read_env()
    sims = load_sims(env)
    numbers = [s["MSISDN"] for s in sims] + [s["IMSI"] for s in sims]
    numbers += [env[k] for k in env if k.startswith("VOICE_") and k.endswith("_MSISDN")]
    pattern = re.compile(
        r"(REGISTER|INVITE|PRACK|UPDATE|BYE|CANCEL|Contact valid|[45]\d\d |Registration|"
        + "|".join(map(re.escape, set(numbers)))
        + ")"
    )

    def follow(name):
        process = subprocess.Popen(
            ["docker", "logs", "-f", "--since", "1s", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in process.stdout:
            if pattern.search(line) and not SECRET.search(line):
                print(f"{name:>12} | {line.rstrip()[:220]}", flush=True)

    print("Слежу за AMF, P-CSCF, S-CSCF и SIP AS; Ctrl+C - выход. Звоните с телефона.")
    for name in ("oai-amf", "lab-pcscf", "lab-scscf", "lab-sip-as"):
        threading.Thread(target=follow, args=(name,), daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        return 0


def collect(since="3h"):
    """Журналы для разбора после испытаний; каталог local/ не попадает в Git."""
    target = ROOT / "local/evidence" / time.strftime("stand-%Y%m%dT%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    for name in IMS + AI + CORE:
        code, logs = docker("logs", "--since", since, name, timeout=120)
        if code:
            continue
        kept = [line for line in logs.splitlines() if not SECRET.search(line)]
        (target / f"{name}.log").write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"Журналы за {since}: {target.relative_to(ROOT)}; строки с ключами удалены")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="preflight",
        choices=("preflight", "phones", "watch", "collect"),
    )
    command = parser.parse_args().command
    return {"preflight": preflight, "phones": phones, "watch": watch, "collect": collect}[command]()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
