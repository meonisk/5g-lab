"""Synthetic Cx PCAPs exercise strict reassembly and private metadata."""

import struct
import tempfile
import unittest
from pathlib import Path

from app.tests.integration.cx_metadata import (
    challenge_fingerprint,
    identity_pseudonym,
    summarize_pcap,
)


def avp(code, value):
    length = 8 + len(value)
    return (
        struct.pack("!I", code)
        + bytes([0])
        + length.to_bytes(3, "big")
        + value
        + b"\0" * (-length % 4)
    )


def diameter(command, request, hop, user, result=None, experimental=False, vendor=10415):
    body = avp(263, f"session-{hop}".encode())
    if request:
        body += avp(1, user.encode())
    elif experimental:
        body += avp(297, avp(266, struct.pack("!I", vendor)) + avp(298, struct.pack("!I", result)))
    else:
        body += avp(268, struct.pack("!I", result))
    if not request and command == 303:
        body += avp(612, avp(609, bytes([hop % 256]) * 32))
    length = 20 + len(body)
    return (
        bytes([1])
        + length.to_bytes(3, "big")
        + bytes([0x80 if request else 0])
        + command.to_bytes(3, "big")
        + struct.pack("!III", 16777216, hop, hop + 9)
        + body
    )


def frame(payload, sequence, reverse=False):
    source = b"\x0a\x00\x00\x01" if not reverse else b"\x0a\x00\x00\x02"
    dest = b"\x0a\x00\x00\x02" if not reverse else b"\x0a\x00\x00\x01"
    source_port, dest_port = (5060, 3868) if not reverse else (3868, 5060)
    tcp = struct.pack("!HHIIHHHH", source_port, dest_port, sequence, 0, 0x5010, 0, 0, 0) + payload
    ip = (
        bytes([0x45, 0])
        + struct.pack("!H", 20 + len(tcp))
        + bytes(5)
        + bytes([6])
        + bytes(2)
        + source
        + dest
    )
    return bytes(12) + b"\x08\x00" + ip + tcp


def pcap(frames):
    header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    return header + b"".join(
        struct.pack("<IIII", 1, 0, len(item), len(item)) + item for item in frames
    )


class CxMetadata(unittest.TestCase):
    def summarize(self, frames, **options):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "cx.pcap"
            path.write_bytes(pcap(frames))
            return summarize_pcap(path, b"test-only-pseudonym-key", **options)

    def complete_frames(
        self, result=2001, omit_last=False, experimental_uar=False, vendor=10415, skip=None
    ):
        requests = []
        answers = []
        for index, user in enumerate(("private-ue-one", "private-ue-two")):
            for number, command in enumerate((300, 303, 301)):
                if skip and (index, command) in skip:
                    continue
                hop = 100 + index * 10 + number
                requests.append(diameter(command, True, hop, user))
                if not omit_last or hop != 112:
                    answers.append(
                        diameter(
                            command,
                            False,
                            hop,
                            user,
                            2002 if experimental_uar and command == 300 else result,
                            experimental=experimental_uar and command == 300,
                            vendor=vendor,
                        )
                    )
        return [frame(b"".join(requests), 1000), frame(b"".join(answers), 2000, True)]

    def test_two_users_three_successful_commands_only_return_pseudonyms(self):
        result = self.summarize(self.complete_frames())
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(len(result["transactions"]), 6)
        self.assertEqual(len({row["user"] for row in result["transactions"]}), 2)
        self.assertNotIn("private-ue", repr(result))
        self.assertEqual({row["command"] for row in result["transactions"]}, {"UAR", "MAR", "SAR"})
        self.assertEqual(self.summarize(list(reversed(self.complete_frames())))["status"], "PASS")

    def test_missing_answer_is_incomplete_and_error_answer_fails(self):
        partial = self.summarize(self.complete_frames(omit_last=True))
        self.assertEqual(partial["status"], "INCOMPLETE")
        self.assertEqual(len(partial["transactions"]), 5)
        self.assertEqual(self.summarize(self.complete_frames(result=5005))["status"], "FAIL")

    def test_3gpp_subsequent_registration_is_uar_success_only(self):
        valid = self.summarize(self.complete_frames(experimental_uar=True))
        self.assertEqual(valid["status"], "PASS", valid)
        self.assertEqual(
            {row["result_namespace"] for row in valid["transactions"]}, {"base", "3gpp"}
        )
        wrong_vendor = self.summarize(self.complete_frames(experimental_uar=True, vendor=999))
        self.assertEqual(wrong_vendor["status"], "FAIL")

    def test_expected_negative_command_profile_and_challenge_binding(self):
        key = b"test-only-pseudonym-key"
        profile = {"private-ue-one": {"UAR", "MAR"}, "private-ue-two": {"UAR", "MAR", "SAR"}}
        frames = self.complete_frames(skip={(0, 301)})
        self.assertEqual(self.summarize(frames)["status"], "INCOMPLETE")
        result = self.summarize(frames, expected_commands=profile)
        self.assertEqual(result["status"], "PASS", result)
        one = identity_pseudonym("private-ue-one", key)
        mar = next(
            row for row in result["transactions"] if row["user"] == one and row["command"] == "MAR"
        )
        self.assertEqual(
            mar["challenge_fingerprints"], [challenge_fingerprint(bytes([101]) * 32, key)]
        )
        self.assertNotIn("private-ue", repr(result))
        self.assertEqual(
            self.summarize(frames, expected_users={"wrong", "private-ue-two"})["status"], "FAIL"
        )

    def test_tcp_gap_and_conflicting_overlap_are_incomplete(self):
        frames = self.complete_frames()
        payload = frames[0][54:]
        gap = [frame(payload[:30], 1000), frame(payload[30:], 1031), frames[1]]
        self.assertIn("TCP sequence gap", self.summarize(gap)["reason"])
        conflict = [frame(payload[:35], 1000), frame(b"X" + payload[31:], 1031), frames[1]]
        self.assertIn("Conflicting TCP overlap", self.summarize(conflict)["reason"])
