"""Панель стенда: захват SIP, диалоги, скрытие секретов, белый список действий, метрики."""

import socket
import struct
import unittest

import sipcap
from lab_panel import calls, jobs, metrics, redact

REGISTER = (
    "REGISTER sip:ims.example SIP/2.0\r\n"
    "Call-ID: abc@ue\r\n"
    "From: <sip:2601@ims.example>;tag=1\r\n"
    "To: <sip:2601@ims.example>\r\n"
    "CSeq: 1 REGISTER\r\n"
    'Authorization: Digest username="u", nonce="c2VjcmV0", response="d41d8cd98f00b204"\r\n'
    "Security-Client: ipsec-3gpp; ck=00112233; ik=44556677\r\n\r\n"
)


def packet(payload: bytes, ident: int = 7, fragment: int = 0, protocol: int = 17) -> bytes:
    udp = struct.pack("!HHHH", 5060, 5070, 8 + len(payload), 0) + payload
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(udp),
        ident,
        fragment,
        64,
        protocol,
        0,
        socket.inet_aton("10.0.0.1"),
        socket.inet_aton("10.0.0.2"),
    )
    return header + udp


def message(text: str, t: float, seq: int) -> dict:
    return {"text": text, "t": t, "seq": seq, "src": "10.0.0.1:5060", "dst": "10.0.0.2:5060"}


class SipCaptureTest(unittest.TestCase):
    def test_udp_sip_is_parsed(self):
        parsed = sipcap.parse_packet(packet(REGISTER.encode()))
        self.assertEqual(parsed["src"], "10.0.0.1:5060")
        self.assertEqual(parsed["dst"], "10.0.0.2:5070")
        self.assertEqual(parsed["call_id"], "abc@ue")

    def test_non_sip_fragments_and_tcp_are_ignored(self):
        self.assertIsNone(sipcap.parse_packet(packet(b"\x80\x00 rtp")))
        self.assertIsNone(sipcap.parse_packet(packet(REGISTER.encode(), fragment=0x2000)))
        self.assertIsNone(sipcap.parse_packet(packet(REGISTER.encode(), protocol=6)))

    def test_same_packet_on_two_interfaces_is_kept_once(self):
        dedup = sipcap.Deduplicator()
        parsed = sipcap.parse_packet(packet(REGISTER.encode()))
        self.assertTrue(dedup.fresh(parsed, 100.0))
        self.assertFalse(dedup.fresh(dict(parsed), 100.1))
        self.assertTrue(dedup.fresh(dict(parsed), 103.0))
        retransmission = sipcap.parse_packet(packet(REGISTER.encode(), ident=8))
        self.assertTrue(dedup.fresh(retransmission, 100.2))

    def test_store_returns_messages_after_cursor(self):
        store = sipcap.Store(2)
        for n in range(3):
            store.add({"n": n})
        self.assertEqual([m["n"] for m in store.since(0)], [1, 2])
        self.assertEqual([m["n"] for m in store.since(2)], [2])


class DialogTest(unittest.TestCase):
    def test_register_final_answer_is_last_one(self):
        items = [
            message(REGISTER, 1.0, 1),
            message("SIP/2.0 401 Unauthorized\r\nCSeq: 1 REGISTER\r\n\r\n", 1.1, 2),
            message(REGISTER.replace("CSeq: 1", "CSeq: 2"), 1.2, 3),
            message("SIP/2.0 200 OK\r\nCSeq: 2 REGISTER\r\n\r\n", 1.3, 4),
        ]
        row = calls.summarize("abc@ue", items)
        self.assertEqual((row["method"], row["from"], row["final"]), ("REGISTER", "2601", 200))

    def test_compact_headers(self):
        described = calls.describe(
            message("INVITE tel:1003 SIP/2.0\r\nf: <sip:2600@x>\r\nt: <tel:1003>\r\n", 0, 1)
        )
        self.assertEqual(
            (described["method"], described["from"], described["to"]), ("INVITE", "2600", "1003")
        )


class RedactionTest(unittest.TestCase):
    def test_sip_secrets_are_masked(self):
        text = redact.sip_text(REGISTER + "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:QUJDREVG\r\n")
        for secret in ("c2VjcmV0", "d41d8cd98f00b204", "00112233", "44556677", "QUJDREVG"):
            self.assertNotIn(secret, text)
        self.assertIn('username="u"', text)

    def test_log_lines_with_keys_are_hidden(self):
        self.assertEqual(redact.log_line("opc=0011 ki=22"), redact.HIDDEN_LINE)
        self.assertEqual(redact.log_line("REGISTER 200 OK"), "REGISTER 200 OK")
        self.assertEqual(redact.log_line("\x1b[0;35;49m WARNING"), " WARNING")


class ActionTest(unittest.TestCase):
    def test_only_whitelisted_actions(self):
        self.assertEqual(jobs.resolve("stand-up", set())[0], ["scripts/stand.sh", "up"])
        self.assertIsNone(jobs.resolve("rm -rf /", set()))
        self.assertIsNone(jobs.resolve("verify:../../evil", set()))
        self.assertIsNone(jobs.resolve("restart:lab-pcscf", set()))
        self.assertEqual(jobs.resolve("restart:lab-pcscf", {"lab-pcscf"})[0][-1], "lab-pcscf")
        self.assertIsNone(jobs.resolve("restart:partner-db", {"partner-db"}))


class GuardTest(unittest.TestCase):
    def test_only_local_host_and_marked_same_origin_changes(self):
        from lab_panel.web import allowed

        self.assertTrue(allowed("GET", "localhost:9000", None, None))
        self.assertFalse(allowed("GET", "evil.example:8090", None, None))
        self.assertFalse(allowed("GET", "localhost.evil.example", None, None))
        self.assertFalse(allowed("POST", "localhost:8090", None, None))
        self.assertTrue(allowed("POST", "localhost:8090", "http://localhost:8090", "1"))
        self.assertFalse(allowed("POST", "localhost:8090", "http://evil.example", "1"))


class MetricsTest(unittest.TestCase):
    def test_docker_stats_line(self):
        item = {"Name": "lab-ai-worker", "CPUPerc": "12.5%", "MemUsage": "1.5GiB / 7.6GiB"}
        self.assertEqual(metrics.parse_stats(item), ("lab-ai-worker", 12.5, 1536.0))

    def test_ai_event_fields(self):
        line = "AI reply_delivered model=q prompt_chars=3 llm_ms=812.500 calls=['a']"
        self.assertEqual(metrics.parse_event(line), [("ai:reply_delivered:llm_ms", 812.5)])
        self.assertEqual(metrics.parse_event("unrelated 5 ms"), [])

    def test_sip_counters(self):
        store = metrics.Metrics()
        store.on_sip([{"text": "INVITE sip:x SIP/2.0\r\n"}, {"text": "SIP/2.0 503 Busy\r\n"}])
        store.on_sip([{"text": "SIP/2.0 401 Unauthorized\r\n"}])
        self.assertEqual((store.sip["invite"], store.sip["fail"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
