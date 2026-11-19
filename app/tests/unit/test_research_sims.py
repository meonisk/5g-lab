"""Исследовательские SIM: разбор таблицы, проверки и provisioning без контейнеров."""

import importlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
INVENTORY = importlib.import_module("research_sim_inventory")
SIMS = importlib.import_module("research_sims")
INIT = importlib.import_module("initialize_local")

HEADER = ["IMSI", "ICCID", "ACC", "PIN1", "PUK1", "PIN2", "PUK2", "Ki", "OPC"]


def iccid(body):
    """Синтетический ICCID с правильной контрольной цифрой Луна."""
    for digit in "0123456789":
        if INVENTORY.luhn_valid(body + digit):
            return body + digit
    raise AssertionError


def synthetic_rows(env, count=3):
    plmn = env["MCC"] + env["MNC"]
    return [
        [
            plmn + f"{9990 + n:0{15 - len(plmn)}d}",
            iccid(f"899999000000000{n:03d}"),
            "0001",
            "1234",
            "12345678",
            "4321",
            "87654321",
            f"{n + 1:x}" * 32,
            f"{n + 10:x}"[-1] * 32,
        ]
        for n in range(count)
    ]


def write_xlsx(path, table):
    """Минимальный XLSX: общие строки, как у таблицы поставщика."""
    strings = sorted({cell for row in table for cell in row})
    index = {value: i for i, value in enumerate(strings)}
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rows = []
    for r, row in enumerate(table, start=1):
        cells = "".join(
            f'<c r="{chr(65 + c)}{r}" t="s"><v>{index[value]}</v></c>'
            for c, value in enumerate(row)
        )
        rows.append(f'<row r="{r}">{cells}</row>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
            '<sheet name="Sheet2" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{main}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{main}"><sheetData>{"".join(rows)}</sheetData></worksheet>',
        )


