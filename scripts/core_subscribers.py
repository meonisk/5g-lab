"""Абоненты в UDR ядра OAI: UE1/UE2 из lab.env и исследовательские SIM.

У телефона один Ki/OPc на две проверки: 5G AKA в ядре (эта база) и IMS AKA в
PyHSS (provision.py). Здесь пишется только база ядра — oai_db в контейнере
MySQL ядра (`OAI_MYSQL_CONTAINER`, по умолчанию `mysql`); учётные данные базы
берутся из `$OAI_CORE_DIR/conf/config.yaml`.

  python3 scripts/core_subscribers.py check          # кто есть в UDR, без ключей
  python3 scripts/core_subscribers.py apply          # завести недостающих
  python3 scripts/core_subscribers.py sql --output local/private/udr.sql

Существующие записи не перезаписываются: SQN карты и UDR сохраняется, другие
ключи у того же IMSI — ошибка. Данные сессий (DNN, срез, QoS) копируются с уже
заведённого абонента ядра, у которого есть DNN `IMS_DNN`: так сохраняются
настройки партнёра; статический адрес из шаблона не переносится.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from provision import read_env
from research_sims import load_sims

ROOT = Path(__file__).resolve().parents[1]
SQN = '{"sqn": "000000000000", "sqnScheme": "NON_TIME_BASED", "lastIndexes": {"ausf": 0}}'


def core_dir(settings) -> Path:
    raw = os.environ.get("OAI_CORE_DIR") or settings.get("OAI_CORE_DIR") or "~/oai-cn5g"
    return Path(raw).expanduser()


def database(settings) -> dict[str, str]:
    """Блок database: из config.yaml ядра (user, password, database_name)."""
    text = (core_dir(settings) / "conf/config.yaml").read_text(encoding="utf-8")
    block = re.search(r"(?m)^database:\n((?:[ \t]+.*\n?)+)", text)
    if block is None:
        raise RuntimeError("В config.yaml ядра нет блока database:")
    values = dict(re.findall(r"(?m)^\s+(\w+):\s*\"?([^\"#\s]+)", block.group(1)))
    return {key: values[key] for key in ("user", "password", "database_name")}


def entries(settings) -> list[dict[str, str]]:
    """UE1/UE2 — эмулируемые телефоны rfsim; SIM — из приватного списка, если он есть."""
    result = [
        {
            "name": prefix,
            "imsi": settings[f"{prefix}_IMSI"],
            "ki": settings[f"{prefix}_IMS_K"].upper(),
            "opc": settings[f"{prefix}_IMS_OPC"].upper(),
            "amf": settings[f"{prefix}_IMS_AMF"],
        }
        for prefix in ("UE1", "UE2")
    ]
    for sim in load_sims(settings, required=False):
        result.append(
            {
                "name": f"SIM {sim['MSISDN']}",
                "imsi": sim["IMSI"],
                "ki": sim["KI"],
                "opc": sim["OPC"],
                "amf": sim["AMF"],
            }
        )
    for entry in result:
        if not entry["imsi"].startswith(settings["MCC"] + settings["MNC"]):
            raise ValueError(
                f"{entry['name']}: IMSI не из PLMN {settings['MCC']}/{settings['MNC']}"
            )
    return result


def literal(value: str) -> str:
    """Значение SQL без экранирования строк: шестнадцатеричная запись UTF-8."""
    return f"CONVERT(0x{value.encode('utf-8').hex()} USING utf8mb4)"


class Udr:
    def __init__(self, settings):
        self.db = database(settings)
        self.container = (
            os.environ.get("OAI_MYSQL_CONTAINER") or settings.get("OAI_MYSQL_CONTAINER") or "mysql"
        )

    def query(self, sql: str) -> list[list[str]]:
        # Пароль — через окружение процесса mysql, не в командной строке.
        command = [
            "docker",
            "exec",
            "-i",
            "-e",
            f"MYSQL_PWD={self.db['password']}",
            self.container,
            "mysql",
            "-u",
            self.db["user"],
            "-N",
            "-B",
            "-r",
            self.db["database_name"],
        ]
        result = subprocess.run(
            command, input=sql.encode(), capture_output=True, timeout=60, check=False
        )
        if result.returncode:
            # Текст ошибки MySQL может содержать фрагменты запроса с ключами.
            raise RuntimeError(
                f"UDR ({self.container}): запрос не выполнен, код {result.returncode}"
            )
        lines = result.stdout.decode("utf-8").splitlines()
        return [line.split("\t") for line in lines if line]


def present(udr, settings, imsis) -> dict[str, tuple[str, str]]:
    if not imsis:
        return {}
    listed = ", ".join(literal(imsi) for imsi in imsis)
    rows = udr.query(
        "SELECT ueid, UPPER(encPermanentKey), UPPER(encOpcKey) FROM AuthenticationSubscription "
        f"WHERE ueid IN ({listed});"
    )
    return {row[0]: (row[1], row[2]) for row in rows}


def session_template(udr, settings) -> tuple[str, str]:
    """Срез и DNN уже работающего абонента ядра с DNN IMS; статический IP убирается."""
    dnn = settings["IMS_DNN"]
    rows = udr.query(
        "SELECT singleNssai, dnnConfigurations FROM SessionManagementSubscriptionData "
        f"WHERE JSON_CONTAINS_PATH(dnnConfigurations, 'one', {literal('$.' + dnn)}) LIMIT 1;"
    )
    if not rows:
        raise RuntimeError(
            f"В UDR нет ни одного абонента с DNN {dnn}: не с чего скопировать данные сессий"
        )
    nssai, dnns = rows[0][0], json.loads(rows[0][1])
    for config in dnns.values():
        config.pop("staticIpAddress", None)
    return nssai, json.dumps(dnns, separators=(",", ":"))


def statements(settings, todo, template) -> str:
    plmn = settings["MCC"] + settings["MNC"]
    nssai, dnns = template
    sql = []
    for entry in todo:
        imsi = literal(entry["imsi"])
        sql.append(
            "INSERT INTO AuthenticationSubscription (ueid, authenticationMethod, encPermanentKey, "
            "protectionParameterId, sequenceNumber, authenticationManagementField, algorithmId, "
            f"encOpcKey, supi) VALUES ({imsi}, '5G_AKA', {literal(entry['ki'])}, "
            f"{literal(entry['ki'])}, {literal(SQN)}, {literal(entry['amf'])}, 'milenage', "
            f"{literal(entry['opc'])}, {imsi}) ON DUPLICATE KEY UPDATE ueid = ueid;"
        )
        sql.append(
            "INSERT INTO SessionManagementSubscriptionData (ueid, servingPlmnid, singleNssai, "
            f"dnnConfigurations) VALUES ({imsi}, {literal(plmn)}, {literal(nssai)}, "
            f"{literal(dnns)}) ON DUPLICATE KEY UPDATE ueid = ueid;"
        )
    return "\n".join(sql) + "\n"


def plan(udr, settings):
    """Кого заводить; расхождение ключей с уже заведённым IMSI — ошибка до записи."""
    wanted = entries(settings)
    existing = present(udr, settings, [entry["imsi"] for entry in wanted])
    todo = []
    for entry in wanted:
        keys = existing.get(entry["imsi"])
        if keys is None:
            todo.append(entry)
        elif keys != (entry["ki"], entry["opc"]):
            raise RuntimeError(
                f"{entry['name']}: IMSI {entry['imsi']} уже в UDR с другими ключами; "
                "проверьте lab.env/список SIM, SQN не сбрасывайте"
            )
    return wanted, todo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=("check", "apply", "sql"))
    parser.add_argument("--output", type=Path, help="Файл SQL для команды sql (внутри local/)")
    args = parser.parse_args(argv)
    settings = read_env()
    udr = Udr(settings)
    wanted, todo = plan(udr, settings)

    if args.command == "check":
        for entry in wanted:
            state = "нет в UDR" if entry in todo else "в UDR"
            print(f"  {entry['name']:<10} IMSI {entry['imsi']}: {state}")
        return 1 if todo else 0

    sql = statements(settings, todo, session_template(udr, settings)) if todo else ""
    if args.command == "sql":
        output = (args.output or ROOT / "local/private/core-subscribers.sql").resolve()
        if ROOT / "local" not in output.parents:
            raise ValueError("Файл SQL с ключами должен лежать внутри local/")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(sql.encode())
        os.chmod(output, 0o600)
        print(f"SQL для {len(todo)} абонентов: {output.relative_to(ROOT)}")
        return 0

    if sql:
        udr.query(sql)
    print(f"UDR ядра: заведено {len(todo)}, уже были {len(wanted) - len(todo)}; SQN не менялся")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
