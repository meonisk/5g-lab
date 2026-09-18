import json
import os
import re
import socket
import threading
import time
import urllib.request

bind_ip = os.environ["SIP_AS_IP"]
bind_port = int(os.environ["SIP_AS_PORT"])
scscf = (os.environ["SCSCF_IP"], int(os.environ["SCSCF_SIP_PORT"]))
adapter_url = os.environ["MEDIA_ADAPTER_URL"].rstrip("/") + "/sessions"
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((bind_ip, bind_port))
transactions = {}

def header(message, name):
    match = re.search(rf"(?im)^{re.escape(name)}\s*:\s*(.+)$", message)
    return match.group(1).strip() if match else ""

def notify_adapter(message):
    payload = json.dumps({
        "call_id": header(message, "Call-ID") or header(message, "i"),
        "from": header(message, "From") or header(message, "f"),
        "to": header(message, "To") or header(message, "t"),
        "observed_at": time.time(),
        "mode": "OBSERVE",
    }).encode()
    try:
        req = urllib.request.Request(adapter_url, payload, {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=1).read()
    except Exception as exc:
        print(f"AS adapter unavailable (call continues): {exc}", flush=True)

def route_request(message, peer):
    branch_match = re.search(r"(?im)^Via\s*:\s*[^\r\n]*branch=([^;\s]+)", message)
    if not branch_match:
        branch_match = re.search(r"(?im)^v\s*:\s*[^\r\n]*branch=([^;\s]+)", message)
    branch = branch_match.group(1) if branch_match else str(time.time_ns())
    transactions[branch] = peer
    via = f"Via: SIP/2.0/UDP {bind_ip}:{bind_port};branch=z9hG4bK-as-{branch}\r\n"
    first, rest = message.split("\r\n", 1)
    # Consume the AS Route only; the following ISC Route returns the request to S-CSCF.
    rest = re.sub(r"(?im)^(Route\s*:\s*)<sip:as\.[^>]+>\s*,\s*", r"\1", rest, count=1)
    forwarded = first + "\r\n" + via + rest
    if first.startswith("INVITE "):
        print(f"AS observed INVITE call_id={header(message, 'Call-ID') or header(message, 'i')}", flush=True)
        threading.Thread(target=notify_adapter, args=(message,), daemon=True).start()
    sock.sendto(forwarded.encode(), scscf)

def route_response(message):
    match = re.search(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-([^;\s]+)\r\n", message)
    if not match:
        print(f"AS dropped response without own Via: {message.splitlines()[0]}", flush=True)
        return
    peer = transactions.get(match.group(1))
    if not peer:
        print(f"AS dropped response for unknown transaction {match.group(1)}", flush=True)
        return
    message = re.sub(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-[^\r\n]+\r\n", "", message, count=1)
    print(f"AS relayed response {message.splitlines()[0]} to {peer[0]}:{peer[1]}", flush=True)
    sock.sendto(message.encode(), peer)

print(f"SIP AS listening udp:{bind_ip}:{bind_port}; next={scscf[0]}:{scscf[1]}", flush=True)
while True:
    data, peer = sock.recvfrom(65535)
    message = data.decode("utf-8", "replace")
    if message.startswith("SIP/2.0"):
        route_response(message)
    else:
        route_request(message, peer)
