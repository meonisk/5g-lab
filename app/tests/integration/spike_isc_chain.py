"""Spike ISC: два пустых логических AS в цепочке iFC — проверка go/no-go до услуг.

spike1.as — вырожденный B2BUA: пересылает INVITE в S-CSCF с НОВЫМ Call-ID (нога B)
и сохранённым ISC Route; spike2.as — прокси с Record-Route; as — прокси (numbers).
Успех: нога B проходит spike2 (приоритет 25) и as (30), Call-ID звонящего дальше
spike1 не идёт, вызываемый получает INVITE ноги B.

На хосте:     python3 app/tests/integration/spike_isc_chain.py install|restore
В контейнере: python /spike.py serve   (вместо остановленного lab-sip-as)
SPIKE_LEG_B_ROUTE=orig — fallback F1: нога B идёт в S-CSCF через sip:orig@.
"""

import os
import re
import secrets
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VENDOR_IFC = ROOT / "app/infrastructure/vendor/docker_open5gs/pyhss/default_ifc.xml"
SPIKE_IFC = "ifc-spike.xml"
ROUTE = re.compile(r"(?im)^(Route\s*:\s*)<sips?:(?:[^@>]+@)?([^:;>]+)[^>]*>\s*,\s*")
OWN_VIA = re.compile(r"(?im)^(?:Via|v)\s*:[^\r\n]*branch=(z9hG4bK-sp[kx]-[^;\s]+)[^\r\n]*\r\n")
ANY_VIA = re.compile(r"(?im)^(?:Via|v)\s*:[^\r\n]*\r\n")


def criteria(priority, host, settings):
    server = f"sip:{host}.{settings['IMS_DOMAIN']}:{settings['SIP_AS_PORT']};transport=udp"
    return f"""        <InitialFilterCriteria>
            <Priority>{priority}</Priority>
            <TriggerPoint>
                <ConditionTypeCNF>1</ConditionTypeCNF>
                <SPT><ConditionNegated>0</ConditionNegated><Group>0</Group><Method>INVITE</Method></SPT>
                <SPT><ConditionNegated>0</ConditionNegated><Group>1</Group><SessionCase>0</SessionCase></SPT>
            </TriggerPoint>
            <ApplicationServer>
                <ServerName>{server}</ServerName>
                <DefaultHandling>0</DefaultHandling>
            </ApplicationServer>
        </InitialFilterCriteria>
"""


def spike_ifc(settings):
    """default_ifc.xml (as, приоритет 30) + spike1.as (10) + spike2.as (25)."""
    text = VENDOR_IFC.read_text(encoding="utf-8").replace("SIP_AS_PORT", settings["SIP_AS_PORT"])
    extra = criteria(10, "spike1.as", settings) + criteria(25, "spike2.as", settings)
    return text.replace("    </ServiceProfile>", extra + "    </ServiceProfile>", 1)


