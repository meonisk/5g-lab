import json
import os
import re
import socket
import threading
import time
import urllib.request
import hashlib
import ipaddress
import urllib.parse

bind_ip = os.environ["SIP_AS_IP"]
bind_port = int(os.environ["SIP_AS_PORT"])
scscf = (os.environ["SCSCF_IP"], int(os.environ["SCSCF_SIP_PORT"]))
adapter_url = os.environ["MEDIA_ADAPTER_URL"].rstrip("/") + "/sessions"
voice_url = os.environ["VOICE_AGENT_URL"].rstrip("/") + "/calls"
voice_number = os.environ["VOICE_TRANSLATOR_MSISDN"]
transcriber_number = os.environ["VOICE_TRANSCRIBER_MSISDN"]
voice_user = os.environ["VOICE_AGENT_SIP_USER"]
transcriber_user = os.environ["VOICE_TRANSCRIBER_SIP_USER"]
voice_ip = os.environ["VOICE_AGENT_IP"]
voice_rtp_port = int(os.environ["VOICE_AGENT_RTP_PORT"])
rtpengine_ip = str(ipaddress.ip_address(os.environ["RTPENGINE_IP"]))
rtp_port_min = int(os.environ["RTPENGINE_PORT_MIN"])
rtp_port_max = int(os.environ["RTPENGINE_PORT_MAX"])
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((bind_ip, bind_port))
transactions = {}
agent_calls = {}
service_targets = {
    voice_number: "translate",
    voice_user: "translate",
    transcriber_number: "transcribe",
    transcriber_user: "transcribe",
}

def header(message, name):
    match = re.search(rf"(?im)^{re.escape(name)}\s*:\s*(.+)$", message)
    return match.group(1).strip() if match else ""

def all_headers(message, long_name, compact_name=None):
    names = re.escape(long_name)
    if compact_name:
        names += "|" + re.escape(compact_name)
    # ``.`` also captures the CR in a CRLF-terminated SIP line.  Keeping it
    # would produce ``\r\r\n`` when the local response is assembled and
    # Kamailio would reject the response as having malformed required headers.
    return [line.rstrip("\r") for line in
            re.findall(rf"(?im)^((?:{names})\s*:\s*.+)$", message)]

def notify_adapter(message, service_mode="observe"):
    payload = json.dumps({
        "call_id": header(message, "Call-ID") or header(message, "i"),
        "observed_at": time.time(),
        "service_mode": service_mode,
    }).encode()
    try:
        req = urllib.request.Request(adapter_url, payload, {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {control_token}",
        })
        urllib.request.urlopen(req, timeout=1).read()
    except Exception as exc:
        print(f"AS adapter unavailable (call continues): {exc}", flush=True)

def stop_adapter(call_id):
    try:
        safe_call_id = urllib.parse.quote(call_id, safe="")
        request = urllib.request.Request(f"{adapter_url}/{safe_call_id}", method="DELETE",
                                         headers={"Authorization": f"Bearer {control_token}"})
        urllib.request.urlopen(request, timeout=1).read()
    except Exception as exc:
        print(f"AS adapter cleanup failed call_id={call_id}: {exc}", flush=True)

def notify_voice(call_id, remote_ip, remote_port, service_mode):
    payload = json.dumps({"call_id": call_id, "remote_ip": remote_ip,
                          "remote_port": remote_port, "service_mode": service_mode}).encode()
    req = urllib.request.Request(voice_url, payload, {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {control_token}",
    })
    urllib.request.urlopen(req, timeout=2).read()

def stop_voice(call_id):
    try:
        safe_call_id = urllib.parse.quote(call_id, safe="")
        request = urllib.request.Request(f"{voice_url}/{safe_call_id}", method="DELETE",
                                         headers={"Authorization": f"Bearer {control_token}"})
        urllib.request.urlopen(request, timeout=1).read()
    except Exception as exc:
        print(f"AS voice cleanup failed call_id={call_id}: {exc}", flush=True)

