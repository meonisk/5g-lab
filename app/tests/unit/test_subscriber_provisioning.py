"""Offline regression checks for repeatable subscriber provisioning."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import initialize_local, validate_ims_auc

ROOT = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")
BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


class LocalCredentials(unittest.TestCase):
    def test_new_stand_generates_four_distinct_aka_profiles(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            (root / "app/config").mkdir(parents=True)
            shutil.copyfile(ROOT / "app/config/lab.env", root / "app/config/lab.env")
            with (
                patch.object(initialize_local, "ROOT", root),
                patch.object(initialize_local, "SECRET_PATH", root / "local/secrets/ims.env"),
            ):
                initialize_local.main()
                values = initialize_local.read_values(initialize_local.SECRET_PATH)
                keys = [values[f"UE{ue}_{domain}_K"] for ue in (1, 2) for domain in ("5GS", "IMS")]
                self.assertEqual(len(set(keys)), 4)
                self.assertNotIn("SUBSCRIBER_K", values)
                initialize_local.main()
                self.assertEqual(initialize_local.read_values(initialize_local.SECRET_PATH), values)


class ExistingAucValidation(unittest.TestCase):
    def setUp(self):
        self.expected = {"ki": "A" * 32, "opc": "B" * 32, "amf": "8000"}
        self.api = {"auc_id": 11, "imsi": "001", "amf": "8000", "sqn": 501}
        self.rows = {
            "auc": [
                {"auc_id": 11, "imsi": "001", **self.expected},
                {"auc_id": 12, "imsi": "002", **self.expected},
            ],
            "subscriber": [],
            "ims_subscriber": [],
        }

    def test_api_omitted_keys_use_read_only_backend(self):
        with patch.object(validate_ims_auc, "read_pyhss_rows", return_value=self.rows) as read:
            self.assertTrue(
                validate_ims_auc.validate_existing(self.api, "001", "11", self.expected, "002")
            )
            read.assert_called_once_with(["001", "002"], require_both=False)

    def test_existing_first_auc_can_validate_before_peer_is_created(self):
        partial = {**self.rows, "auc": [self.rows["auc"][0]]}
        with patch.object(validate_ims_auc, "read_pyhss_rows", return_value=partial):
            self.assertTrue(
                validate_ims_auc.validate_existing(self.api, "001", "11", self.expected, "002")
            )

    def test_backend_mismatch_and_wrong_auc_id_fail(self):
        bad = {**self.rows, "auc": [{**self.rows["auc"][0], "ki": "C" * 32}, self.rows["auc"][1]]}
        with patch.object(validate_ims_auc, "read_pyhss_rows", return_value=bad):
            self.assertFalse(
                validate_ims_auc.validate_existing(self.api, "001", "11", self.expected, "002")
            )
        with patch.object(validate_ims_auc, "read_pyhss_rows", return_value=self.rows):
            self.assertFalse(
                validate_ims_auc.validate_existing(self.api, "001", "99", self.expected, "002")
            )


@unittest.skipUnless(NODE, "Node.js is unavailable")
class MongoProvisioning(unittest.TestCase):
    def test_existing_subscribers_keep_identity_and_runtime_state(self):
        script = ROOT / "scripts/subscribers.js"
        harness = r"""
