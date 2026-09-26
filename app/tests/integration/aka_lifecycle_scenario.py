"""Render a private one-socket IMS AKA register/refresh/deregister scenario."""

from pathlib import Path

try:
    from . import aka_scenario
except ImportError:  # Direct integration-script import.
    import aka_scenario


def _seconds(settings: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(settings.get(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _initial_body(path: Path, settings: dict, ue: int) -> str:
    temporary = path.with_name(path.name + ".initial.xml")
    if temporary.exists():
        raise FileExistsError(temporary)
    try:
        aka_scenario.render(temporary, settings, ue)
        xml = temporary.read_text(encoding="utf-8")
    finally:
        temporary.unlink(missing_ok=True)
    return xml.split("<scenario", 1)[1].split(">", 1)[1].rsplit("</scenario>", 1)[0]


def _register(settings: dict, ue: int, cseq: int, expires: int, authorization: str) -> str:
    imsi = settings[f"UE{ue}_IMSI"]
    realm = settings["IMS_DOMAIN"]
    identity = f"{imsi}@{realm}"
    return f"""<send retrans="500"><![CDATA[
REGISTER sip:{realm} SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
Max-Forwards: 70
From: <sip:{identity}>;tag=[call_number]
To: <sip:{identity}>
Call-ID: [call_id]
CSeq: {cseq} REGISTER
Contact: <sip:{imsi}@[local_ip]:[local_port]>
{authorization}
Supported: path
Expires: {expires}
Content-Length: 0

]]></send>
"""


def _exchange(settings: dict, ue: int, first_cseq: int, expires: int) -> str:
    identity = f"{settings[f'UE{ue}_IMSI']}@{settings['IMS_DOMAIN']}"
    realm = settings["IMS_DOMAIN"]
    selector = (
        f'Authorization: Digest username="{identity}", realm="{realm}", '
        f'nonce="", uri="sip:{realm}", response="", algorithm=AKAv1-MD5'
    )
    authorization = _authorization(settings, ue)
    # S-CSCF's REGISTER route challenges an unauthenticated request before
    # ims_registrar_scscf.save; each phase obtains a fresh challenge vector.
    return (
        _register(settings, ue, first_cseq, expires, selector)
        + '<recv response="100" optional="true"/>\n'
        + '<recv response="100" optional="true"/>\n'
        + '<recv response="401" auth="true"/>\n'
        + _register(settings, ue, first_cseq + 1, expires, authorization)
        + '<recv response="100" optional="true"/>\n'
        + '<recv response="100" optional="true"/>\n'
        + '<recv response="200"/>\n'
    )


def _authorization(settings: dict, ue: int) -> str:
    identity = f"{settings[f'UE{ue}_IMSI']}@{settings['IMS_DOMAIN']}"
    return (
        f"[authentication username={identity} "
        f"aka_OPc=0x{settings[f'UE{ue}_IMS_OPC']} "
        f"aka_K=0x{settings[f'UE{ue}_IMS_K']} "
        f"aka_AMF=0x{settings[f'UE{ue}_IMS_AMF']}]"
    )


def render(path: Path, settings: dict, ue: int) -> Path:
    """Write XML under caller-owned private path; return it for SIPp -sf."""
    if ue not in (1, 2):
        raise ValueError("ue must be 1 or 2")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = _seconds(settings, "SIP_AKA_LIFECYCLE_CHECKPOINT_SECONDS", 20, 1, 120)
    final = _seconds(settings, "SIP_AKA_LIFECYCLE_FINAL_SECONDS", 5, 1, 30)
    initial = _initial_body(path, settings, ue)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<scenario name="AKA registration lifecycle">\n'
        + initial
        + f'<pause milliseconds="{checkpoint * 1000}"/>\n'
        + _exchange(settings, ue, 3, 300)
        + f'<pause milliseconds="{checkpoint * 1000}"/>\n'
        + _exchange(settings, ue, 5, 0)
        + f'<pause milliseconds="{final * 1000}"/>\n'
        + "</scenario>\n"
    )
    path.write_text(xml, encoding="utf-8", newline="\n")
    return path