def local_response(request, status, reason, body="", to_tag="", contact_user=None):
    lines = [f"SIP/2.0 {status} {reason}"]
    lines.extend(all_headers(request, "Via", "v"))
    lines.extend(all_headers(request, "Record-Route"))
    from_value = header(request, "From") or header(request, "f")
    to_value = header(request, "To") or header(request, "t")
    if to_tag and ";tag=" not in to_value:
        to_value += f";tag={to_tag}"
    lines += [f"From: {from_value}", f"To: {to_value}",
              f"Call-ID: {header(request, 'Call-ID') or header(request, 'i')}",
              f"CSeq: {header(request, 'CSeq')}"]
    if status == 200 and request.startswith("INVITE "):
        lines += [f"Contact: <sip:{contact_user or voice_user}@{bind_ip}:{bind_port};transport=udp>",
                  "Content-Type: application/sdp"]
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body

def terminate_for_agent(message, peer, service_mode):
    first = message.split("\r\n", 1)[0]
    method = first.split(" ", 1)[0]
    call_id = header(message, "Call-ID") or header(message, "i")
    tag = hashlib.sha256(call_id.encode()).hexdigest()[:16]
    service_user = transcriber_user if service_mode == "transcribe" else voice_user
    if method == "INVITE":
        sock.sendto(local_response(message, 100, "Trying").encode(), peer)
        connection = re.search(r"(?im)^c=IN IP4 ([^\s]+)", message)
        media = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
        if not connection or not media:
            sock.sendto(local_response(message, 488, "Not Acceptable Here", to_tag=tag).encode(), peer)
            return
        try:
            offered_ip = str(ipaddress.ip_address(connection.group(1)))
            offered_port = int(media.group(1))
        except ValueError:
            sock.sendto(local_response(message, 488, "Invalid Media Endpoint", to_tag=tag).encode(), peer)
            return
        # P-CSCF must anchor the offer before iFC sends it to this AS.  Without
        # this check an authenticated SIP caller could make the agent emit RTP
        # toward an arbitrary address (media SSRF/amplification).
        if offered_ip != rtpengine_ip or not rtp_port_min <= offered_port <= rtp_port_max:
            print(f"AS rejected unanchored media call_id={call_id}", flush=True)
            sock.sendto(local_response(message, 488, "Media Must Be Anchored", to_tag=tag).encode(), peer)
            return
        if call_id not in agent_calls:
            try:
                notify_voice(call_id, offered_ip, offered_port, service_mode)
                agent_calls[call_id] = {"tag": tag, "service_mode": service_mode}
                threading.Thread(target=notify_adapter, args=(message, service_mode), daemon=True).start()
            except Exception as exc:
                print(f"AS voice unavailable call_id={call_id}: {exc}", flush=True)
                sock.sendto(local_response(message, 503, "Voice Agent Unavailable", to_tag=tag).encode(), peer)
                return
        body = ("v=0\r\n"
                f"o=voice-agent 1 1 IN IP4 {voice_ip}\r\n"
                "s=IMS Voice Agent\r\n"
                f"c=IN IP4 {voice_ip}\r\n"
                "t=0 0\r\n"
                f"m=audio {voice_rtp_port} RTP/AVP 0\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=ptime:20\r\n"
                "a=sendrecv\r\n")
        sock.sendto(local_response(message, 200, "OK", body, tag, service_user).encode(), peer)
        print(f"AS terminated INVITE for voice agent call_id={call_id} service={service_mode}", flush=True)
    elif method == "ACK":
        print(f"AS received ACK for voice agent call_id={call_id}", flush=True)
    elif method in {"BYE", "CANCEL"}:
        call = agent_calls.get(call_id, {})
        sock.sendto(local_response(message, 200, "OK", to_tag=call.get("tag", tag)).encode(), peer)
        agent_calls.pop(call_id, None)
        threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
        threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
        print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)

def route_request(message, peer):
    first = message.split("\r\n", 1)[0]
    call_id = header(message, "Call-ID") or header(message, "i")
    target = re.search(r"^[A-Z]+\s+sip:([^@; ]+)", first)
    service_mode = agent_calls.get(call_id, {}).get("service_mode")
    if not service_mode and target:
        service_mode = service_targets.get(target.group(1))
    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return
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
        threading.Thread(target=notify_adapter, args=(message, "observe"), daemon=True).start()
    elif first.startswith(("BYE ", "CANCEL ")):
        threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
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