class Inventory(unittest.TestCase):
    def setUp(self):
        self.env = INIT.read_values(ROOT / "app/config/lab.env")
        self.table = [HEADER, *synthetic_rows(self.env)]

    def test_xlsx_import_drops_pin_puk_and_assigns_stable_msisdn(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sims.xlsx"
            write_xlsx(source, self.table)
            rows = INVENTORY.validate(INVENTORY.read_xlsx(source), self.env)
        self.assertEqual(len(rows), 3)
        self.assertEqual(set(rows[0]), set(INVENTORY.FIELDS))
        prefix = self.env["RESEARCH_SIM_MSISDN_PREFIX"]
        digits = int(self.env["RESEARCH_SIM_MSISDN_SUFFIX_DIGITS"])
        self.assertEqual(rows[1]["MSISDN"], prefix + rows[1]["IMSI"][-digits:])
        self.assertEqual(rows[0]["AMF"], "8000")
        identity = INVENTORY.ims_identity(rows[0], self.env)
        self.assertEqual(identity["impi"], f"{rows[0]['IMSI']}@{self.env['IMS_DOMAIN']}")

    def test_rejects_foreign_plmn_bad_iccid_reserved_number_and_duplicates(self):
        rows = INVENTORY._rows_from_table(self.table)
        cases = (
            ({"IMSI": "001019999999999"}, "PLMN"),
            ({"ICCID": rows[0]["ICCID"][:-1] + str((int(rows[0]["ICCID"][-1]) + 1) % 10)}, "ICCID"),
            ({"MSISDN": self.env["VOICE_TRANSLATOR_MSISDN"]}, "занят"),
            ({"KI": "Z" * 32}, "KI"),
            ({"OPC": rows[0]["KI"]}, "совпадают"),
            ({"IMSI": self.env["UE1_IMSI"]}, "UE1_IMSI"),
        )
        for change, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                INVENTORY.validate([{**rows[0], **change}], self.env)
        with self.assertRaisesRegex(ValueError, "повтор KI <скрыто>"):
            INVENTORY.validate([rows[0], {**rows[1], "KI": rows[0]["KI"]}], self.env)

    def test_errors_never_contain_key_material(self):
        rows = INVENTORY._rows_from_table(self.table)
        bad = {**rows[0], "IMSI": "123"}
        with self.assertRaises(ValueError) as caught:
            INVENTORY.validate([bad], self.env)
        self.assertNotIn(rows[0]["KI"], str(caught.exception))


class Provisioning(unittest.TestCase):
    def setUp(self):
        self.env = INIT.read_values(ROOT / "app/config/lab.env")
        self.sims = INVENTORY.validate(
            INVENTORY._rows_from_table([HEADER, *synthetic_rows(self.env, 2)]), self.env
        )

    def test_private_file_must_stay_under_local(self):
        with self.assertRaisesRegex(ValueError, "local/"):
            SIMS.sim_file({**self.env, "RESEARCH_SIM_FILE": "app/config/sims.csv"})
        self.assertTrue(SIMS.sim_file(self.env).is_relative_to(ROOT / "local"))

    def test_import_refuses_overwrite_without_force(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(SIMS, "ROOT", Path(directory)),
        ):
            source = Path(directory) / "sims.xlsx"
            write_xlsx(source, [HEADER, *synthetic_rows(self.env, 2)])
            SIMS.command_import(self.env, source, force=False)
            stored = INVENTORY.read_csv(SIMS.sim_file(self.env))
            self.assertNotIn("PIN1", stored[0])
            with self.assertRaisesRegex(ValueError, "--force"):
                SIMS.command_import(self.env, source, force=False)

    def test_oai_statements_preserve_existing_sqn(self):
        statements = SIMS.oai_statements(self.env, self.sims)
        self.assertEqual(len(statements), 3 * len(self.sims))
        self.assertTrue(all("ueid=ueid" in s for s in statements[::3]))

    def test_oai_rejects_changed_keys_in_udr(self):
        with patch("oai_subscribers.query", return_value="0" * 32 + "\t" + "1" * 32 + "\t8000"):
            with self.assertRaisesRegex(RuntimeError, "отличаются"):
                SIMS.provision_oai(self.env, self.sims)

    def test_hss_creates_auc_once_and_never_patches_existing_auc(self):
        calls = []
        existing = {self.sims[0]["IMSI"]: {"auc_id": 7, "imsi": self.sims[0]["IMSI"]}}

        def fake(_self, method, path, payload=None):
            calls.append((method, path))
            if path.startswith("/apn/list"):
                return [{"apn": self.env["IMS_DNN"], "apn_id": 3}]
            if path.startswith("/auc/imsi/"):
                imsi = path.rsplit("/", 1)[1]
                return existing.get(imsi) or ({"auc_id": 8} if ("PUT", "/auc/") in calls else None)
            if path.endswith("/list?page=0&page_size=1000"):
                return []
            return None

        with (
            patch.object(SIMS.Hss, "call", fake),
            patch("validate_ims_auc.validate_existing", return_value=True),
        ):
            SIMS.provision_hss(self.env, self.sims)
        self.assertEqual(calls.count(("PUT", "/auc/")), 1)
        self.assertFalse(any(m == "PATCH" and p.startswith("/auc") for m, p in calls))
        self.assertEqual(calls.count(("PUT", "/ims_subscriber/")), 2)

    def test_hss_stops_on_auc_key_mismatch(self):
        def fake(_self, method, path, payload=None):
            if path.startswith("/apn/list"):
                return [{"apn": self.env["IMS_DNN"], "apn_id": 3}]
            return {"auc_id": 7, "imsi": self.sims[0]["IMSI"]}

        with (
            patch.object(SIMS.Hss, "call", fake),
            patch("validate_ims_auc.validate_existing", return_value=False),
            self.assertRaisesRegex(RuntimeError, "отличаются"),
        ):
            SIMS.provision_hss(self.env, self.sims)

    def test_retire_protects_current_identities_and_deletes_in_fk_order(self):
        with self.assertRaisesRegex(ValueError, "Нельзя"):
            SIMS.retire_hss(self.env, [self.env["UE1_IMSI"]])
        calls = []
        rows = {"ims_subscriber": "ims_subscriber_id", "subscriber": "subscriber_id"}

        def fake(_self, method, path, payload=None):
            calls.append((method, path))
            if path.startswith("/auc/imsi/"):
                return {"auc_id": 5}
            kind = path.split("/")[1]
            return [{"imsi": "001010000000009", rows[kind]: 4}] if "list" in path else None

        with patch.object(SIMS.Hss, "call", fake):
            SIMS.retire_hss(self.env, ["001010000000009"])
            self.assertFalse(any(method == "DELETE" for method, _ in calls))
            SIMS.retire_hss(self.env, ["001010000000009"], apply=True)
        deleted = [path for method, path in calls if method == "DELETE"]
        self.assertEqual(deleted, ["/ims_subscriber/4", "/subscriber/4", "/auc/5"])


if __name__ == "__main__":
    unittest.main()