const fs = require('fs');
const vm = require('vm');
const records = new Map([
  ['001', { imsi: '001', security: { k: 'new-key', opc: 'opc', amf: '8000' }, sqn: 123, marker: 'keep' }]
]);
const collection = {
  findOne(filter) { return records.get(filter.imsi); },
  updateOne(filter, update, options) {
    if (!options.upsert || !update.$setOnInsert) throw Error('unsafe update');
    if (!records.has(filter.imsi)) records.set(filter.imsi, update.$setOnInsert);
  },
  find() { return { toArray() { return [...records.values()]; } }; }
};
const db = { getSiblingDB() { return { subscribers: collection }; } };
const context = { db, print() {}, printjson() {}, process: { env: {
  SUBSCRIBER_K: 'new-key', SUBSCRIBER_OPC: 'opc', SUBSCRIBER_AMF: '8000', UE1_IMSI: '001', UE2_IMSI: '002'
} } };
const source = fs.readFileSync(process.argv[1], 'utf8');
vm.runInNewContext(source, { ...context });
vm.runInNewContext(source, { ...context });
const snapshot = [...records.values()].map((value) => JSON.parse(JSON.stringify(value)));
records.get('001').security.k = 'mismatch';
let rejected = false;
try { vm.runInNewContext(source, { ...context }); } catch (error) {
  rejected = error.message.includes('explicit migration required');
}
console.log(JSON.stringify({ snapshot, rejected }));
"""
        result = subprocess.run(
            [NODE, "-e", harness, str(script)],
            capture_output=True,
            text=True,
            check=True,
        )
        outcome = json.loads(result.stdout)
        records = {row["imsi"]: row for row in outcome["snapshot"]}
        self.assertEqual(len(records), 2)
        self.assertEqual(records["001"]["security"]["k"], "new-key")
        self.assertEqual(records["001"]["sqn"], 123)
        self.assertEqual(records["001"]["marker"], "keep")
        self.assertEqual(records["002"]["security"]["k"], "new-key")
        self.assertTrue(outcome["rejected"])


@unittest.skipUnless(BASH.exists(), "Git Bash is unavailable")
class PyhssProvisioning(unittest.TestCase):
    def test_existing_auc_is_not_patched_or_reseeded(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            script = root / "scripts/provision-ims-subscribers.sh"
            script.parent.mkdir()
            shutil.copyfile(ROOT / "scripts/provision-ims-subscribers.sh", script)
            shutil.copyfile(
                ROOT / "scripts/validate_ims_auc.py", root / "scripts/validate_ims_auc.py"
            )
            shutil.copyfile(
                ROOT / "scripts/subscriber_key_backend.py",
                root / "scripts/subscriber_key_backend.py",
            )
            (root / "scripts/load-lab-env.sh").write_text(
                "PYHSS_API_BIND=localhost\nPYHSS_API_PORT=8080\n"
                "SUBSCRIBER_K=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
                "SUBSCRIBER_OPC=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\nSUBSCRIBER_AMF=8000\n"
                "UE1_IMSI=001\nUE2_IMSI=002\nUE1_MSISDN=1001\nUE2_MSISDN=1002\n"
                "IMS_DOMAIN=example.test\nSCSCF_SIP_PORT=6060\nIMS_DNN=ims\n",
                encoding="utf-8",
            )
            fake_curl = root / "bin/curl"
            fake_curl.parent.mkdir()
            fake_curl.write_text(
                "#!/usr/bin/env bash\n"
                'printf \'%s\\n\' "$*" >> "$CURL_CALLS"\n'
                "outfile=''\nurl=''\n"
                "while (($#)); do\n"
                '  case "$1" in -o) outfile=$2; shift 2;; *) url=$1; shift;; esac\n'
                "done\n"
                'case "$url" in\n'
                '  */apn/list*) body=\'[{"apn":"ims","apn_id":3}]\';;\n'
                '  */auc/imsi/001) body=\'{"auc_id":11,"sqn":500,"ki":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","opc":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","amf":"8000"}\';;\n'
                '  */auc/imsi/002) body=\'{"auc_id":12,"sqn":600,"ki":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","opc":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","amf":"8000"}\';;\n'
                '  */subscriber/list*) body=\'[{"imsi":"001","subscriber_id":21},{"imsi":"002","subscriber_id":22}]\';;\n'
                '  */ims_subscriber/list*) body=\'[{"imsi":"001","ims_subscriber_id":31},{"imsi":"002","ims_subscriber_id":32}]\';;\n'
                "  *) body='{}';;\n"
                "esac\n"
                'if [[ -n ${MOCK_BAD_AUC:-} && "$url" == */auc/imsi/001 ]]; then body=\'{"auc_id":11,"ki":"CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC","opc":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","amf":"8000"}\'; fi\n'
                'if [[ -n $outfile ]]; then printf \'%s\' "$body" > "$outfile"; printf 200; else printf \'%s\' "$body"; fi\n',
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            with (root / "scripts/load-lab-env.sh").open("a", encoding="utf-8") as loader:
                loader.write(
                    'PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../bin" && pwd):$PATH"\n'
                )
            calls = root / "curl-calls"
            env = {
                **os.environ,
                "PATH": str(fake_curl.parent) + os.pathsep + os.environ["PATH"],
                "CURL_CALLS": str(calls),
            }
            result = subprocess.run(
                [str(BASH), str(script), "--apply"],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            requests = calls.read_text(encoding="utf-8")
            self.assertNotIn("/auc/11", requests)
            self.assertNotIn("/auc/12", requests)
            self.assertEqual(requests.count("/auc/imsi/"), 2)

            calls.write_text("", encoding="utf-8")
            mismatch = subprocess.run(
                [str(BASH), str(script), "--apply"],
                capture_output=True,
                text=True,
                env={**env, "MOCK_BAD_AUC": "1"},
                timeout=20,
                check=False,
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("explicit migration required", mismatch.stderr)
            self.assertNotIn("/subscriber/21", calls.read_text(encoding="utf-8"))
