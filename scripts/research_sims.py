"""Исследовательские SIM: импорт, проверка и заведение в OAI UDR и PyHSS.

Команды (по умолчанию ничего не меняют):
  import <таблица.xlsx|csv>  — перенести нужные поля в local/secrets/research-sims.csv;
  plan                        — проверить список и показать IMSI/MSISDN/IMPI без ключей;
  apply [--ims-only]          — завести абонентов: OAI UDR (если не --ims-only) и PyHSS;
  status                      — только чтение: какие SIM уже есть в базах;
  retire --imsi <IMSI> [--apply] — убрать из PyHSS абонентов прежнего PLMN;
  retire --foreign-plmn [--apply] — то же для всех IMSI вне PLMN lab.env;
  oai-sql --output <файл>     — приватный SQL для UDR партнёров (OAI MySQL).

У физической SIM один Ki/OPc: он используется и для 5G AKA (UDR), и для IMS AKA
(PyHSS AuC). Существующие записи не перезаписываются: SQN карты и баз сохраняется.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from initialize_local import read_values
from research_sim_inventory import ims_identity, read_csv, read_source, validate, write_private_csv

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ENV = ROOT / "app/config/lab.env"
SECRET_ENV = ROOT / "local/secrets/ims.env"


def environment() -> dict[str, str]:
    values = read_values(PUBLIC_ENV)
    if SECRET_ENV.exists():
        values.update(read_values(SECRET_ENV))
    return values


def sim_file(env: dict[str, str]) -> Path:
    path = Path(env["RESEARCH_SIM_FILE"])
    path = path if path.is_absolute() else ROOT / path
    # Файл с Ki/OPc допускается только в игнорируемом каталоге local/.
    if ROOT / "local" not in path.resolve().parents:
        raise ValueError("RESEARCH_SIM_FILE должен находиться внутри local/ (игнорируется Git)")
    return path


def load(env: dict[str, str]) -> list[dict[str, str]]:
    path = sim_file(env)
    if not path.exists():
        raise ValueError(f"Нет файла SIM {path.relative_to(ROOT)}; сначала выполните import")
    return validate(read_csv(path), env)


# --- OAI UDR -----------------------------------------------------------------


def oai_statements(env, sims):
    from oai_subscribers import statements

    commands = []
    for sim in sims:
        commands.extend(statements(env, sim["IMSI"], (sim["KI"], sim["OPC"], sim["AMF"])))
    return commands


def provision_oai(env, sims):
    from oai_subscribers import query, sql_value

    for sim in sims:
        existing = query(
            "SELECT encPermanentKey,encOpcKey,authenticationManagementField "
            f"FROM AuthenticationSubscription WHERE ueid={sql_value(sim['IMSI'])};"
        )
        expected = [sim["KI"].lower(), sim["OPC"].lower(), sim["AMF"].lower()]
        if existing and existing.lower().split("\t") != expected:
            raise RuntimeError(
                f"OAI: ключи IMSI {sim['IMSI']} в UDR отличаются от карты; нужен отдельный перенос"
            )

    # Одна транзакция: либо заведены все SIM, либо ни одной.
    query("\n".join(["START TRANSACTION;", *oai_statements(env, sims), "COMMIT;"]))
    print(f"OAI UDR: заведено/подтверждено SIM: {len(sims)}; SQN существующих записей сохранён")


def oai_present(sims) -> set[str]:
    from oai_subscribers import query, sql_value

    listed = ",".join(sql_value(sim["IMSI"]) for sim in sims)
    rows = query(f"SELECT ueid FROM AuthenticationSubscription WHERE ueid IN ({listed});")
    return set(rows.split()) if rows else set()


# --- PyHSS -------------------------------------------------------------------


class Hss:
    """Минимальный клиент REST PyHSS; тела ответов с ключами не печатаются."""

    def __init__(self, env):
        self.base = env.get("PYHSS_API_BASE") or (
            f"http://{env['PYHSS_API_BIND']}:{env['PYHSS_API_PORT']}"
        )

    def call(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"PyHSS {method} {path.split('/')[1]}: HTTP {error.code}") from None
        except OSError as error:
            raise RuntimeError(f"PyHSS недоступен по {self.base}") from error
        return json.loads(body) if body else None

    def find(self, kind, imsi, key):
        rows = self.call("GET", f"/{kind}/list?page=0&page_size=1000") or []
        return next((row[key] for row in rows if row.get("imsi") == imsi), None)


def ensure_apn(hss, env):
    rows = hss.call("GET", "/apn/list?page=0&page_size=200") or []
    found = next((row["apn_id"] for row in rows if row.get("apn") == env["IMS_DNN"]), None)
    if found is not None:
        return found
    hss.call(
        "PUT",
        "/apn/",
        {
            "apn": env["IMS_DNN"],
            "ip_version": 0,
            "apn_ambr_dl": 1000000,
            "apn_ambr_ul": 1000000,
            "qci": 9,
            "arp_priority": 8,
            "arp_preemption_capability": False,
            "arp_preemption_vulnerability": True,
        },
    )
    return ensure_apn(hss, env)


def ensure_auc(hss, env, sim):
    from validate_ims_auc import validate_existing

    record = hss.call("GET", f"/auc/imsi/{sim['IMSI']}")
    if record is not None:
        expected = {"ki": sim["KI"], "opc": sim["OPC"], "amf": sim["AMF"]}
        auc_id = str(record["auc_id"])
        # Сравнение через read-only запрос к БД PyHSS; PATCH AuC сбросил бы SQN.
        if not validate_existing(record, sim["IMSI"], auc_id, expected, env["UE1_IMSI"]):
            raise RuntimeError(f"PyHSS: ключи AuC IMSI {sim['IMSI']} отличаются от карты")
        return record["auc_id"], "сохранён"
    # Начальный SQN как у bootstrap-абонентов; карта примет любой больший номер.
    payload = {
        "ki": sim["KI"],
        "opc": sim["OPC"],
        "amf": sim["AMF"],
        "sqn": 96,
        "imsi": sim["IMSI"],
    }
    if sim["ICCID"]:
        payload["iccid"] = sim["ICCID"]
    hss.call("PUT", "/auc/", payload)
    return hss.call("GET", f"/auc/imsi/{sim['IMSI']}")["auc_id"], "создан"


def upsert(hss, kind, key, imsi, payload):
    existing = hss.find(kind, imsi, key)
    if existing is None:
        hss.call("PUT", f"/{kind}/", payload)
        return "создан"
    hss.call("PATCH", f"/{kind}/{existing}", payload)
    return "обновлён"


def provision_hss(env, sims):
    hss = Hss(env)
    apn_id = ensure_apn(hss, env)
    domain, port = env["IMS_DOMAIN"], env["SCSCF_SIP_PORT"]
    for sim in sims:
        auc_id, auc_state = ensure_auc(hss, env, sim)
        subscriber = {
            "imsi": sim["IMSI"],
            "enabled": True,
            "auc_id": auc_id,
            "default_apn": apn_id,
            "apn_list": str(apn_id),
            "msisdn": sim["MSISDN"],
            "ue_ambr_dl": 1000000,
            "ue_ambr_ul": 1000000,
            "nam": 2,
            "roaming_enabled": False,
            "subscribed_rau_tau_timer": 600,
        }
        ims = {
            "imsi": sim["IMSI"],
            "msisdn": sim["MSISDN"],
            "ifc_path": "default_ifc.xml",
            "sh_template_path": "default_sh_user_data.xml",
            "scscf": f"sip:scscf.{domain}:{port}",
            "scscf_realm": domain,
            "scscf_peer": f"scscf.{domain}",
            "pcscf_realm": domain,
            "pcscf_peer": f"pcscf.{domain}",
        }
        states = (
            auc_state,
            upsert(hss, "subscriber", "subscriber_id", sim["IMSI"], subscriber),
            upsert(hss, "ims_subscriber", "ims_subscriber_id", sim["IMSI"], ims),
        )
        print(
            f"PyHSS: IMSI {sim['IMSI']} MSISDN {sim['MSISDN']}: AuC {states[0]}, "
            f"subscriber {states[1]}, IMS {states[2]}"
        )


def retire_hss(env, imsis, apply=False):
    """Удаляет из PyHSS устаревших абонентов (например, IMSI прежнего PLMN).

    После смены MCC/MNC старые записи UE1/UE2 сохраняют MSISDN 1001/1002 и
    мешают новым. Текущие UE1/UE2 и SIM из списка удалить нельзя.
    """
    protected = {env["UE1_IMSI"], env["UE2_IMSI"]}
    path = sim_file(env)
    if path.exists():
        protected.update(sim["IMSI"] for sim in validate(read_csv(path), env))
    if protected.intersection(imsis):
        raise ValueError("Нельзя удалить текущих UE1/UE2 или исследовательские SIM")
    hss = Hss(env)
    for imsi in imsis:
        auc = hss.call("GET", f"/auc/imsi/{imsi}")
        # Порядок важен: subscriber ссылается на AuC, IMS-запись — на IMSI.
        targets = [
            ("ims_subscriber", hss.find("ims_subscriber", imsi, "ims_subscriber_id")),
            ("subscriber", hss.find("subscriber", imsi, "subscriber_id")),
            ("auc", None if auc is None else auc["auc_id"]),
        ]
        found = [(kind, key) for kind, key in targets if key is not None]
        names = ", ".join(kind for kind, _ in found) or "нет записей"
        if not apply:
            print(f"DRY-RUN PyHSS: IMSI {imsi}: будет удалено: {names}")
            continue
        for kind, key in found:
            hss.call("DELETE", f"/{kind}/{key}")
        print(f"PyHSS: IMSI {imsi}: удалено: {names}")


def foreign_plmn_imsis(env) -> list[str]:
    """IMSI в PyHSS вне PLMN lab.env: после смены MCC/MNC это прежние UE1/UE2.

    Наш PyHSS заполняют только скрипты стенда, поэтому такие записи устарели:
    IMS-домен и IMPI выводятся из текущего PLMN, а номера 1001/1002 заняты ими.
    """
    hss = Hss(env)
    plmn = env["MCC"] + env["MNC"]
    found = set()
    for kind in ("ims_subscriber", "subscriber", "auc"):
        rows = hss.call("GET", f"/{kind}/list?page=0&page_size=1000") or []
        found.update(str(row.get("imsi") or "") for row in rows)
    return sorted(imsi for imsi in found if imsi and not imsi.startswith(plmn))


def hss_present(env, sims) -> set[str]:
    hss = Hss(env)
    rows = hss.call("GET", "/ims_subscriber/list?page=0&page_size=1000") or []
    listed = {row.get("imsi") for row in rows}
    return {sim["IMSI"] for sim in sims if sim["IMSI"] in listed}


def status(env, sims, ims_only=False) -> dict:
    """Только чтение. Возвращает IMSI, найденные в каждой базе, без ключей."""
    result = {"sims": len(sims), "pyhss": sorted(hss_present(env, sims))}
    if not ims_only:
        result["oai_udr"] = sorted(oai_present(sims))
    return result


# --- CLI ---------------------------------------------------------------------


def command_import(env, source: Path, force: bool):
    target = sim_file(env)
    if target.exists() and not force:
        raise ValueError(f"{target.relative_to(ROOT)} уже есть; добавьте --force для замены")
    sims = validate(read_source(source), env)
    write_private_csv(target, sims)
    print(f"Импортировано SIM: {len(sims)} -> {target.relative_to(ROOT)} (PIN/PUK не переносятся)")


def command_plan(env, sims):
    print(f"PLMN {env['MCC']}/{env['MNC']}, IMS домен {env['IMS_DOMAIN']}, SIM: {len(sims)}")
    for sim in sims:
        identity = ims_identity(sim, env)
        iccid = ("…" + sim["ICCID"][-6:]) if sim["ICCID"] else "-"
        print(
            f"  IMSI {sim['IMSI']}  ICCID {iccid}  MSISDN {sim['MSISDN']}  "
            f"IMPI {identity['impi']}  IMPU {identity['impu']}"
        )
    print("Ключи проверены по формату и в вывод не попадают.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    imported = sub.add_parser("import", help="Импорт таблицы поставщика SIM")
    imported.add_argument("source", type=Path)
    imported.add_argument("--force", action="store_true", help="Заменить существующий файл")
    sub.add_parser("plan", help="Проверка без обращения к базам")
    for name in ("apply", "status"):
        sub.add_parser(name).add_argument(
            "--ims-only", action="store_true", help="Только PyHSS (ядро OAI у партнёров)"
        )
    retired = sub.add_parser("retire", help="Удалить устаревших абонентов из PyHSS")
    retired.add_argument("--imsi", action="append", default=[])
    retired.add_argument(
        "--foreign-plmn", action="store_true", help="Все IMSI PyHSS вне PLMN lab.env"
    )
    retired.add_argument("--apply", action="store_true", help="Без флага только показать план")
    exported = sub.add_parser("oai-sql", help="Приватный SQL для UDR партнёров")
    exported.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    env = environment()

    if args.command == "import":
        return command_import(env, args.source, args.force)
    if args.command == "retire":
        imsis = list(args.imsi)
        if args.foreign_plmn:
            imsis += foreign_plmn_imsis(env)
            if not imsis:
                print("PyHSS: абонентов вне PLMN lab.env нет")
                return 0
        if not imsis or any(not imsi.isdigit() for imsi in imsis):
            raise ValueError("Укажите --imsi (только цифры) или --foreign-plmn")
        return retire_hss(env, imsis, args.apply)
    sims = load(env)
    if args.command == "plan":
        return command_plan(env, sims)
    if args.command == "apply":
        if not args.ims_only:
            provision_oai(env, sims)
        return provision_hss(env, sims)
    if args.command == "status":
        report = status(env, sims, args.ims_only)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        complete = all(len(report[k]) == len(sims) for k in ("pyhss", "oai_udr") if k in report)
        return 0 if complete else 1

    output = args.output if args.output.is_absolute() else ROOT / args.output
    if ROOT / "local" not in output.resolve().parents:
        raise ValueError("SQL с ключами сохраняется только внутри local/")
    statements = ["START TRANSACTION;", *oai_statements(env, sims), "COMMIT;"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(statements) + "\n", encoding="utf-8", newline="\n")
    try:
        output.chmod(0o600)
    except OSError:
        pass  # Windows: доступ ограничивает профиль пользователя.
    print(
        f"SQL для {len(sims)} SIM записан в {output.relative_to(ROOT)}; передавайте по защищённому каналу"
    )


if __name__ == "__main__":
    from script_console import configure_output

    configure_output()
    try:
        raise SystemExit(main() or 0)
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
