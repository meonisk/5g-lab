"""Synthetic AMR round trip through live RTPengine; no RF/phone acceptance claim."""

import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path


def inside():
    address = os.environ["RTPENGINE_IP"]
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.settimeout(3)

    def command(payload):
        cookie = secrets.token_hex(8).encode()
        control.sendto(
            cookie + b" " + json.dumps(payload).encode(),
            (address, int(os.environ["RTPENGINE_NG_PORT"])),
        )
        response = control.recv(65535)
        assert response.startswith(cookie + b" "), "NG cookie mismatch"
        result = json.loads(response.split(b" ", 1)[1])
        assert result.get("result") == "ok", result.get("error-reason", "NG failure")
        return result

    def sdp(port, codec, rate, pt, aligned):
        return (
            f"v=0\r\no=- 1 1 IN IP4 {address}\r\ns=synthetic codec gate\r\n"
            f"c=IN IP4 {address}\r\nt=0 0\r\nm=audio {port} RTP/AVP {pt}\r\n"
            f"a=rtpmap:{pt} {codec}/{rate}\r\n"
            + (f"a=fmtp:{pt} octet-align={aligned}\r\n" if pt else "")
            + "a=sendrecv\r\na=ptime:20\r\n"
        )

    def endpoint(description):
        return (
            re.search(r"c=IN IP4 (\S+)", description)[1],
            int(re.search(r"m=audio (\d+)", description)[1]),
        )

    def exchange(sender, receiver, destination, packets):
        # Resampling has lookahead: one input packet need not yield an output
        # packet immediately. Feed at 20 ms while receiving independently.
        def transmit():
            for packet in packets:
                sender.sendto(packet, destination)
                time.sleep(0.02)

        worker = threading.Thread(target=transmit)
        worker.start()
        received = []
        receiver.settimeout(1)
        try:
            while True:
                received.append(receiver.recv(4096))
        except TimeoutError:
            pass
        finally:
            worker.join()
        assert len(received) >= 12, f"Only {len(received)} audio packets returned"
        return received

    for codec, rate in (("AMR", 8000), ("AMR-WB", 16000)):
        for aligned in (0, 1):
            call = "phone-codec-" + secrets.token_hex(8)
            phone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            service = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for stream in (phone, service):
                stream.bind((address, 0))
                stream.settimeout(2)
            common = {"call-id": call, "from-tag": "phone"}
            try:
                offer = command(
                    {
                        **common,
                        "command": "offer",
                        "sdp": sdp(phone.getsockname()[1], codec, rate, 96, aligned),
                        "flags": ["trust address"],
                        "replace": ["origin", "session connection"],
                        "codec": {"transcode": ["PCMU"]},
                    }
                )
                assert re.search(r"m=audio \d+ RTP/AVP .*\b0\b", offer["sdp"])
                answer = command(
                    {
                        **common,
                        "command": "answer",
                        "to-tag": "ai",
                        "sdp": sdp(service.getsockname()[1], "PCMU", 8000, 0, 0),
                        "flags": ["trust address"],
                        "replace": ["origin", "session connection"],
                    }
                )
                assert f"{codec}/{rate}" in answer["sdp"]
                # Use encoded output as the phone input: prove both encoding and
                # decoding without shipping recorded speech or an AMR fixture.
                input_packets = [
                    struct.pack("!BBHII", 0x80, 0, sequence, sequence * 160, 1234)
                    + (b"\x90" * 10 + b"\x10" * 10) * 8
                    for sequence in range(24)
                ]
                encoded = exchange(service, phone, endpoint(offer["sdp"]), input_packets)
                assert all(p[1] & 127 == 96 and len(p) > 14 for p in encoded)
                decoded = exchange(phone, service, endpoint(answer["sdp"]), encoded)
                assert all(p[1] & 127 == 0 and len(p) == 172 for p in decoded)
                returned = b"".join(p[12:] for p in decoded)
                assert len(set(returned)) > 4, "Returned audio has no test waveform"
                print(
                    f"PASS: {codec} octet-align={aligned} <-> PCMU, "
                    f"encoded={len(encoded)} decoded={len(decoded)} RTP frames"
                )
            finally:
                command({**common, "command": "delete"})
                phone.close()
                service.close()
    control.close()


if __name__ == "__main__":
    if "--inside" in sys.argv:
        inside()
    else:
        result = subprocess.run(
            ["docker", "exec", "-i", "lab-media-adapter", "python", "-", "--inside"],
            input=Path(__file__).read_bytes(),
        )
        raise SystemExit(result.returncode)
