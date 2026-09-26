"""Render private SIPp AKA registration inputs; never print credential material."""

from pathlib import Path


def render(path: Path, settings: dict, ue: int, *, rejected: bool = False):
    identity = settings[f"UE{ue}_IMSI"] + "@" + settings["IMS_DOMAIN"]
    realm = settings["IMS_DOMAIN"]
    initial_auth = (
        f'Authorization: Digest username="{identity}", realm="{realm}", nonce="", '
        f'uri="sip:{realm}", response="", algorithm=AKAv1-MD5'
    )
    auth = (
        f"[authentication username={identity} aka_OPc=0x{settings[f'UE{ue}_IMS_OPC']} "
        f"aka_K=0x{settings[f'UE{ue}_IMS_K']} aka_AMF=0x{settings[f'UE{ue}_IMS_AMF']}]"
    )
    if rejected:
        auth = (
            f'Authorization: Digest username="{identity}", realm="{realm}", nonce="[$2]", '
            f'uri="sip:{realm}", response="'
            + "0" * 32
            + '", algorithm=AKAv1-MD5, qop=auth, nc=00000001, cnonce="negative-probe"'
        )

    def message(cseq, authorization):
        return f"""REGISTER sip:{realm} SIP/2.0
Via: SIP/2.0/[transport] [local_ip]:[local_port];branch=[branch]
Max-Forwards: 70
From: <sip:{identity}>;tag=[call_number]
To: <sip:{identity}>
Call-ID: [call_id]
CSeq: {cseq} REGISTER
Contact: <sip:{settings[f"UE{ue}_IMSI"]}@[local_ip]:[local_port]>
{authorization}
Supported: path
Expires: 300
Content-Length: 0

"""

    challenge = '<recv response="401" auth="true"/>'
    reference = ""
    if rejected:
        challenge = """<recv response="401" auth="true"><action>
<ereg regexp="nonce=&quot;([^&quot;]+)&quot;" search_in="hdr" header="WWW-Authenticate:"
 check_it="true" assign_to="1,2"/>
</action></recv>"""
        reference = '<Reference variables="1"/>'
    text = f"""<?xml version="1.0" encoding="UTF-8"?>
<scenario name="AKA registration {"reject-response" if rejected else "positive"}">
<send retrans="500"><![CDATA[
{message(1, initial_auth)}]]></send>
<recv response="100" optional="true"/>
<recv response="100" optional="true"/>
{challenge}
<send retrans="500"><![CDATA[
{message(2, auth)}]]></send>
<recv response="100" optional="true"/>
<recv response="100" optional="true"/>
<recv response="{"403" if rejected else "200"}"/>
{reference}
</scenario>
"""
    path.write_text(text, encoding="utf-8", newline="\n")
