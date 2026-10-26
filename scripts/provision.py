"""Заводит в PyHSS абонентов из lab.env: телефоны UE1/UE2 и тестовые SIPUE1/SIPUE2."""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB_ENV = ROOT / "app/config/lab.env"
PROFILES = ("UE1", "UE2", "SIPUE1", "SIPUE2")
KEY_FIELDS = ("ki", "opc", "amf")

# Выполняется внутри lab-pyhss: REST PyHSS не отдаёт ki/opc, поэтому для сверки
# ключей существующей записи читаем одну строку AuC напрямую из её MySQL.
AUC_QUERY = """
import json, sys, MySQLdb, MySQLdb.cursors, yaml
db = yaml.safe_load(open("/pyhss/config.yaml"))["database"]
connection = MySQLdb.connect(host=db["server"], user=db["username"], passwd=db["password"],
    db=db["database"], connect_timeout=5, cursorclass=MySQLdb.cursors.DictCursor)
cursor = connection.cursor()
cursor.execute("SELECT auc_id, ki, opc, amf FROM auc WHERE imsi = %s", (sys.argv[1],))
print(json.dumps(cursor.fetchall(), default=str))
"""


def read_env(path=LAB_ENV):
    """Читает KEY=VALUE так же, как Compose: без подстановок, кавычки снимаются."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


def subscribers(settings):
    """Проверяет ключи до любого обращения к HSS: ошибка не оставит половину записей."""
    result = []
    for prefix in PROFILES:
        entry = {
            "name": prefix,
            "imsi": settings[f"{prefix}_IMSI"],
            "msisdn": settings[f"{prefix}_MSISDN"],
            "ki": settings[f"{prefix}_IMS_K"],
            "opc": settings[f"{prefix}_IMS_OPC"],
            "amf": settings[f"{prefix}_IMS_AMF"],
        }
        if not entry["imsi"].isdigit() or not entry["msisdn"].isdigit():
            raise ValueError(f"{prefix}_IMSI и {prefix}_MSISDN должны состоять из цифр")
        for field, length in zip(KEY_FIELDS, (32, 32, 4), strict=True):
            if not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", entry[field]):
                raise ValueError(f"{prefix}: {field} должен содержать {length} hex-символов")
        result.append(entry)
    if len({entry["imsi"] for entry in result}) != len(result):
        raise ValueError("IMSI телефонов и тестовых клиентов должны различаться")
    return result


class PyHSS:
    def __init__(self, settings):
        self.base = f"http://{settings['PYHSS_API_BIND']}:{settings['PYHSS_API_PORT']}"

    def call(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base + path, data, {"Content-Type": "application/json"}, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            # Тело ответа не выводим: в нём могут быть ключи абонента.
            raise RuntimeError(f"PyHSS {method} {path.split('?')[0]}: HTTP {error.code}") from None

    def find(self, kind, imsi, id_field):
        rows = self.call("GET", f"/{kind}/list?page=0&page_size=200")
        return next((row[id_field] for row in rows if row.get("imsi") == imsi), None)


def stored_keys(imsi):
    result = subprocess.run(
        ["docker", "exec", "lab-pyhss", "python3", "-c", AUC_QUERY, imsi],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Не удалось прочитать ключи AuC из базы PyHSS")
    rows = json.loads(result.stdout)
    # Две строки AuC на один IMSI — испорченная база: сверять с произвольной нельзя.
    if len(rows) != 1:
        raise RuntimeError(f"В базе PyHSS {len(rows)} записей AuC для IMSI {imsi}, ожидалась одна")
    return rows[0]


def ensure_auc(hss, entry, replace_keys):
    keys = {field: entry[field] for field in KEY_FIELDS}
    record = hss.call("GET", f"/auc/imsi/{entry['imsi']}")
    if record is None:
        hss.call("PUT", "/auc/", {**keys, "sqn": 96, "imsi": entry["imsi"]})
        print(f"{entry['name']}: создан AuC для IMSI {entry['imsi']}")
        return hss.call("GET", f"/auc/imsi/{entry['imsi']}")["auc_id"]

    # SQN существующей записи растёт при каждой аутентификации; перезапись
    # ключей без явного запроса сломала бы уже зарегистрированный телефон.
    current = stored_keys(entry["imsi"]) if record.get("ki") is None else record
    if str(current.get("auc_id", record["auc_id"])) != str(record["auc_id"]):
        raise RuntimeError(f"{entry['name']}: REST и база PyHSS указывают на разные AuC")
    if all(str(current.get(f, "")).lower() == keys[f].lower() for f in KEY_FIELDS):
        print(f"{entry['name']}: AuC {record['auc_id']} сохранён без изменений")
    elif replace_keys:
        hss.call("PATCH", f"/auc/{record['auc_id']}", {**keys, "imsi": entry["imsi"]})
        print(f"{entry['name']}: ключи AuC {record['auc_id']} заменены значениями из lab.env")
    else:
        raise RuntimeError(
            f"{entry['name']}: ключи IMSI {entry['imsi']} в PyHSS отличаются от lab.env; "
            "исправьте lab.env или запустите provision.py --apply --replace-keys"
        )
    return record["auc_id"]


def ensure_apn(hss, dnn):
    """PyHSS требует внешний ключ APN у каждого абонента, хотя ядро OAI его не читает."""

    def find():
        rows = hss.call("GET", "/apn/list?page=0&page_size=200")
        return next((row["apn_id"] for row in rows if row.get("apn") == dnn), None)

    if find() is None:
        hss.call(
            "PUT",
            "/apn/",
            {
                "apn": dnn,
                "ip_version": 0,
                "apn_ambr_dl": 1000000,
                "apn_ambr_ul": 1000000,
                "qci": 9,
                "arp_priority": 8,
                "arp_preemption_capability": False,
                "arp_preemption_vulnerability": True,
            },
        )
    return find()


def upsert(hss, kind, id_field, entry, payload):
    existing = hss.find(kind, entry["imsi"], id_field)
    if existing is None:
        hss.call("PUT", f"/{kind}/", payload)
    else:
        hss.call("PATCH", f"/{kind}/{existing}", payload)


def provision(settings, replace_keys=False):
    entries = subscribers(settings)
    hss = PyHSS(settings)
    domain = settings["IMS_DOMAIN"]
    apn_id = ensure_apn(hss, settings["IMS_DNN"])

    for entry in entries:
        auc_id = ensure_auc(hss, entry, replace_keys)
        subscriber = {
            "imsi": entry["imsi"],
            "enabled": True,
            "auc_id": auc_id,
            "default_apn": apn_id,
            "apn_list": str(apn_id),
            "msisdn": entry["msisdn"],
            "ue_ambr_dl": 1000000,
            "ue_ambr_ul": 1000000,
            "nam": 2,
            "roaming_enabled": False,
            "subscribed_rau_tau_timer": 600,
        }
        upsert(hss, "subscriber", "subscriber_id", entry, subscriber)

        # default_ifc.xml отправляет исходящие INVITE на SIP AS (ISC); от него
        # зависит, попадёт ли вызов в AI. Остальные поля привязывают S-CSCF.
        ims = {
            "imsi": entry["imsi"],
            "msisdn": entry["msisdn"],
            "ifc_path": "default_ifc.xml",
            "sh_template_path": "default_sh_user_data.xml",
            "scscf": f"sip:scscf.{domain}:{settings['SCSCF_SIP_PORT']}",
            "scscf_realm": domain,
            "scscf_peer": f"scscf.{domain}",
            "pcscf_realm": domain,
            "pcscf_peer": f"pcscf.{domain}",
        }
        upsert(hss, "ims_subscriber", "ims_subscriber_id", entry, ims)
        print(f"{entry['name']}: IMPU sip:{entry['imsi']}@{domain}, MSISDN {entry['msisdn']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Записать абонентов в PyHSS")
    parser.add_argument(
        "--replace-keys", action="store_true", help="Заменить расходящиеся ключи AuC"
    )
    args = parser.parse_args()
    settings = read_env()
    if not args.apply:
        for entry in subscribers(settings):
            print(f"{entry['name']}: IMSI {entry['imsi']}, MSISDN {entry['msisdn']} (dry-run)")
        return
    provision(settings, args.replace_keys)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
