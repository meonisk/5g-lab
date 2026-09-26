"""Render bounded, private SIPp registration and two-UE call scenarios."""

from pathlib import Path

try:
    from . import aka_scenario
except ImportError:  # Direct integration-script imports also work.
    import aka_scenario


def _number(settings: dict, name: str, default: int, low: int, high: int) -> int:
    value = int(settings.get(name, default))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _register_body(directory: Path, settings: dict, ue: int) -> str:
    # Reuse the tested AKA REGISTER sequence, including its explicit OPc input.
    temporary = directory / f"ue{ue}-register-source.xml"
    aka_scenario.render(temporary, settings, ue)
    xml = temporary.read_text(encoding="utf-8")
    temporary.unlink()
    body = xml.split("<scenario", 1)[1].split(">", 1)[1].rsplit("</scenario>", 1)[0]
    final = '<recv response="200"/>'
    if body.count(final) != 1:
        raise ValueError("AKA registration template changed its 200 response")

    # A missing Service-Route is a failed IMS registration contract for this call.
    capture = """<recv response="200"><action>
<ereg regexp="(.+)" search_in="hdr" header="Service-Route:"
 check_it="true" assign_to="route_match,service_route"/>
</action></recv>"""
    return body.replace(final, capture) + '<Reference variables="route_match"/>\n'


def _message(lines: str, *, retrans: int | None = None) -> str:
    attr = f' retrans="{retrans}"' if retrans else ""
    return f"<send{attr}><![CDATA[\n{lines.rstrip()}\n\n]]></send>\n"


def _caller_call(
    settings: dict, caller: int, callee: int, media_port: int, delay: int, seconds: int
) -> str:
    domain = settings["IMS_DOMAIN"]
    from_id = settings[f"UE{caller}_IMSI"]
    to_id = settings[f"UE{callee}_IMSI"]
    from_uri = f"sip:{from_id}@{domain}"
    to_uri = f"sip:{to_id}@{domain}"
    invite = f"""INVITE {to_uri} SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
Max-Forwards: 70
From: <{from_uri}>;tag=[call_number]
To: <{to_uri}>
Call-ID: [call_id]
CSeq: 1 INVITE
Contact: <sip:{from_id}@[local_ip]:[local_port]>
Route: [$service_route]
Content-Type: application/sdp
Content-Length: [len]

v=0
o=- 1 1 IN IP4 [media_ip]
s=AKA PCMU call
c=IN IP4 [media_ip]
t=0 0
m=audio {media_port} RTP/AVP 0
a=rtpmap:0 PCMU/8000"""
    ack = f"""ACK [next_url] SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
Max-Forwards: 70
From: <{from_uri}>;tag=[call_number]
To: <{to_uri}>[peer_tag_param]
Call-ID: [call_id]
CSeq: 1 ACK
[routes]
Content-Length: 0"""
    bye = f"""BYE [next_url] SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
Max-Forwards: 70
From: <{from_uri}>;tag=[call_number]
To: <{to_uri}>[peer_tag_param]
Call-ID: [call_id]
CSeq: 2 BYE
[routes]
Content-Length: 0"""
    return (
        f'<pause milliseconds="{delay}"/>\n'
        + _message(invite, retrans=500)
        + '<recv response="100" optional="true"/>\n'
        + '<recv response="180" optional="true"/>\n'
        + '<recv response="200" rrs="true"/>\n'
        + _message(ack)
        + f'<pause milliseconds="{seconds * 1000}"/>\n'
        + _message(bye, retrans=500)
        + '<recv response="200"/>\n'
    )


def _callee_ooc(settings: dict, callee: int, media_port: int, seconds: int) -> str:
    uri = f"sip:{settings[f'UE{callee}_IMSI']}@{settings['IMS_DOMAIN']}"
    response = f"""SIP/2.0 200 OK
[last_Via:]
[last_Record-Route:]
[last_From:]
To: <{uri}>;tag=[call_number]
[last_Call-ID:]
[last_CSeq:]
Contact: <sip:{settings[f"UE{callee}_IMSI"]}@[local_ip]:[local_port]>
Content-Type: application/sdp
Content-Length: [len]

v=0
o=- 1 1 IN IP4 [media_ip]
s=AKA PCMU call
c=IN IP4 [media_ip]
t=0 0
m=audio {media_port} RTP/AVP 0
a=rtpmap:0 PCMU/8000"""
    bye_ok = f"""SIP/2.0 200 OK
[last_Via:]
[last_From:]
To: <{uri}>;tag=[call_number]
[last_Call-ID:]
[last_CSeq:]
Content-Length: 0"""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<scenario name="AKA callee UAS">\n'
        '<recv request="INVITE" rrs="true"/>\n'
        + _message(response)
        + '<recv request="ACK"/>\n'
        + f'<recv request="BYE" timeout="{(seconds + 20) * 1000}"/>\n'
        + _message(bye_ok)
        + "</scenario>\n"
    )


def render_pair(directory: Path, settings: dict, caller_ue: int = 1) -> dict[str, Path]:
    """Return caller, callee, and callee-OOC XML paths; secrets stay in directory."""
    if caller_ue not in (1, 2):
        raise ValueError("caller_ue must be 1 or 2")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    media_port = _number(settings, "SIP_AKA_MEDIA_PORT", 4000, 1024, 65534)
    seconds = _number(settings, "SIP_AKA_CALL_SECONDS", 20, 1, 120)
    delay = _number(settings, "SIP_AKA_INVITE_DELAY_MS", 5000, 0, 30000)
    callee = 3 - caller_ue
    outputs = {}

    for ue, role in ((caller_ue, "caller"), (callee, "callee")):
        register = _register_body(directory, settings, ue)
        second = (
            _caller_call(settings, ue, callee, media_port, delay, seconds)
            if role == "caller"
            else f'<pause milliseconds="{(seconds + 40) * 1000}"/>\n'
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scenario name="AKA {role}">\n'
            '<User variables="registered,service_route"/>\n'
            '<nop next="2" test="registered"/>\n'
            + register
            + '<nop next="19"><action><assignstr assign_to="registered" value="yes"/></action></nop>\n'
            + '<label id="2"/>\n'
            + second
            + '<label id="19"/>\n'
            + "</scenario>\n"
        )
        path = directory / f"ue{ue}-{role}-main.xml"
        path.write_text(xml, encoding="utf-8", newline="\n")
        outputs[role] = path

    ooc = directory / f"ue{callee}-callee-ooc.xml"
    ooc.write_text(
        _callee_ooc(settings, callee, media_port, seconds), encoding="utf-8", newline="\n"
    )
    outputs["callee_ooc"] = ooc
    return outputs
