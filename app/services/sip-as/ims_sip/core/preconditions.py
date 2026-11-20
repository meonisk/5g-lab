"""SIP option tags and SDP QoS preconditions (RFC 3262, RFC 3312, TS 24.229).

Pure functions without runtime state: the SIP AS terminates AI calls as a UAS
inside the core network. It has no access network of its own, so its local
QoS segment is always ready; only the phone's segment must be waited for.
"""

import re

# Extensions the AI UAS implements. Any other Require tag gets 420.
SUPPORTED = ("100rel", "precondition")
DIRECTIONS = {"none": 0, "send": 1, "recv": 2, "sendrecv": 3}
STRENGTHS = ("none", "optional", "mandatory")


def option_tags(message: str, long_name: str, compact_name: str = "") -> set[str]:
    headers = message.partition("\r\n\r\n")[0]
    names = re.escape(long_name) + ("|" + re.escape(compact_name) if compact_name else "")
    values = re.findall(rf"(?im)^(?:{names})\s*:\s*([^\r\n]*)", headers)
    return {tag.strip().lower() for value in values for tag in value.split(",") if tag.strip()}


def required(message: str) -> set[str]:
    return option_tags(message, "Require")


def supported(message: str) -> set[str]:
    return option_tags(message, "Supported", "k")


def unsupported_required(message: str) -> set[str]:
    return required(message) - set(SUPPORTED)


def sdp_body(message: str) -> str:
    return message.partition("\r\n\r\n")[2]


def qos_status(sdp: str) -> dict:
    """Current and desired status per segment, seen from the SDP author.

    3GPP uses segmented status (local/remote). An end-to-end line is treated
    as the author's local segment: the AS adds no segment of its own.
    """
    status = {"curr": {}, "des": {}}
    for kind, value in re.findall(r"(?im)^a=(curr|des):qos\s+([^\r\n]+)", sdp):
        parts = value.split()
        if kind == "curr" and len(parts) == 2 and parts[1] in DIRECTIONS:
            segment = "local" if parts[0] == "e2e" else parts[0]
            status["curr"][segment] = parts[1]
        elif kind == "des" and len(parts) == 3 and parts[0] in STRENGTHS:
            segment = "local" if parts[1] == "e2e" else parts[1]
            if parts[2] in DIRECTIONS:
                status["des"][segment] = (parts[0], parts[2])
    return status


def uses_preconditions(sdp: str) -> bool:
    return bool(qos_status(sdp)["des"])


def covers(current: str, wanted: str) -> bool:
    return DIRECTIONS[current] & DIRECTIONS[wanted] == DIRECTIONS[wanted]


def offerer_ready(sdp: str) -> bool:
    """True when the phone's own mandatory segment already has resources."""
    status = qos_status(sdp)
    strength, direction = status["des"].get("local", ("none", "sendrecv"))
    if strength != "mandatory":
        return True
    return covers(status["curr"].get("local", "none"), direction)


def answer_lines(offer_sdp: str) -> list[str]:
    """Media-level attributes of the AS answer (RFC 3312 section 6).

    The offerer's "local" becomes our "remote" and vice versa. Our segment is
    reported as already reserved; a conf line asks the phone to send UPDATE
    when its segment is ready, so the final 200 OK follows its reservation.
    """
    if not uses_preconditions(offer_sdp):
        return []
    status = qos_status(offer_sdp)
    their_strength, their_direction = status["des"].get("local", ("mandatory", "sendrecv"))
    our_strength, our_direction = status["des"].get("remote", ("none", "sendrecv"))
    lines = [
        "a=curr:qos local sendrecv",
        f"a=curr:qos remote {status['curr'].get('local', 'none')}",
        f"a=des:qos {our_strength} local {our_direction}",
        f"a=des:qos {their_strength} remote {their_direction}",
    ]
    if not offerer_ready(offer_sdp):
        lines.append(f"a=conf:qos remote {their_direction}")
    return lines