def set_ifc(ifc_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import provision

    settings = provision.read_env()
    entry = next(e for e in provision.subscribers(settings) if e["name"] == "SIPUE1")
    domain = settings["IMS_DOMAIN"]
    payload = {
        "imsi": entry["imsi"],
        "msisdn": entry["msisdn"],
        "ifc_path": ifc_path,
        "sh_template_path": "default_sh_user_data.xml",
        "scscf": f"sip:scscf.{domain}:{settings['SCSCF_SIP_PORT']}",
        "scscf_realm": domain,
        "scscf_peer": f"scscf.{domain}",
        "pcscf_realm": domain,
        "pcscf_peer": f"pcscf.{domain}",
    }
    provision.upsert(
        provision.PyHSS(settings), "ims_subscriber", "ims_subscriber_id", entry, payload
    )
    return settings


def install():
    sys.path.insert(0, str(ROOT / "scripts"))
    import provision

    xml = spike_ifc(provision.read_env())
    result = subprocess.run(
        ["docker", "exec", "-i", "lab-pyhss", "sh", "-c", 'cat > "$1"', "_", f"/pyhss/{SPIKE_IFC}"],
        input=xml,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise SystemExit("ERROR: не удалось записать iFC в lab-pyhss")
    set_ifc(SPIKE_IFC)
    print("SPIKE iFC installed for SIPUE1: spike1.as(10) -> spike2.as(25) -> as(30)")


def restore():
    set_ifc("default_ifc.xml")
    print("SPIKE iFC removed: SIPUE1 uses default_ifc.xml")


def header_value(message, *names):
    for name in names:
        match = re.search(rf"(?im)^{re.escape(name)}\s*:\s*([^\r\n]+)", message)
        if match:
            return match.group(1)
    return ""


def replace_header(message, names, value):
    pattern = rf"(?im)^(?:{'|'.join(re.escape(name) for name in names)})\s*:[^\r\n]*"
    return re.sub(pattern, lambda _: f"{names[0]}: {value}", message, count=1)


def leg_b(message, call_id, legs, peer, context):
    """Нога B: новый Call-ID и From tag, свой единственный Via, ISC Route сохранён."""
    ip, port, domain, scscf = context
    branch = "z9hG4bK-spk-" + secrets.token_hex(6)
    new_call_id = "spike-" + secrets.token_hex(8)
    from_value = header_value(message, "From", "f")
    vias = "".join(ANY_VIA.findall(message))
    legs[branch] = {"peer": peer, "vias": vias, "call_id": call_id, "from": from_value}
    leg = ANY_VIA.sub("", message)
    leg = replace_header(leg, ("Call-ID", "i"), new_call_id)
    new_from = re.sub(r";tag=[^;>\s]+", ";tag=" + secrets.token_hex(4), from_value)
    leg = replace_header(leg, ("From", "f"), new_from)
    if os.environ.get("SPIKE_LEG_B_ROUTE") == "orig":
        leg = re.sub(r"(?im)^Route\s*:[^\r\n]*\r\n", "", leg)
        line, rest = leg.split("\r\n", 1)
        leg = f"{line}\r\nRoute: <sip:orig@scscf.{domain}:{scscf[1]};lr>\r\n{rest}"
    line, rest = leg.split("\r\n", 1)
    leg = f"{line}\r\nVia: SIP/2.0/UDP {ip}:{port};branch={branch}\r\n{rest}"
    print(f"SPIKE1 leg_b call_id={new_call_id} for call_id={call_id}", flush=True)
    return leg


def request(sock, message, peer, legs, proxied, context):
    ip, port, domain, scscf = context
    method = message.split(" ", 1)[0]
    route = ROUTE.search(message)
    host = route.group(2).lower() if route else ""
    label = host.split(".", 1)[0].upper() or "NOROUTE"
    call_id = header_value(message, "Call-ID", "i")
    print(f"{label} {method} call_id={call_id}", flush=True)
    message = ROUTE.sub(r"\1", message, count=1)
    if label == "SPIKE1" and method == "INVITE" and not call_id.startswith("spike-"):
        sock.sendto(leg_b(message, call_id, legs, peer, context).encode(), scscf)
        return
    line, rest = message.split("\r\n", 1)
    original = re.search(r"branch=([^;\s]+)", rest)
    branch = "z9hG4bK-spx-" + (original.group(1) if original else secrets.token_hex(6))
    proxied[branch] = peer
    extra = ""
    if label == "SPIKE2" and method == "INVITE":
        extra = f"Record-Route: <sip:spike2.as.{domain}:{port};transport=udp;lr>\r\n"
    forwarded = f"{line}\r\nVia: SIP/2.0/UDP {ip}:{port};branch={branch}\r\n{extra}{rest}"
    sock.sendto(forwarded.encode(), scscf)


def relay(sock, message, legs, proxied):
    match = OWN_VIA.search(message)
    if match is None:
        print("SPIKE dropped response without own Via", flush=True)
        return
    branch = match.group(1)
    message = message.replace(match.group(0), "", 1)
    status = message.split("\r\n", 1)[0]
    if branch in legs:
        leg = legs[branch]
        line, rest = ANY_VIA.sub("", message).split("\r\n", 1)
        message = f"{line}\r\n{leg['vias']}{rest}"
        message = replace_header(message, ("Call-ID", "i"), leg["call_id"])
        message = replace_header(message, ("From", "f"), leg["from"])
        print(f"SPIKE1 relayed {status} call_id={leg['call_id']}", flush=True)
        sock.sendto(message.encode(), leg["peer"])
    elif branch in proxied:
        sock.sendto(message.encode(), proxied[branch])


def serve():
    ip, port = os.environ["SIP_AS_IP"], int(os.environ["SIP_AS_PORT"])
    scscf = (os.environ["SCSCF_IP"], int(os.environ["SCSCF_SIP_PORT"]))
    context = (ip, port, os.environ["IMS_DOMAIN"], scscf)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    legs, proxied = {}, {}
    print(f"SPIKE listening udp:{ip}:{port}", flush=True)
    while True:
        data, peer = sock.recvfrom(65535)
        message = data.decode("utf-8", "replace")
        if message.startswith("SIP/2.0"):
            relay(sock, message, legs, proxied)
        else:
            request(sock, message, peer, legs, proxied, context)


if __name__ == "__main__":
    actions = {"install": install, "restore": restore, "serve": serve}
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in actions:
        raise SystemExit(__doc__)
    actions[command]()
