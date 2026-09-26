"""Ethernet PCAP and TCP stream reconstruction for Cx metadata."""

from __future__ import annotations

import struct
from collections import defaultdict
from pathlib import Path


class IncompleteCapture(ValueError):
    pass


def _pcap_packets(path: Path):
    data = Path(path).read_bytes()
    if len(data) < 24:
        raise IncompleteCapture("PCAP header missing")
    magic = data[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian = "<"
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian = ">"
    else:
        raise IncompleteCapture("Unsupported PCAP encoding")
    _, major, minor, _, _, snaplen, linktype = struct.unpack_from(endian + "IHHIIII", data)
    if (major, minor) != (2, 4) or linktype != 1 or snaplen < 54:
        raise IncompleteCapture("Unsupported PCAP format")
    offset = 24
    while offset < len(data):
        if len(data) - offset < 16:
            raise IncompleteCapture("Truncated PCAP record")
        _, _, captured, original = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        if captured > snaplen or captured != original or len(data) - offset < captured:
            raise IncompleteCapture("Truncated packet capture")
        yield data[offset : offset + captured]
        offset += captured


def _tcp_segment(frame: bytes):
    if len(frame) < 34:
        raise IncompleteCapture("Truncated Ethernet frame")
    kind = int.from_bytes(frame[12:14], "big")
    offset = 14
    if kind in (0x8100, 0x88A8):
        if len(frame) < 38:
            raise IncompleteCapture("Truncated VLAN frame")
        kind = int.from_bytes(frame[16:18], "big")
        offset = 18
    if kind != 0x0800:
        return None
    if len(frame) < offset + 20:
        raise IncompleteCapture("Truncated IPv4 header")
    ip = frame[offset:]
    ihl = (ip[0] & 15) * 4
    if ip[0] >> 4 != 4 or ihl < 20 or len(ip) < ihl:
        raise IncompleteCapture("Invalid IPv4 header")
    total = int.from_bytes(ip[2:4], "big")
    if total < ihl or len(ip) < total:
        raise IncompleteCapture("Truncated IPv4 datagram")
    if ip[9] != 6:
        return None
    if int.from_bytes(ip[6:8], "big") & 0x3FFF:
        raise IncompleteCapture("Fragmented Cx TCP datagram")
    tcp = ip[ihl:total]
    if len(tcp) < 20:
        raise IncompleteCapture("Truncated TCP header")
    source_port, dest_port, sequence = struct.unpack_from("!HHI", tcp)
    header = (tcp[12] >> 4) * 4
    if header < 20 or len(tcp) < header:
        raise IncompleteCapture("Invalid TCP header")
    syn = bool(tcp[13] & 2)
    flow = (bytes(ip[12:16]), source_port, bytes(ip[16:20]), dest_port)
    return flow, sequence + int(syn), tcp[header:]


def _streams(path: Path, port: int) -> list[bytes]:
    segments = defaultdict(list)
    for frame in _pcap_packets(path):
        parsed = _tcp_segment(frame)
        if parsed is None:
            continue
        flow, sequence, payload = parsed
        if port in (flow[1], flow[3]) and payload:
            segments[flow].append((sequence, payload))
    if not segments:
        raise IncompleteCapture("No Cx TCP payload")
    streams = []
    for parts in segments.values():
        parts.sort(key=lambda item: item[0])
        base = parts[0][0]
        result = bytearray()
        for sequence, payload in parts:
            relative = sequence - base
            if relative > len(result):
                raise IncompleteCapture("TCP sequence gap")
            overlap = max(0, len(result) - relative)
            if result[relative : relative + overlap] != payload[:overlap]:
                raise IncompleteCapture("Conflicting TCP overlap")
            result.extend(payload[overlap:])
        streams.append(bytes(result))
    return streams
