"""Extract subscriber PCMU from mirrored RTP packets."""

import ipaddress
import socket
import struct

from . import runtime


def rtp_payload(packet):
    if len(packet) < 12 or packet[0] >> 6 != 2:
        return b""
    offset = 12 + (packet[0] & 0x0F) * 4
    if len(packet) < offset:
        return b""
    if packet[0] & 0x10:
        if len(packet) < offset + 4:
            return b""
        extension_words = struct.unpack("!H", packet[offset + 2 : offset + 4])[0]
        offset += 4 + extension_words * 4
    padding = packet[-1] if packet[0] & 0x20 else 0
    end = len(packet) - padding
    return packet[offset:end] if offset <= end else b""


def packet_direction(src_ip, dst_ip):
    if dst_ip == runtime.voice_agent_ip:
        return "caller_to_agent"
    if src_ip == runtime.voice_agent_ip:
        return "agent_to_caller"
    if ipaddress.ip_address(src_ip) in runtime.ims_ue_network:
        return "caller_to_core"
    if ipaddress.ip_address(dst_ip) in runtime.ims_ue_network:
        return "core_to_caller"
    return "other"


def capture():
    raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800))
    while True:
        packet = raw.recv(65535)
        if len(packet) < 42 or packet[23] != 17:
            continue
        ihl = (packet[14] & 15) * 4
        udp = 14 + ihl
        src_ip = socket.inet_ntoa(packet[26:30])
        dst_ip = socket.inet_ntoa(packet[30:34])
        src_port, dst_port, length = struct.unpack("!HHH", packet[udp : udp + 6])
        relay_port = src_port if runtime.port_min <= src_port <= runtime.port_max else dst_port
        if not (runtime.port_min <= relay_port <= runtime.port_max) or relay_port % 2:
            continue
        rtp_packet = packet[udp + 8 : udp + length]
        if len(rtp_packet) < 12 or rtp_packet[0] >> 6 != 2:
            continue
        payload_type = rtp_packet[1] & 0x7F
        payload = rtp_payload(rtp_packet)
        if not payload:
            continue
        ssrc = struct.unpack("!I", rtp_packet[8:12])[0]
        direction = packet_direction(src_ip, dst_ip)
        key = (ssrc, src_port, dst_port, payload_type, direction)
        with runtime.lock:
            value = runtime.counters[key]
            value["packets"] += 1
            value["payload_bytes"] += len(payload)
            # Only packets sourced by an IMS-PDU subscriber cross the AI data
            # boundary. Agent TTS is tagged agent_to_caller and cannot feed STT.
            if (
                direction == "caller_to_core"
                and payload_type == 0
                and len(value["audio"]) < runtime.audio_max_bytes
            ):
                remaining = runtime.audio_max_bytes - len(value["audio"])
                value["audio"].extend(payload[:remaining])
