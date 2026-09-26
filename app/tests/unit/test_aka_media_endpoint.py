"""Offline checks for the bounded AKA RTP endpoint."""

import io
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

from app.tests.integration import aka_media_endpoint as media


def packet(sequence, timestamp, ssrc, payload=b"\xff" * 160, pt=0):
    return struct.pack("!BBHII", 0x80, pt, sequence, timestamp, ssrc) + payload


class MediaEndpointTests(unittest.TestCase):
    def test_marker_is_deterministic_and_decodable(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        tmp_path = Path(folder.name)
        source = tmp_path / "source.wav"
        with wave.open(str(source), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(struct.pack("<800h", *([0] * 800)))
        first, second = tmp_path / "one.pcmu", tmp_path / "two.pcmu"
        media.make_marker(source, first)
        media.make_marker(source, second)
        assert first.read_bytes() == second.read_bytes()
        assert len(first.read_bytes()) % 160 == 0
        assert first.read_bytes()[:160] != b"\xff" * 160
        assert media.decode_mulaw(media.encode_mulaw(1000)) > 0

    def test_receiver_filters_and_accounts_for_gaps(self):
        raw, pcm = io.BytesIO(), io.BytesIO()
        with wave.open(pcm, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            receiver = media.Receiver("127.0.0.1", 9000, 111, wav, raw)
            receiver.receive(packet(1, 160, 42), ("127.0.0.1", 9001))
            receiver.receive(packet(1, 160, 42, pt=8), ("127.0.0.1", 9000))
            receiver.receive(packet(1, 160, 111), ("127.0.0.1", 9000))
            receiver.receive(packet(1, 160, 42), ("127.0.0.1", 9000))
            receiver.receive(packet(1, 160, 42), ("127.0.0.1", 9000))
            receiver.receive(packet(3, 480, 42), ("127.0.0.1", 9000))
            receiver.receive(packet(4, 800, 42), ("127.0.0.1", 9000))
            receiver.receive(packet(5, 960, 43), ("127.0.0.1", 9000))
        assert receiver.stats == {
            "accepted": 3,
            "wrong_source": 1,
            "wrong_pt": 1,
            "self_echo": 1,
            "wrong_ssrc": 1,
            "malformed": 0,
            "duplicates": 1,
            "out_of_order": 0,
            "sequence_gaps": 1,
            "timestamp_errors": 1,
        }
        assert len(raw.getvalue()) == 3 * (2 + 172)
        pcm.seek(0)
        with wave.open(pcm, "rb") as wav:
            assert wav.getnframes() == 480

    def test_udp_endpoint_file_contract(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        tmp_path = Path(folder.name)
        marker = tmp_path / "marker.pcmu"
        marker.write_bytes(b"\xff" * 160)
        ready, control, stop = (tmp_path / name for name in ("ready", "control.json", "stop"))
        prefix = tmp_path / "capture"
        outcome = {}

        def worker():
            outcome["result"] = media.run(
                "127.0.0.1", 0, 111, marker, control, ready, stop, prefix, 2
            )

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            until = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < until:
                time.sleep(0.01)
            bind_port = json.loads(ready.read_text())["bind_port"]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
                peer.bind(("127.0.0.1", 0))
                control.write_text(
                    json.dumps(
                        {
                            "remote_ip": "127.0.0.1",
                            "remote_port": peer.getsockname()[1],
                            "payload_type": 0,
                        }
                    )
                )
                for sequence in range(3):
                    time.sleep(0.04)
                    peer.sendto(packet(sequence, sequence * 160, 42), ("127.0.0.1", bind_port))
                stop.touch()
        finally:
            thread.join(timeout=3)
        assert not thread.is_alive()
        assert outcome["result"]["status"] == "CAPTURED"
        assert outcome["result"]["accepted"] == 3
        assert outcome["result"]["sent_packets"] > 0
        assert json.loads(prefix.with_suffix(".json").read_text())["accepted"] == 3
        with wave.open(str(prefix.with_suffix(".wav")), "rb") as wav:
            assert wav.getnframes() == 480

    def test_two_endpoints_exchange_distinct_ssrc(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        tmp_path = Path(folder.name)
        marker = tmp_path / "marker.pcmu"
        marker.write_bytes(b"\xff" * 160)
        runs = []
        for index in (1, 2):
            folder = tmp_path / str(index)
            folder.mkdir()
            runs.append(
                {
                    "folder": folder,
                    "ready": folder / "ready.json",
                    "control": folder / "control.json",
                    "stop": folder / "stop",
                    "output": folder / "capture",
                    "ssrc": 1000 + index,
                }
            )
        threads = []
        results = {}
        for index, item in enumerate(runs):

            def worker(i=index, entry=item):
                results[i] = media.run(
                    "127.0.0.1",
                    0,
                    entry["ssrc"],
                    marker,
                    entry["control"],
                    entry["ready"],
                    entry["stop"],
                    entry["output"],
                    2,
                )

            thread = threading.Thread(target=worker)
            thread.start()
            threads.append(thread)
        try:
            until = time.monotonic() + 2
            while not all(item["ready"].exists() for item in runs) and time.monotonic() < until:
                time.sleep(0.01)
            ports = [json.loads(item["ready"].read_text())["bind_port"] for item in runs]
            for index, item in enumerate(runs):
                item["control"].write_text(
                    json.dumps(
                        {
                            "remote_ip": "127.0.0.1",
                            "remote_port": ports[1 - index],
                            "payload_type": 0,
                        }
                    )
                )
            time.sleep(0.3)
            for item in runs:
                item["stop"].touch()
        finally:
            for thread in threads:
                thread.join(timeout=3)
        assert all(not thread.is_alive() for thread in threads)
        assert all(results[index]["status"] == "CAPTURED" for index in (0, 1))
        assert all(results[index]["accepted"] > 0 for index in (0, 1))
        assert results[0]["received_ssrc"] == runs[1]["ssrc"]
        assert results[1]["received_ssrc"] == runs[0]["ssrc"]
