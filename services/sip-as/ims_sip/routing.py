"""Proxy ordinary dialogs and terminate configured AI service calls."""

import hashlib
import ipaddress
import re
import threading
import time

from . import runtime
from .control import notify_adapter, notify_voice, stop_adapter, stop_voice
from .messages import header, local_response


def terminate_for_agent(message, peer, service_mode):
    first = message.split("\r\n", 1)[0]
    method = first.split(" ", 1)[0]
    call_id = header(message, "Call-ID") or header(message, "i")
    tag = hashlib.sha256(call_id.encode()).hexdigest()[:16]
    service_user = runtime.transcriber_user if service_mode == "transcribe" else runtime.voice_user
    if method == "INVITE":
        runtime.sock.sendto(local_response(message, 100, "Trying").encode(), peer)
        connection = re.search(r"(?im)^c=IN IP4 ([^\s]+)", message)
        media = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
        if not connection or not media:
            runtime.sock.sendto(
                local_response(message, 488, "Not Acceptable Here", to_tag=tag).encode(),
                peer,
            )
            return
        try:
            offered_ip = str(ipaddress.ip_address(connection.group(1)))
            offered_port = int(media.group(1))
        except ValueError:
            runtime.sock.sendto(
                local_response(message, 488, "Invalid Media Endpoint", to_tag=tag).encode(),
                peer,
            )
            return
        # P-CSCF must anchor the offer before iFC sends it to this AS.  Without
        # this check an authenticated SIP caller could make the agent emit RTP
        # toward an arbitrary address (media SSRF/amplification).
        if (
            offered_ip != runtime.rtpengine_ip
            or not runtime.rtp_port_min <= offered_port <= runtime.rtp_port_max
        ):
            print(f"AS rejected unanchored media call_id={call_id}", flush=True)
            runtime.sock.sendto(
                local_response(message, 488, "Media Must Be Anchored", to_tag=tag).encode(),
                peer,
            )
            return
        if call_id not in runtime.agent_calls:
            try:
                notify_voice(call_id, offered_ip, offered_port, service_mode)
                runtime.agent_calls[call_id] = {
                    "tag": tag,
                    "service_mode": service_mode,
                }
                threading.Thread(
                    target=notify_adapter, args=(message, service_mode), daemon=True
                ).start()
            except Exception as exc:
                print(f"AS voice unavailable call_id={call_id}: {exc}", flush=True)
                runtime.sock.sendto(
                    local_response(message, 503, "Voice Agent Unavailable", to_tag=tag).encode(),
                    peer,
                )
                return
        body = (
            "v=0\r\n"
            f"o=voice-agent 1 1 IN IP4 {runtime.voice_ip}\r\n"
            "s=IMS Voice Agent\r\n"
            f"c=IN IP4 {runtime.voice_ip}\r\n"
            "t=0 0\r\n"
            f"m=audio {runtime.voice_rtp_port} RTP/AVP 0\r\n"
            "a=rtpmap:0 PCMU/8000\r\n"
            "a=ptime:20\r\n"
            "a=sendrecv\r\n"
        )
        runtime.sock.sendto(
            local_response(message, 200, "OK", body, tag, service_user).encode(), peer
        )
        print(
            f"AS terminated INVITE for voice agent call_id={call_id} service={service_mode}",
            flush=True,
        )
    elif method == "ACK":
        print(f"AS received ACK for voice agent call_id={call_id}", flush=True)
    elif method in {"BYE", "CANCEL"}:
        call = runtime.agent_calls.get(call_id, {})
        runtime.sock.sendto(
            local_response(message, 200, "OK", to_tag=call.get("tag", tag)).encode(),
            peer,
        )
        runtime.agent_calls.pop(call_id, None)
        threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
        threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
        print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)


def route_request(message, peer):
    first = message.split("\r\n", 1)[0]
    call_id = header(message, "Call-ID") or header(message, "i")
    target = re.search(r"^[A-Z]+\s+sip:([^@; ]+)", first)
    service_mode = runtime.agent_calls.get(call_id, {}).get("service_mode")
    if not service_mode and target:
        service_mode = runtime.service_targets.get(target.group(1))
    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return
    branch_match = re.search(r"(?im)^Via\s*:\s*[^\r\n]*branch=([^;\s]+)", message)
    if not branch_match:
        branch_match = re.search(r"(?im)^v\s*:\s*[^\r\n]*branch=([^;\s]+)", message)
    branch = branch_match.group(1) if branch_match else str(time.time_ns())
    runtime.transactions[branch] = peer
    via = f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    first, rest = message.split("\r\n", 1)
    # Consume the AS Route only; the following ISC Route returns the request to S-CSCF.
    rest = re.sub(r"(?im)^(Route\s*:\s*)<sip:as\.[^>]+>\s*,\s*", r"\1", rest, count=1)
    forwarded = first + "\r\n" + via + rest
    if first.startswith("INVITE "):
        print(
            f"AS observed INVITE call_id={header(message, 'Call-ID') or header(message, 'i')}",
            flush=True,
        )
        threading.Thread(target=notify_adapter, args=(message, "observe"), daemon=True).start()
    elif first.startswith(("BYE ", "CANCEL ")):
        threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
    runtime.sock.sendto(forwarded.encode(), runtime.scscf)


def route_response(message):
    match = re.search(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-([^;\s]+)\r\n", message)
    if not match:
        print(
            f"AS dropped response without own Via: {message.splitlines()[0]}",
            flush=True,
        )
        return
    peer = runtime.transactions.get(match.group(1))
    if not peer:
        print(f"AS dropped response for unknown transaction {match.group(1)}", flush=True)
        return
    message = re.sub(
        r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-[^\r\n]+\r\n",
        "",
        message,
        count=1,
    )
    print(
        f"AS relayed response {message.splitlines()[0]} to {peer[0]}:{peer[1]}",
        flush=True,
    )
    runtime.sock.sendto(message.encode(), peer)
