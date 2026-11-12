"""Фейковый SIP AS для unit-тестов: окружение из lab.env, перехват UDP, HTTP и потоков.

runtime SIP AS читает окружение и открывает сокет при импорте, поэтому пакет
загружается один раз с подменённым socket.socket; отправленные датаграммы видны
в runtime.sock.sendto. HTTP к Media Adapter, Voice Agent и AI Worker перехватывается
на уровне httpx.request, фоновые потоки выполняются синхронно.
"""

import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[3]
SIP_AS = ROOT / "app/services/sip-as"


def lab_env():
    values = {}
    for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


ENV = lab_env()
DOMAIN = ENV["IMS_DOMAIN"]
SCSCF = (ENV["SCSCF_IP"], int(ENV["SCSCF_SIP_PORT"]))
RTP_IP = ENV["RTPENGINE_IP"]
RTP_A = int(ENV["RTPENGINE_PORT_MIN"]) + 100
RTP_B = int(ENV["RTPENGINE_PORT_MIN"]) + 50  # внутри пула RTPengine (MIN..MAX)
CALLER = ENV["SIPUE1_MSISDN"]
CALLEE = ENV["SIPUE2_MSISDN"]
UE_HOST = "192.0.2.10"
STATE = (
    "transactions",
    "agent_calls",
    "own_call_ids",
    "record_marks",
    "b2bua_calls",
    "b2bua_branches",
    "answer_hooks",
    "record_invites",
)
_loaded = {}


def load_sip_as():
    if "runtime" in _loaded:
        return _loaded["runtime"]
    token = tempfile.NamedTemporaryFile("w", suffix=".token", delete=False, encoding="ascii")
    token.write("unit-test-token\n")
    token.close()
    env = {
        **ENV,
        "MEDIA_ADAPTER_URL": "http://media.test",
        "VOICE_AGENT_URL": "http://voice.test",
        "AI_WORKER_URL": "http://ai.test",
        "SERVICE_CONTROL_TOKEN_FILE": token.name,
    }
    if str(SIP_AS) not in sys.path:
        sys.path.insert(0, str(SIP_AS))
    with patch.dict(os.environ, env), patch("socket.socket"):
        from ims_sip import app, runtime  # noqa: F401
    _loaded["runtime"] = runtime
    return runtime


def reset_state(runtime):
    for name in STATE:
        if hasattr(runtime, name):
            getattr(runtime, name).clear()


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.content = b"" if data is None else b"{}"

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeHttp:
    """Записывает (метод, URL, JSON); URL с подстрокой из fail отвечает ошибкой связи."""

    def __init__(self):
        self.calls = []
        self.fail = set()
        self.voice_calls = {}

    def __call__(self, method, url, json=None, headers=None, timeout=None, trust_env=None):
        self.calls.append((method, url, json))
        if any(part in url for part in self.fail):
            raise httpx.ConnectError("unit test: service down")
        if method == "GET" and url.endswith("/status"):
            return FakeResponse({"calls": dict(self.voice_calls)})
        return FakeResponse(None)

    def posted(self, fragment):
        return [data for method, url, data in self.calls if method == "POST" and fragment in url]

    def deleted(self, fragment):
        return [url for method, url, _ in self.calls if method == "DELETE" and fragment in url]


class SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class SipCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_sip_as()
        from ims_sip.app import route_request, route_response

        cls.route_request = staticmethod(route_request)
        cls.route_response = staticmethod(route_response)

    def setUp(self):
        reset_state(self.runtime)
        self.runtime.sock.reset_mock()
        self.http = FakeHttp()
        output = io.StringIO()
        for patcher in (
            patch("httpx.request", self.http),
            patch("threading.Thread", SyncThread),
            patch("sys.stdout", output),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = output

    def sent(self):
        return [
            (call.args[0].decode(), call.args[1])
            for call in self.runtime.sock.sendto.call_args_list
        ]

    def statuses(self):
        return [int(m.split(" ", 2)[1]) for m, _ in self.sent() if m.startswith("SIP/2.0")]

    def requests(self, method):
        return [m for m, _ in self.sent() if m.startswith(method + " ")]

    def log(self):
        return self.output.getvalue()


def sdp(ip, port):
    return (
        f"v=0\r\no=- 1 1 IN IP4 {ip}\r\ns=-\r\nc=IN IP4 {ip}\r\nt=0 0\r\n"
        f"m=audio {port} RTP/AVP 0 8\r\na=rtpmap:0 PCMU/8000\r\na=sendrecv\r\n"
    )


def compact_form(message):
    head, _, body = message.partition("\r\n\r\n")
    names = {"Via": "v", "From": "f", "To": "t", "Call-ID": "i", "Contact": "m"}
    names["Content-Type"] = "c"
    for name, short in names.items():
        head = re.sub(rf"(?m)^{re.escape(name)}:", f"{short}:", head)
    return head + "\r\n\r\n" + body


def isc_route(route_host):
    port = ENV["SIP_AS_PORT"]
    return (
        f"Route: <sip:{route_host}.{DOMAIN}:{port};transport=udp;lr>, "
        f"<sip:iscmark@scscf.{DOMAIN}:{SCSCF[1]};lr;s=1;h=0;d=0>"
    )


def invite(
    target,
    call_id="call-a",
    *,
    route_host="as",
    ip=RTP_IP,
    port=RTP_A,
    branch="z9hG4bK-a1",
    caller=CALLER,
    from_tag="fa1",
    served=None,
    to_tag="",
    compact=False,
):
    body = sdp(ip, port)
    uri = f"sip:{target}@{DOMAIN}"
    lines = [
        f"INVITE {uri} SIP/2.0",
        f"Via: SIP/2.0/UDP {SCSCF[0]}:{SCSCF[1]};branch={branch}",
        f"Via: SIP/2.0/UDP {UE_HOST}:5060;branch=z9hG4bK-ue-{branch}",
    ]
    if route_host:
        lines.append(isc_route(route_host))
    lines += [
        f"Record-Route: <sip:mo@scscf.{DOMAIN}:{SCSCF[1]};lr>",
        f"From: <sip:{caller}@{DOMAIN}>;tag={from_tag}",
        f"To: <{uri}>" + (f";tag={to_tag}" if to_tag else ""),
        f"Call-ID: {call_id}",
        "CSeq: 1 INVITE",
        f"Contact: <sip:{caller}@{UE_HOST}:5060>",
        f"P-Asserted-Identity: <sip:{caller}@{DOMAIN}>",
        f"P-Served-User: <sip:{served or caller}@{DOMAIN}>;sescase=orig;regstate=reg",
        "Content-Type: application/sdp",
        f"Content-Length: {len(body)}",
    ]
    message = "\r\n".join(lines) + "\r\n\r\n" + body
    return compact_form(message) if compact else message


def request(
    method,
    call_id,
    *,
    uri,
    from_user,
    from_tag,
    to_user,
    to_tag="",
    cseq=2,
    branch="z9hG4bK-r1",
    route_host=None,
    body="",
):
    lines = [f"{method} {uri} SIP/2.0", f"Via: SIP/2.0/UDP {SCSCF[0]}:{SCSCF[1]};branch={branch}"]
    if route_host:
        lines.append(isc_route(route_host))
    lines += [
        f"From: <sip:{from_user}@{DOMAIN}>;tag={from_tag}",
        f"To: <sip:{to_user}@{DOMAIN}>" + (f";tag={to_tag}" if to_tag else ""),
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} {method}",
        f"Contact: <sip:{from_user}@{UE_HOST}:5060>",
    ]
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body)}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def response(req, status, reason, *, to_tag="", body="", contact="", record_routes=()):
    head = req.split("\r\n\r\n", 1)[0].split("\r\n")
    keep = [line for line in head[1:] if re.match(r"(?i)(Via|v|From|f|Call-ID|i|CSeq)\s*:", line)]
    to = next(line for line in head if re.match(r"(?i)(To|t)\s*:", line))
    if to_tag and ";tag=" not in to:
        to += f";tag={to_tag}"
    lines = [f"SIP/2.0 {status} {reason}", *keep, to]
    lines += [f"Record-Route: {value}" for value in record_routes]
    if contact:
        lines.append(f"Contact: {contact}")
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body)}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def to_tag_of(message):
    match = re.search(r"(?im)^(?:To|t)\s*:[^\r\n]*;tag=([^;>\s]+)", message)
    return match.group(1) if match else ""
