"""Проверка стенда перед звонками с настоящих телефонов и наблюдение во время них.

  python scripts/stand_check.py            # preflight: всё ли готово к телефону
  python scripts/stand_check.py phones     # какие исследовательские SIM зарегистрированы
  python scripts/stand_check.py watch      # живой журнал REGISTER/INVITE/AI во время звонка
  python scripts/stand_check.py collect    # сохранить журналы в local/evidence/ для разбора

Команды только читают состояние стенда. Исключение — самотест preflight: один
синтетический AI-вызов внутри lab-sip-as (183/PRACK/UPDATE/200/BYE). Не
запускайте его одновременно с интеграционными проверками: стенд общий.
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import research_sims

ROOT = Path(__file__).resolve().parents[1]
IMS_CONTAINERS = (
    "lab-dns",
    "lab-mysql",
    "lab-pyhss",
    "lab-icscf",
    "lab-scscf",
    "lab-pcscf",
    "lab-rtpengine",
)
AI_CONTAINERS = ("lab-sip-as", "lab-voice-agent", "lab-media-adapter", "lab-ai-worker")
CORE_CONTAINERS = (
    "lab-oai-db",
    "lab-nrf",
    "lab-udr",
    "lab-udm",
    "lab-ausf",
    "lab-amf",
    "lab-smf",
    "lab-upf",
)
results = []
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
    print(f"[{marker}] {name}" + (f"\n         → {hint}" if hint and status != "PASS" else ""))


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
        sims = research_sims.load(env)
        report(
            "PASS", f"Список SIM: {len(sims)} карт, номера {sims[0]['MSISDN']}…{sims[-1]['MSISDN']}"
        )
        return sims
    except ValueError as error:
        report("FAIL", "Список исследовательских SIM", f"{error}; см. docs/research-sims.md")
        return []


def check_containers():
    for name in IMS_CONTAINERS + AI_CONTAINERS:
        report(
            "PASS" if running(name) else "FAIL",
            f"Контейнер {name} запущен",
            "запустите стенд: python scripts/start_lab.py (или start_partner.py)",
        )
    local_core = running("lab-oai-db")
    if local_core:
        for name in CORE_CONTAINERS:
            report("PASS" if running(name) else "FAIL", f"Контейнер {name} запущен")
    else:
        report(
            "WARN",
            "Локального OAI нет: ядро и радиосеть у партнёров",
            "SIM должны быть заведены в их UDR: research_sims.py oai-sql",
        )
    return local_core


def check_versions():
    # Старые контейнеры не знают о preconditions: нужен пересобранный/пересозданный сервис.
    code, _ = docker("exec", "lab-sip-as", "test", "-f", "/app/ims_sip/agent_dialog.py")
    report(
        "PASS" if code == 0 else "FAIL",
        "SIP AS содержит поддержку 100rel/preconditions",
        "пересоберите: scripts/compose.sh up -d --build --force-recreate sip-as",
    )
    code, rtp = docker("exec", "lab-pcscf", "cat", "/etc/kamailio_pcscf/route/rtp.cfg")
    ok = code == 0 and 'is_in_profile("as"' in rtp and "(;.*)?$" in rtp
    report(
        "PASS" if ok else "FAIL",
        "P-CSCF: якорение ответа AS на UPDATE и номера с phone-context",
        "пересоздайте: scripts/compose.sh up -d --force-recreate pcscf",
    )


def check_sims(env, sims, local_core):
    if not sims:
        return
    try:
        state = research_sims.status(env, sims, ims_only=not local_core)
    except RuntimeError as error:
        report("FAIL", "Чтение баз абонентов", str(error))
        return
    for key, title in (("pyhss", "PyHSS"), ("oai_udr", "OAI UDR")):
        if key in state:
            found = len(state[key])
            report(
                "PASS" if found == len(sims) else "FAIL",
                f"{title}: заведено SIM {found}/{len(sims)}",
                "python scripts/research_sims.py apply" + ("" if local_core else " --ims-only"),
            )


def check_codecs():
    import phone_readiness

    for item in phone_readiness.inspect()["checks"]:
        if item["check"].startswith("codec_"):
            report(
                "PASS" if item["status"] == "PASS" else "FAIL",
                f"RTPengine: {item['check'][6:].replace('_bidirectional', '')} в обе стороны",
                "пересоберите rtpengine (libavcodec-extra), см. docs/native-phone.md",
            )


def check_ai_call():
    if not running("lab-sip-as") or not running("lab-voice-agent"):
        report("FAIL", "Самотест AI-вызова пропущен: SIP AS или Voice Agent не запущены")
        return
    script = (ROOT / "scripts/stand_check_uac.py").read_text(encoding="utf-8")
    code, output = docker("exec", "-i", "lab-sip-as", "python", "-", stdin=script, timeout=60)
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
            "docker logs --tail 50 lab-sip-as; Voice Agent: docker logs --tail 50 lab-voice-agent",
        )
    if len(steps) < 5:
        report("FAIL", "Самотест AI-вызова завершён не полностью")


def preflight():
    env = research_sims.environment()
    print("== 1. Конфигурация")
    sims = check_config(env)
    print("== 2. Контейнеры")
    local_core = check_containers()
    print("== 3. Версии сервисов")
    check_versions()
    print("== 4. Абоненты")
    check_sims(env, sims, local_core)
    print("== 5. Медиа")
    check_codecs()
    print("== 6. Самотест AI-вызова (без телефона)")
    check_ai_call()

    failed = results.count("FAIL")
    print()
    if failed:
        print(f"СТЕНД НЕ ГОТОВ: {failed} проблем(ы); исправьте по подсказкам и повторите")
        return 1
    print("СТЕНД ГОТОВ К ТЕЛЕФОНУ — дальше: docs/stand-check.md, раздел «С телефоном»")
    return 0


def registered(env, sims, since="2h"):
    """IMSI -> IMS-адрес телефона по последнему «Contact valid» в S-CSCF."""
    _, logs = docker("logs", "--since", since, "lab-scscf", timeout=60)
    found = {}
    for sim in sims:
        for address in re.findall(rf"{sim['IMSI']}@([0-9.]+)[^\n]*Contact valid", logs):
            found[sim["IMSI"]] = address
    return found


def phones():
    env = research_sims.environment()
    sims = research_sims.load(env)
    found = registered(env, sims)
    for sim in sims:
        state = f"зарегистрирована, IMS-адрес {found[sim['IMSI']]}" if sim["IMSI"] in found else "—"
        print(f"  {sim['MSISDN']}  IMSI {sim['IMSI']}  {state}")
    print(f"Зарегистрировано в IMS: {len(found)} из {len(sims)} (по журналу S-CSCF за 2 ч)")
    return 0 if found else 1


def watch():
    env = research_sims.environment()
    sims = research_sims.load(env)
    numbers = [s["MSISDN"] for s in sims] + [s["IMSI"] for s in sims]
    numbers += [env[k] for k in env if k.startswith("VOICE_") and k.endswith("_MSISDN")]
    pattern = re.compile(
        r"(REGISTER|INVITE|PRACK|UPDATE|BYE|CANCEL|Contact valid|AS |[45]\d\d |"
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
                print(f"{name[4:]:>10} | {line.rstrip()[:220]}", flush=True)

    print("Слежу за P-CSCF, S-CSCF и SIP AS; Ctrl+C — выход. Звоните с телефона.")
    for name in ("lab-pcscf", "lab-scscf", "lab-sip-as"):
        threading.Thread(target=follow, args=(name,), daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        return 0


def collect(since="3h"):
    """Журналы для разбора после испытаний; каталог local/ не попадает в Git."""
    target = ROOT / "local/evidence" / time.strftime("stand-%Y%m%dT%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    names = IMS_CONTAINERS + AI_CONTAINERS + CORE_CONTAINERS
    for name in names:
        code, logs = docker("logs", "--since", since, name, timeout=120)
        if code:
            continue
        kept = [line for line in logs.splitlines() if not SECRET.search(line)]
        (target / f"{name}.log").write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"Журналы за {since} сохранены в {target.relative_to(ROOT)}; строки с ключами удалены")
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
    from script_console import configure_output

    configure_output()
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
