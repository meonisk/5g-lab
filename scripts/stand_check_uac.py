"""Самотест AI-вызова с preconditions; выполняется внутри контейнера lab-sip-as.

Запускается через `docker exec -i lab-sip-as python -` из stand_check.py.
Только stdlib: в образе SIP AS нет тестовых зависимостей. Сценарий повторяет
штатную звонилку: INVITE (Supported: 100rel, precondition, tel:-номер) ->
надёжный 183 -> PRACK -> UPDATE с готовым QoS -> 200 OK -> ACK -> BYE.
"""

import json
import os
import re
import socket
import time

AS = (os.environ["SIP_AS_IP"], int(os.environ["SIP_AS_PORT"]))
RTP_IP = os.environ["RTPENGINE_IP"]
# Порт из диапазона RTPengine: иначе SIP AS отклонит незаякоренный offer.
RTP_PORT = int(os.environ["RTPENGINE_PORT_MAX"]) - 1
NUMBER = os.environ["VOICE_TRANSLATOR_MSISDN"]
DOMAIN = os.environ["IMS_DOMAIN"]
CALL_ID = f"stand-check-{int(time.time())}"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((AS[0], 0))
sock.settimeout(4)
LOCAL = sock.getsockname()
steps = []


def offer(local):
    return (
        f"v=0\r\no=- 1 1 IN IP4 {RTP_IP}\r\ns=-\r\nc=IN IP4 {RTP_IP}\r\nt=0 0\r\n"
        f"m=audio {RTP_PORT} RTP/AVP 0 96\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:96 AMR/8000\r\n"
        f"a=curr:qos local {local}\r\na=curr:qos remote none\r\n"
        "a=des:qos mandatory local sendrecv\r\na=des:qos none remote sendrecv\r\na=sendrecv\r\n"
    )


def send(method, cseq, body="", extra=(), to_tag=""):
    uri = f"tel:{NUMBER};phone-context={DOMAIN}"
    lines = [
        f"{method} {uri} SIP/2.0",
        f"Via: SIP/2.0/UDP {LOCAL[0]}:{LOCAL[1]};branch=z9hG4bK-{CALL_ID}-{cseq}{method}",
        f"From: <sip:stand-check@{DOMAIN}>;tag=check",
        f"To: <{uri}>" + (f";tag={to_tag}" if to_tag else ""),
        f"Call-ID: {CALL_ID}",
        f"CSeq: {cseq} {method}",
        *extra,
    ]
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
    sock.sendto(("\r\n".join(lines) + "\r\n\r\n" + body).encode(), AS)


def expect(name, method, status, cseq_method, check=None):
    """Ждать ответ status на cseq_method; повторы 183 и 100 пропускаются."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            message = sock.recv(65535).decode("utf-8", "replace")
        except socket.timeout:
            break
        first = message.split("\r\n", 1)[0]
        if f" {cseq_method}" in (re.search(r"(?im)^CSeq:[^\r\n]*", message) or [""])[0]:
            if first.startswith(f"SIP/2.0 {status}") and (check is None or check(message)):
                steps.append({"step": name, "status": "PASS", "response": first})
                return message
            if not first.startswith(("SIP/2.0 100", "SIP/2.0 183")):
                steps.append({"step": name, "status": "FAIL", "response": first})
                return None
    steps.append({"step": name, "status": "FAIL", "response": "нет ответа"})
    return None


def main():
    send("INVITE", 1, offer("none"), ("Supported: 100rel, precondition, timer",))
    early = expect(
        "reliable 183 с QoS",
        "INVITE",
        183,
        "INVITE",
        lambda m: "RSeq: 1" in m and "a=curr:qos local sendrecv" in m,
    )
    if early is None:
        return
    tag = re.search(r"(?im)^To:[^\r\n]*;tag=([^;\s]+)", early).group(1)

    send("PRACK", 2, extra=("RAck: 1 1 INVITE",), to_tag=tag)
    if expect("PRACK -> 200", "PRACK", 200, "PRACK") is None:
        return
    send("UPDATE", 3, offer("sendrecv"), to_tag=tag)
    if expect("UPDATE -> 200 c SDP", "UPDATE", 200, "UPDATE", lambda m: "m=audio" in m) is None:
        return
    if expect("200 OK на INVITE", "INVITE", 200, "INVITE") is None:
        return

    send("ACK", 1, to_tag=tag)
    time.sleep(1)  # Voice Agent успевает принять звонок до BYE.
    send("BYE", 4, to_tag=tag)
    expect("BYE -> 200", "BYE", 200, "BYE")


main()
print(json.dumps({"call_id": CALL_ID, "steps": steps}, ensure_ascii=False))
