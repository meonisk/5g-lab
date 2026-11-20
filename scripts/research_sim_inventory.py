"""Чтение и проверка приватного списка исследовательских SIM без вывода ключей.

Исходная таблица поставщика (XLSX/CSV) содержит IMSI, ICCID, PIN/PUK, Ki и OPc.
В рабочий файл `local/secrets/research-sims.csv` переносятся только поля,
нужные базам абонентов: IMSI, ICCID, Ki, OPc, AMF и MSISDN. PIN/PUK остаются
в исходной таблице у оператора и в базы не попадают.
"""

from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

FIELDS = ("IMSI", "ICCID", "KI", "OPC", "AMF", "MSISDN")
DEFAULT_AMF = "8000"
XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference).group(0)
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def _cell_text(cell, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iterfind(".//x:t", XLSX_NS))
    value = cell.findtext("x:v", default="", namespaces=XLSX_NS)
    if kind == "s":
        return shared[int(value)]
    # Числовая ячейка: IMSI/ICCID могли сохранить как число. Ведущие нули
    # такой формат не хранит; длину и PLMN потом проверяет validate().
    if kind in (None, "n") and re.fullmatch(r"\d+(\.0+)?", value):
        return value.split(".", 1)[0]
    return value


def read_xlsx(path: Path) -> list[dict[str, str]]:
    """Первый лист XLSX через stdlib: openpyxl не нужен на хосте оператора."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.iterfind("x:si", XLSX_NS):
                shared.append("".join(node.text or "" for node in item.iterfind(".//x:t", XLSX_NS)))

        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        first = workbook.find("x:sheets/x:sheet", XLSX_NS).get(REL_NS)
        relations = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(
            rel.get("Target")
            for rel in relations.iterfind("r:Relationship", PKG_REL_NS)
            if rel.get("Id") == first
        )
        sheet_path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        sheet = ElementTree.fromstring(archive.read(sheet_path))

    table = []
    for row in sheet.iterfind(".//x:sheetData/x:row", XLSX_NS):
        values: dict[int, str] = {}
        for cell in row.iterfind("x:c", XLSX_NS):
            values[_column_index(cell.get("r"))] = _cell_text(cell, shared).strip()
        if values:
            table.append([values.get(i, "") for i in range(max(values) + 1)])
    return _rows_from_table(table)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return _rows_from_table([row for row in csv.reader(handle) if any(row)])


def read_source(path: Path) -> list[dict[str, str]]:
    return read_xlsx(path) if path.suffix.lower() == ".xlsx" else read_csv(path)


def _rows_from_table(table: list[list[str]]) -> list[dict[str, str]]:
    if not table:
        raise ValueError("Таблица SIM пуста")
    header = [name.strip().upper() for name in table[0]]
    missing = {"IMSI", "KI", "OPC"} - set(header)
    if missing:
        raise ValueError("В таблице SIM нет столбцов: " + ", ".join(sorted(missing)))

    rows = []
    for raw in table[1:]:
        record = dict(zip(header, (value.strip() for value in raw), strict=False))
        if not record.get("IMSI"):
            continue
        rows.append({field: record.get(field, "") for field in FIELDS})
    return rows


def write_private_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows: доступ ограничивает профиль пользователя.


def luhn_valid(number: str) -> bool:
    total = 0
    for position, digit in enumerate(reversed(number)):
        value = int(digit) * (2 if position % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def assign_msisdn(imsi: str, env: dict[str, str]) -> str:
    """Стабильный номер из хвоста IMSI: не зависит от порядка строк в таблице."""
    digits = int(env["RESEARCH_SIM_MSISDN_SUFFIX_DIGITS"])
    return env["RESEARCH_SIM_MSISDN_PREFIX"] + imsi[-digits:]


def reserved_numbers(env: dict[str, str]) -> dict[str, str]:
    """Номера, уже занятые тестовыми UE и AI-услугами стенда."""
    return {value: key for key, value in env.items() if key.endswith("_MSISDN") and value}


def validate(rows: list[dict[str, str]], env: dict[str, str]) -> list[dict[str, str]]:
    """Нормализует записи и возвращает их; сообщения об ошибках без ключей."""
    if not rows:
        raise ValueError("В списке нет ни одной SIM")
    plmn = env["MCC"] + env["MNC"]
    reserved = reserved_numbers(env)
    # IMSI стенда из lab.env: эмулируемые UE1/UE2 и тестовые клиенты SIPUE1/SIPUE2.
    synthetic = {value for key, value in env.items() if key.endswith("_IMSI") and value}
    seen: dict[str, set[str]] = {"IMSI": set(), "ICCID": set(), "KI": set(), "MSISDN": set()}
    result = []

    for number, source in enumerate(rows, start=2):
        row = {field: source.get(field, "").strip() for field in FIELDS}
        where = f"строка {number}"
        row["KI"], row["OPC"] = row["KI"].upper(), row["OPC"].upper()
        row["AMF"] = (row["AMF"] or DEFAULT_AMF).upper()
        row["MSISDN"] = row["MSISDN"] or assign_msisdn(row["IMSI"], env)

        if not re.fullmatch(r"\d{15}", row["IMSI"]):
            raise ValueError(f"{where}: IMSI должен содержать 15 цифр")
        if not row["IMSI"].startswith(plmn):
            raise ValueError(
                f"{where}: IMSI {row['IMSI']} не из PLMN {env['MCC']}/{env['MNC']} в lab.env"
            )
        if row["IMSI"] in synthetic:
            raise ValueError(f"{where}: IMSI совпадает с *_IMSI абонентов стенда в lab.env")
        if row["ICCID"] and not (
            re.fullmatch(r"\d{18,20}", row["ICCID"]) and luhn_valid(row["ICCID"])
        ):
            raise ValueError(f"{where}: ICCID не проходит проверку длины или контрольной цифры")
        for field, length in (("KI", 32), ("OPC", 32), ("AMF", 4)):
            if not re.fullmatch(rf"[0-9A-F]{{{length}}}", row[field]):
                raise ValueError(f"{where}: {field} должен содержать {length} hex-символа(ов)")
        if row["KI"] == row["OPC"]:
            raise ValueError(f"{where}: Ki и OPc совпадают; проверьте столбцы таблицы")
        if not re.fullmatch(r"\d{3,15}", row["MSISDN"]):
            raise ValueError(f"{where}: MSISDN должен содержать от 3 до 15 цифр")
        if row["MSISDN"] in reserved:
            raise ValueError(
                f"{where}: MSISDN {row['MSISDN']} уже занят {reserved[row['MSISDN']]} в lab.env"
            )

        for field in seen:
            if row[field] and row[field] in seen[field]:
                # Значение Ki не выводим даже при дубликате.
                shown = "<скрыто>" if field == "KI" else row[field]
                raise ValueError(f"{where}: повтор {field} {shown}")
            seen[field].add(row[field])
        result.append(row)
    return result


def ims_identity(row: dict[str, str], env: dict[str, str]) -> dict[str, str]:
    """Идентификаторы, которые телефон без записанного ISIM выводит из IMSI."""
    domain = env["IMS_DOMAIN"]
    return {
        "impi": f"{row['IMSI']}@{domain}",
        "impu": f"sip:{row['MSISDN']}@{domain}",
        "tel": f"tel:{row['MSISDN']}",
    }
