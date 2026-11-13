"""iFC по профилю абонента из lab.env: приоритеты, правило «*», DefaultHandling, DNS."""

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import provision  # noqa: E402


class FakeHss:
    def __init__(self):
        self.calls = []

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return None

    def find(self, kind, imsi, id_field):
        return None


def rules(xml):
    """(приоритет, хост AS, DefaultHandling, RequestURI) каждого iFC по порядку."""
    result = []
    for ifc in ET.fromstring(xml.encode("utf-8")).iter("InitialFilterCriteria"):
        server = ifc.findtext("ApplicationServer/ServerName")
        result.append(
            (
                int(ifc.findtext("Priority")),
                re.match(r"sip:([^:;]+)", server).group(1),
                ifc.findtext("ApplicationServer/DefaultHandling"),
                ifc.findtext("TriggerPoint/SPT/RequestURI"),
            )
        )
    return result


class IfcGeneration(unittest.TestCase):
    def setUp(self):
        self.settings = provision.read_env()
        self.domain = self.settings["IMS_DOMAIN"]

    def test_translate_record_chain_in_priority_order(self):
        found = rules(provision.ifc_xml(self.settings, ["translate", "record"]))
        domain = self.domain
        self.assertEqual(
            [(priority, host) for priority, host, _, _ in found],
            [
                (10, f"translate.as.{domain}"),
                (15, f"translate.as.{domain}"),
                (20, f"record.as.{domain}"),
                (30, f"as.{domain}"),
                (40, f"smsc.{domain}"),
            ],
        )

    def test_every_rule_continues_session_when_as_is_down(self):
        found = rules(provision.ifc_xml(self.settings, ["translate", "record"]))
        self.assertEqual({handling for _, _, handling, _ in found}, {"0"})

    def test_star_rule_matches_only_prefixed_request_uri(self):
        found = rules(provision.ifc_xml(self.settings, []))
        star = next(ruri for priority, _, _, ruri in found if priority == 15)
        self.assertRegex(f"sip:*1002@{self.domain}", star)
        self.assertRegex("tel:*1002", star)
        self.assertNotRegex(f"sip:1002@{self.domain}", star)

    def test_subscriber_without_services_keeps_star_and_numbers(self):
        found = rules(provision.ifc_xml(self.settings, []))
        self.assertEqual([priority for priority, *_ in found], [15, 30, 40])

    def test_numbers_rule_kept_for_originating_invite(self):
        xml = provision.ifc_xml(self.settings, [])
        server = f"sip:as.{self.domain}:{self.settings['SIP_AS_PORT']};transport=udp"
        self.assertIn(f"<ServerName>{server}</ServerName>", xml)
        numbers = next(
            ifc
            for ifc in ET.fromstring(xml.encode("utf-8")).iter("InitialFilterCriteria")
            if ifc.findtext("Priority") == "30"
        )
        self.assertEqual(numbers.findtext("TriggerPoint/SPT/Method"), "INVITE")
        self.assertEqual(numbers.findtext("TriggerPoint/SPT/SessionCase"), "0")

    def test_identities_stay_pyhss_templates(self):
        xml = provision.ifc_xml(self.settings, [])
        self.assertIn("<PrivateID>{{ iFC_vars['imsi'] }}", xml)
        self.assertIn("<Identity>tel:{{ iFC_vars['msisdn'] }}</Identity>", xml)


class SubscriberProfiles(unittest.TestCase):
    def test_repository_profiles(self):
        entries = {e["name"]: e for e in provision.subscribers(provision.read_env())}
        profile = {name: (e["services"], e["language"]) for name, e in entries.items()}
        self.assertEqual(
            profile,
            {
                "UE1": (["translate", "record"], "ru"),
                "UE2": ([], "en"),
                "SIPUE1": (["translate", "record"], "ru"),
                "SIPUE2": ([], "en"),
            },
        )

    def test_unknown_service_is_rejected_before_hss(self):
        settings = {**provision.read_env(), "SIPUE2_SERVICES": "translate,fax"}
        with self.assertRaisesRegex(ValueError, "SIPUE2_SERVICES: .*fax"):
            provision.subscribers(settings)

    def test_language_defaults_and_validation(self):
        settings = provision.read_env()
        settings.pop("SIPUE2_LANGUAGE")
        entries = {e["name"]: e for e in provision.subscribers(settings)}
        self.assertEqual(entries["SIPUE2"]["language"], settings["DEFAULT_LANGUAGE"])
        with self.assertRaisesRegex(ValueError, "UE1_LANGUAGE=de"):
            provision.subscribers({**provision.read_env(), "UE1_LANGUAGE": "de"})


class Provisioning(unittest.TestCase):
    def test_each_subscriber_gets_own_generated_ifc(self):
        hss = FakeHss()
        settings = provision.read_env()
        with (
            patch.object(provision, "PyHSS", return_value=hss),
            patch.object(provision, "ensure_apn", return_value=1),
            patch.object(provision, "ensure_auc", return_value=2),
            patch.object(
                provision, "install_ifc", side_effect=lambda name, xml: f"ifc-{name}.xml"
            ) as install,
        ):
            provision.provision(settings)
        ims = [payload for _, path, payload in hss.calls if path == "/ims_subscriber/"]
        self.assertEqual(
            [payload["ifc_path"] for payload in ims],
            ["ifc-UE1.xml", "ifc-UE2.xml", "ifc-SIPUE1.xml", "ifc-SIPUE2.xml"],
        )
        generated = {call.args[0]: call.args[1] for call in install.call_args_list}
        self.assertIn(f"record.as.{settings['IMS_DOMAIN']}", generated["SIPUE1"])
        self.assertNotIn("record.as.", generated["SIPUE2"])

    def test_install_writes_next_to_default_template(self):
        with patch.object(provision.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(provision.install_ifc("UE1", "<!-- услуги --><xml/>"), "ifc-UE1.xml")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["docker", "exec", "-i", "lab-pyhss"])
        self.assertEqual(command[-1], "/pyhss/ifc-UE1.xml")
        # Байты UTF-8 при любой кодировке ОС: cp1251 ломал SAR в PyHSS.
        self.assertEqual(run.call_args.kwargs["input"], "<!-- услуги --><xml/>".encode("utf-8"))
        self.assertNotIn("text", run.call_args.kwargs)

    def test_dns_names_point_to_sip_as(self):
        conf = (ROOT / "app/infrastructure/configs/dns/ims-dnsmasq.conf").read_text(
            encoding="utf-8"
        )
        for name in ("translate.as", "record.as"):
            self.assertIn(f"address=/{name}.__IMS_DOMAIN__/__SIP_AS_IP__", conf)


if __name__ == "__main__":
    unittest.main()
