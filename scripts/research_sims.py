"""Исследовательские SIM: импорт таблицы поставщика, проверка и состояние в базах.

  python3 scripts/research_sims.py import <таблица.xlsx|csv>  # поля в local/secrets
  python3 scripts/research_sims.py plan     # проверка; IMSI/номера/IMPI без ключей
  python3 scripts/research_sims.py status   # есть ли SIM в UDR ядра и в PyHSS

Заводят карты обычные шаги стенда: `scripts/core-setup.sh apply` — UDR ядра
(core_subscribers.py), `scripts/start.py` — PyHSS (provision.py). PIN/PUK из
таблицы не переносятся; Ki/OPc не печатаются.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from provision import PyHSS, read_env, subscriber_profile
from research_sim_inventory import ims_identity, read_csv, read_source, validate, write_private_csv

ROOT = Path(__file__).resolve().parents[1]


def sim_file(settings) -> Path:
    path = Path(settings["RESEARCH_SIM_FILE"])
    path = path if path.is_absolute() else ROOT / path
    # Файл с Ki/OPc допускается только в игнорируемом каталоге local/.
    if ROOT / "local" not in path.resolve().parents:
        raise ValueError("RESEARCH_SIM_FILE должен находиться внутри local/ (игнорируется Git)")
    return path


def load_sims(settings, required=True) -> list[dict[str, str]]:
    path = sim_file(settings)
    if not path.exists():
        if required:
            raise ValueError(f"Нет файла SIM {path.relative_to(ROOT)}; сначала выполните import")
        return []
    return validate(read_csv(path), settings)


def hss_entries(settings) -> list[dict]:
    """Записи для provision.py: у всех SIM общие услуги и язык RESEARCH_SIM_*."""
    services, language = subscriber_profile(settings, "RESEARCH_SIM")
    return [
        {
            "name": f"SIM{sim['MSISDN']}",
            "imsi": sim["IMSI"],
            "msisdn": sim["MSISDN"],
            "ki": sim["KI"],
            "opc": sim["OPC"],
            "amf": sim["AMF"],
            "services": services,
            "language": language,
        }
        for sim in load_sims(settings, required=False)
    ]


def foreign_plmn_imsis(hss, settings) -> list[str]:
    """IMSI в PyHSS вне PLMN lab.env: после смены MCC/MNC это прежние абоненты стенда.

    PyHSS заполняют только скрипты стенда. Старые записи держат номера 1001/1002…,
    а IMPI и домен у них от прежнего PLMN — работать они уже не могут.
    """
    plmn = settings["MCC"] + settings["MNC"]
    found = set()
    for kind in ("ims_subscriber", "subscriber", "auc"):
        rows = hss.call("GET", f"/{kind}/list?page=0&page_size=1000") or []
        found.update(str(row.get("imsi") or "") for row in rows)
    return sorted(imsi for imsi in found if imsi and not imsi.startswith(plmn))


def retire_foreign(hss, settings) -> None:
    for imsi in foreign_plmn_imsis(hss, settings):
        auc = hss.call("GET", f"/auc/imsi/{imsi}")
        # Порядок важен: IMS-запись и subscriber ссылаются на AuC.
        targets = [
            ("ims_subscriber", hss.find("ims_subscriber", imsi, "ims_subscriber_id")),
            ("subscriber", hss.find("subscriber", imsi, "subscriber_id")),
            ("auc", None if auc is None else auc["auc_id"]),
        ]
        for kind, key in targets:
            if key is not None:
                hss.call("DELETE", f"/{kind}/{key}")
        print(f"PyHSS: удалён абонент прежнего PLMN, IMSI {imsi}")


def command_import(settings, source: Path, force: bool) -> int:
    target = sim_file(settings)
    if target.exists() and not force:
        raise ValueError(f"{target.relative_to(ROOT)} уже есть; для замены добавьте --force")
    rows = validate(read_source(source), settings)
    write_private_csv(target, rows)
    print(f"Импортировано SIM: {len(rows)} -> {target.relative_to(ROOT)} (PIN/PUK не переносятся)")
    return 0


def command_plan(settings) -> int:
    sims = load_sims(settings)
    print(
        f"PLMN {settings['MCC']}/{settings['MNC']}, IMS домен {settings['IMS_DOMAIN']}, "
        f"SIM: {len(sims)}"
    )
    for sim in sims:
        identity = ims_identity(sim, settings)
        print(
            f"  IMSI {sim['IMSI']}  ICCID …{sim['ICCID'][-6:]}  MSISDN {sim['MSISDN']}  "
            f"IMPI {identity['impi']}"
        )
    print("Ключи проверены по формату и в вывод не попадают.")
    return 0


def command_status(settings) -> int:
    from core_subscribers import Udr, present

    imsis = [sim["IMSI"] for sim in load_sims(settings)]
    listed = PyHSS(settings).call("GET", "/ims_subscriber/list?page=0&page_size=1000") or []
    in_hss = {row.get("imsi") for row in listed}
    report = {
        "sims": len(imsis),
        "pyhss": sorted(imsi for imsi in imsis if imsi in in_hss),
        "core_udr": sorted(present(Udr(settings), settings, imsis)),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if len(report["pyhss"]) == len(report["core_udr"]) == len(imsis) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    imported = sub.add_parser("import", help="Импорт таблицы поставщика SIM")
    imported.add_argument("source", type=Path)
    imported.add_argument("--force", action="store_true", help="Заменить существующий файл")
    sub.add_parser("plan", help="Проверка без обращения к базам")
    sub.add_parser("status", help="Только чтение: SIM в UDR ядра и в PyHSS")
    args = parser.parse_args(argv)
    settings = read_env()

    if args.command == "import":
        return command_import(settings, args.source, args.force)
    if args.command == "plan":
        return command_plan(settings)
    return command_status(settings)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
