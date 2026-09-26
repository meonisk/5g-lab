"""Bounded PCMU/8000 RTP sender and receiver for an AKA SIPp call."""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import socket
import struct
import time
import wave
from pathlib import Path

FRAME_SAMPLES = 160
FRAME_SECONDS = 0.02


def decode_mulaw(byte: int) -> int:
    value = (~byte) & 0xFF
    magnitude = ((value & 15) << 3) + 0x84
    magnitude <<= (value >> 4) & 7
    sample = magnitude - 0x84
    return -sample if value & 0x80 else sample


def encode_mulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), 32635) + 0x84
    exponent = max(0, magnitude.bit_length() - 8)
    exponent = min(exponent, 7)
    mantissa = (magnitude >> (exponent + 3)) & 15
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF


def make_marker(wav_path: Path, raw_path: Path) -> None:
    """Prefix a deterministic two-tone tag, then encode mono PCM16 WAV to PCMU."""
    with wave.open(str(wav_path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 8000):
            raise ValueError("Marker source must be mono PCM16 at 8000 Hz")
        pcm = source.readframes(source.getnframes())
    if len(pcm) < 320:
        raise ValueError("Marker source is too short")
    samples = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
    # The tag distinguishes this transmission from the untouched source WAV.
    tag = [
        int(6000 * math.sin(2 * math.pi * (1000 if n < 1600 else 500) * n / 8000))
        for n in range(3200)
    ]
    payload = bytes(encode_mulaw(value) for value in tag + list(samples))
    payload += bytes([0xFF]) * (-len(payload) % FRAME_SAMPLES)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(raw_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as target:
        target.write(payload)


def parse_rtp(packet: bytes) -> tuple[int, int, int, int, bytes]:
    if len(packet) < 12 or packet[0] >> 6 != 2:
        raise ValueError("Invalid RTP header")
    count = packet[0] & 15
    offset = 12 + count * 4
    if len(packet) < offset:
        raise ValueError("Truncated RTP CSRC list")
    if packet[0] & 0x10:
        if len(packet) < offset + 4:
            raise ValueError("Truncated RTP extension")
        words = struct.unpack_from("!H", packet, offset + 2)[0]
        offset += 4 + words * 4
    if len(packet) < offset:
        raise ValueError("Truncated RTP extension data")
    end = len(packet)
    if packet[0] & 0x20:
        padding = packet[-1]
        if not padding or end - padding < offset:
            raise ValueError("Invalid RTP padding")
        end -= padding
    pt = packet[1] & 0x7F
    sequence, timestamp, ssrc = struct.unpack_from("!HII", packet, 2)
    return pt, sequence, timestamp, ssrc, packet[offset:end]


class Receiver:
    def __init__(self, remote_ip: str, remote_port: int, local_ssrc: int, pcm_file, packet_file):
        self.remote = (remote_ip, remote_port)
        self.local_ssrc = local_ssrc
        self.pcm_file = pcm_file
        self.packet_file = packet_file
        self.ssrc = None
        self.sequence = None
        self.timestamp = None
        self.stats = {
            name: 0
            for name in (
                "accepted",
                "wrong_source",
                "wrong_pt",
                "self_echo",
                "wrong_ssrc",
                "malformed",
                "duplicates",
                "out_of_order",
                "sequence_gaps",
                "timestamp_errors",
            )
        }

    def receive(self, packet: bytes, source: tuple[str, int]) -> None:
        if source != self.remote:
            self.stats["wrong_source"] += 1
            return
        try:
            pt, sequence, timestamp, ssrc, payload = parse_rtp(packet)
        except ValueError:
            self.stats["malformed"] += 1
            return
        if pt != 0 or len(payload) != FRAME_SAMPLES:
            self.stats["wrong_pt"] += 1
            return
        if ssrc == self.local_ssrc:
            self.stats["self_echo"] += 1
            return
        if self.ssrc is not None and ssrc != self.ssrc:
            self.stats["wrong_ssrc"] += 1
            return
        if self.sequence is not None:
            step = (sequence - self.sequence) & 0xFFFF
            if step == 0:
                self.stats["duplicates"] += 1
                return
            if step >= 0x8000:
                self.stats["out_of_order"] += 1
                return
            self.stats["sequence_gaps"] += step - 1
            if (timestamp - self.timestamp) & 0xFFFFFFFF != FRAME_SAMPLES * step:
                self.stats["timestamp_errors"] += 1
        self.ssrc = ssrc
        self.sequence = sequence
        self.timestamp = timestamp
        self.packet_file.write(struct.pack("!H", len(packet)) + packet)
        self.pcm_file.writeframesraw(
            b"".join(struct.pack("<h", decode_mulaw(byte)) for byte in payload)
        )
        self.stats["accepted"] += 1


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        json.dump(value, target, sort_keys=True)
    os.replace(temporary, path)


def run(
    bind_ip: str,
    bind_port: int,
    local_ssrc: int,
    marker: Path,
    control: Path,
    ready: Path,
    stop: Path,
    output_prefix: Path,
    seconds: float,
) -> dict:
    if not 0 < seconds <= 3600:
        raise ValueError("Duration must be between zero and 3600 seconds")
    if not 0 <= local_ssrc <= 0xFFFFFFFF:
        raise ValueError("SSRC must be a 32-bit unsigned integer")
    payload = Path(marker).read_bytes()
    if len(payload) < FRAME_SAMPLES or len(payload) % FRAME_SAMPLES:
        raise ValueError("PCMU marker must contain complete 160-byte frames")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output_prefix.with_suffix(".rtpbin")
    wav_path = output_prefix.with_suffix(".wav")
    status_path = output_prefix.with_suffix(".json")
    for path in (raw_path, wav_path, status_path, ready):
        if path.exists():
            raise FileExistsError(path)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((bind_ip, bind_port))
        udp.setblocking(False)
        fd = os.open(ready, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump({"bind_ip": bind_ip, "bind_port": udp.getsockname()[1]}, target)
        deadline = time.monotonic() + seconds
        settings = None
        while time.monotonic() < deadline and not stop.exists():
            if control.exists():
                settings = json.loads(control.read_text(encoding="utf-8"))
                break
            time.sleep(0.05)
        if settings is None:
            result = {"status": "INCOMPLETE", "reason": "RTP control never arrived"}
            _atomic_json(status_path, result)
            return result
        remote = (str(settings["remote_ip"]), int(settings["remote_port"]))
        if not 1 <= remote[1] <= 65535 or settings.get("payload_type", 0) != 0:
            raise ValueError("Expected a PCMU negotiated RTP peer")
        packets = 0
        next_send = time.monotonic()
        wav_fd = os.open(wav_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with (
            raw_path.open("xb") as raw,
            os.fdopen(wav_fd, "wb") as wav_file,
            wave.open(wav_file, "wb") as wav,
        ):
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            receiver = Receiver(*remote, local_ssrc, wav, raw)
            while time.monotonic() < deadline and not stop.exists():
                now = time.monotonic()
                if now >= next_send:
                    frame = payload[(packets % (len(payload) // FRAME_SAMPLES)) * FRAME_SAMPLES :][
                        :FRAME_SAMPLES
                    ]
                    header = struct.pack(
                        "!BBHII",
                        0x80,
                        0,
                        packets & 0xFFFF,
                        (packets * FRAME_SAMPLES) & 0xFFFFFFFF,
                        local_ssrc,
                    )
                    udp.sendto(header + frame, remote)
                    packets += 1
                    next_send += FRAME_SECONDS
                    if next_send < now - FRAME_SECONDS:
                        next_send = now + FRAME_SECONDS
                readable, _, _ = select.select(
                    [udp], [], [], min(0.02, max(0, next_send - time.monotonic()))
                )
                if readable:
                    packet, source = udp.recvfrom(65535)
                    receiver.receive(packet, source)
        complete = receiver.stats["accepted"] and not any(
            receiver.stats[name]
            for name in ("sequence_gaps", "timestamp_errors", "out_of_order", "wrong_ssrc")
        )
        result = {
            "status": "CAPTURED" if complete else "INCOMPLETE",
            "sent_packets": packets,
            "remote_ip": remote[0],
            "remote_port": remote[1],
            "received_ssrc": receiver.ssrc,
            "packet_format": "uint16be length + RTP packet",
            **receiver.stats,
        }
        _atomic_json(status_path, result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encode-marker", nargs=2, type=Path, metavar=("WAV", "PCMU"))
    parser.add_argument("--bind-ip")
    parser.add_argument("--bind-port", type=int)
    parser.add_argument("--ssrc", type=int)
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--stop", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    if args.encode_marker:
        make_marker(*args.encode_marker)
        return
    required = (
        "bind_ip",
        "bind_port",
        "ssrc",
        "marker",
        "control",
        "ready",
        "stop",
        "output_prefix",
    )
    if any(getattr(args, name) is None for name in required):
        parser.error("RTP endpoint requires bind, marker, control, ready, stop, and output paths")
    run(
        args.bind_ip,
        args.bind_port,
        args.ssrc,
        args.marker,
        args.control,
        args.ready,
        args.stop,
        args.output_prefix,
        args.seconds,
    )


if __name__ == "__main__":
    main()
