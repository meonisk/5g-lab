# Услуги IMS ближе к 3GPP: iFC по абоненту, B2BUA, цепочка AS — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** услуги подключаются по профилю абонента в HSS (iFC) несколькими логическими AS
цепочкой через S-CSCF: перевод (`translate`, B2BUA через MRF) и запись (`record`), а
`*номер` разово включает перевод; номера 1003–1006 работают как раньше.

**Architecture:** `scripts/provision.py` собирает iFC каждого абонента из `lab.env` и
кладёт его в `lab-pyhss`. Один процесс `lab-sip-as` содержит несколько логических AS:
`core/` (SIP-разбор, транспорт, прокси, B2BUA, диспетчер по Route, API MRF) и
`services/` (`translate`, `record`, `numbers`). AI Worker получает от SIP AS явную пару
ног и запись обеих сторон; уведомление о записи без перевода играет RTPengine по
команде Media Adapter.

**Tech Stack:** Python 3.13 (stdlib, Flask/waitress/httpx из `requirements-http.txt`),
Kamailio `ims_isc` (S-CSCF), PyHSS (Jinja2-шаблоны iFC), dnsmasq, RTPengine NG
(`query`, `play media`), unittest, bash-проверки на стенде.

## Global Constraints

- Спецификация — `docs/superpowers/specs/2026-11-12-ims-services-3gpp-design.md`; при расхождении прав она.
- Python сервисов — 3.13 (`python:3.13.7-alpine3.22`); ruff `target-version = "py311"`, `line-length = 100`, правила `F`, `I`.
- Новых зависимостей нет: только stdlib и пакеты из `app/services/requirements-http.txt`; `lab_common/` не меняется.
- В каждом `.py`/`.sh` не больше 300 логических строк (`scripts/check.py`, `MAX_LOGICAL_LINES`).
- Адреса, IMSI и домен — только в `app/config/lab.env`; в коде и тестах — из окружения/`lab.env`, чужие адреса только из `192.0.2.0/24`, `198.51.100.0/24`.
- Журналы сервисов — только Call-ID и метаданные; IMSI, номера и текст реплик не печатаются (`verify-security.sh`).
- Ключи `lab.env`: `UE1_SERVICES=translate,record`, `UE1_LANGUAGE=ru`, `UE2_SERVICES=`, `UE2_LANGUAGE=en`, `SIPUE1_SERVICES=translate,record`, `SIPUE1_LANGUAGE=ru`, `SIPUE2_SERVICES=`, `SIPUE2_LANGUAGE=en`, `DEFAULT_LANGUAGE=ru`, `RECORDING_ANNOUNCEMENT_RU`, `RECORDING_ANNOUNCEMENT_EN`.
- URI логических AS: `sip:translate.as.<IMS_DOMAIN>:<SIP_AS_PORT>;transport=udp`, `sip:record.as.<IMS_DOMAIN>:<SIP_AS_PORT>;transport=udp`, `sip:as.<IMS_DOMAIN>:<SIP_AS_PORT>;transport=udp` (numbers).
- Приоритеты iFC: translate 10, `*номер` → translate 15, record 20, numbers 30, SMS (`MESSAGE`) 40.
- `DefaultHandling` = `0` (SESSION_CONTINUED) у всех правил.
- Языки услуг — только `ru` и `en` (режимы `interpret_ru`, `interpret_en`); не задан — `DEFAULT_LANGUAGE`.
- Номера 1003–1006 ведут себя как раньше: translate и record пропускают их без изменений; их проверки не меняются.
- Call-ID ноги B — `b2b-<24 hex>` (проходит `lab_common.http.valid_call_id`).
- Shell-скрипты — окончания LF и бит исполнения в Git (`git update-index --chmod=+x`).
- Unit: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit`; offline-ворота перед коммитом: `python3 scripts/check.py` → `OFFLINE CHECKS: PASS`.
- Интеграционные проверки — только на Linux-стенде, строго по одной.
- Сообщения коммитов — Conventional Commits, без строк Co-Authored-By и упоминаний AI.

---

## File Structure

Создаются:

| Файл | Ответственность |
|---|---|
| `app/tests/integration/spike_isc_chain.py` | spike: два пустых логических AS в цепочке iFC, go/no-go |
| `app/services/sip-as/ims_sip/core/__init__.py` | пакет SIP-ядра |
| `app/services/sip-as/ims_sip/core/sip.py` | разбор SIP без состояния: заголовки, tag, Route, CSeq |
| `app/services/sip-as/ims_sip/core/transport.py` | отправка UDP и локальные ответы |
| `app/services/sip-as/ims_sip/core/sdp.py` | допуск PCMU и адрес медиа из SDP (бывший `ims_sip/sdp.py`) |
| `app/services/sip-as/ims_sip/core/mrf.py` | API MRF: места, ноги, озвучка, распознавание, освобождение, пара, запись, уведомление |
| `app/services/sip-as/ims_sip/core/proxy.py` | прокси-путь: свой Via, снятие своего Route, возврат ответов, хук ответа |
| `app/services/sip-as/ims_sip/core/dialogs.py` | Call-ID, созданные AS, и пометки записи |
| `app/services/sip-as/ims_sip/core/subscribers.py` | язык по MSISDN/IMSI, обслуживаемый и вызываемый абонент |
| `app/services/sip-as/ims_sip/core/b2bua.py` | две ноги звонка: нога B через S-CSCF, ответы, BYE/CANCEL, re-INVITE |
| `app/services/sip-as/ims_sip/core/dispatch.py` | вход SIP: логический AS по первому Route, диалоги B2BUA, иначе numbers |
| `app/services/sip-as/ims_sip/services/__init__.py` | контракт модуля услуги |
| `app/services/sip-as/ims_sip/services/numbers.py` | 1003–1006 и observe (перенос из `routing.py`) |
| `app/services/sip-as/ims_sip/services/translate.py` | translate AS: B2BUA с переводом или прозрачный прокси |
| `app/services/sip-as/ims_sip/services/record.py` | record AS: пометка записи, уведомление, поток в AI |
| `app/tests/unit/sip_fakes.py` | фейковые сокет, HTTP и потоки; построители SIP-сообщений |
| `app/tests/unit/test_ifc_generation.py` | iFC из `lab.env`, профили, provisioning, DNS |
| `app/tests/unit/test_sip_as_numbers.py` | характеризация 1003–1006 и observe |
| `app/tests/unit/test_sip_as_dispatch.py` | Route-хост, языки, снятие Route, свои диалоги |
| `app/tests/unit/test_sip_as_mrf.py` | API MRF |
| `app/tests/unit/test_ai_pairs.py` | пары ног в AI Worker |
| `app/tests/unit/test_sip_as_translate.py` | нога B, 180, ответ, пара |
| `app/tests/unit/test_sip_as_b2bua_teardown.py` | 486/480/408, BYE, CANCEL, re-INVITE/UPDATE |
| `app/tests/unit/test_sip_as_translate_bypass.py` | `*номер`, прозрачный режим |
| `app/tests/unit/test_ai_recording.py` | запись обеих сторон в AI Worker |
| `app/tests/unit/test_announcements.py` | WAV уведомления и `play media` |
| `app/tests/unit/test_sip_as_record.py` | record AS |
| `app/tests/integration/verify-services.sh` | сценарии 1–4 на SIPUE |

Изменяются: `scripts/provision.py`, `app/config/lab.env`,
`app/infrastructure/configs/dns/ims-dnsmasq.conf`, `app/infrastructure/compose/ai.yml`,
`app/services/sip-as/ims_sip/{app.py,runtime.py}`,
`app/services/ai-worker/ims_ai/{api.py,runtime.py,interpretation.py,lifecycle.py,recording.py,transcription.py,segmentation.py,utterances.py,settings.py}`,
`app/services/media-adapter/ims_media/{api.py,runtime.py,rtpengine.py,publish.py}`,
`app/services/voice-agent/ims_voice/{api.py,audio.py,runtime.py}`,
`app/tests/unit/{test_phone_sdp.py,test_media_routing.py}`,
`app/tests/integration/{verify-ims.sh,verify-ims-call.sh,verify-5g-ue.sh}`, `scripts/bench_5g.py`,
`docs/{guide-1-ims-core.md,guide-2-ims-ai.md,guide-4-5g-manual.md,guide-5-5g-scripts.md,project-layout.md}`, `CHANGELOG.md`.

Удаляются: `app/services/sip-as/ims_sip/{routing.py,control.py,messages.py,sdp.py}`.

---

### Task 1: Spike — два пустых логических AS в цепочке iFC (go/no-go)

Цель — до любого кода услуг доказать, что запрос с **новым** Call-ID (нога B2BUA),
вернувшийся в S-CSCF с его ISC Route, продолжает цепочку iFC со следующего приоритета.
`spike1.as` — вырожденный B2BUA (меняет Call-ID и From tag), `spike2.as` — прокси с
Record-Route, `as` — прокси (место numbers). Имена `spike1.as.<IMS_DOMAIN>` и
`spike2.as.<IMS_DOMAIN>` уже разрешаются в `SIP_AS_IP`: `address=/as.__IMS_DOMAIN__/`
в dnsmasq покрывает поддомены.

**Files:**
- Create: `app/tests/integration/spike_isc_chain.py`
- Modify (только если spike не проходит, см. шаг 6): `app/infrastructure/vendor/docker_open5gs/scscf/kamailio_scscf.cfg:424`

**Interfaces:**
- Consumes: `provision.read_env()`, `provision.subscribers(settings)`, `provision.PyHSS(settings)`, `provision.upsert(hss, kind, id_field, entry, payload)` из `scripts/provision.py:30-164`.
- Produces: решение GO / GO-с-fallback / NO-GO для задач 7–9; при fallback F1 — замена тела `b2bua.leg_b_routes()` (задача 7).

- [ ] **Step 1: Написать spike-скрипт**

```python
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
```

- [ ] **Step 2: Проверить скрипт offline**

Run: `python3 -c "import ast,sys; ast.parse(open('app/tests/integration/spike_isc_chain.py').read())" && python3 app/tests/integration/spike_isc_chain.py`
Expected: выводится docstring скрипта (нет команды), код возврата 1; синтаксических ошибок нет.

- [ ] **Step 3: Коммит spike-скрипта**

```bash
python3 scripts/check.py
git add app/tests/integration/spike_isc_chain.py
git commit -m "test: ISC chain spike with two empty logical AS"
```

Expected от `check.py`: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 4: Запуск spike на Linux-стенде (выполняет пользователь)**

Стенд запущен (`python3 scripts/start.py`), рабочий каталог — корень репозитория.

```bash
set -a; source app/config/lab.env; set +a
python3 app/tests/integration/spike_isc_chain.py install
# S-CSCF берёт iFC при регистрации: сбросить кэш профиля перезапуском (телефоны
# перерегистрируются сами), затем дождаться Cx.
docker restart lab-scscf && sleep 15
docker stop lab-sip-as
docker run -d --rm --name lab-spike-isc --network "$CORE_NETWORK_NAME" --ip "$SIP_AS_IP" \
  -e SIP_AS_IP -e SIP_AS_PORT -e SCSCF_IP -e SCSCF_SIP_PORT -e IMS_DOMAIN \
  -v "$PWD/app/tests/integration/spike_isc_chain.py:/spike.py:ro" \
  --entrypoint python lab-sip-as /spike.py serve
compose=(docker compose --env-file app/config/lab.env -f docker-compose.yml --profile test)
"${compose[@]}" up -d --no-deps --force-recreate sipue1 sipue2
until docker logs lab-sipue1 2>&1 | grep -q 'Response msg 200/REGISTER' &&
      docker logs lab-sipue2 2>&1 | grep -q 'Response msg 200/REGISTER'; do sleep 1; done
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker exec lab-sipue1 sh -c 'printf "%b" "$1" > /tmp/pjsua-control' _ "m\nsip:${SIPUE2_MSISDN}@${IMS_DOMAIN}\n"
sleep 10
logs=$(docker logs lab-spike-isc 2>&1); echo "$logs"
leg=$(sed -n 's/^SPIKE1 leg_b call_id=\([^ ]*\) for .*/\1/p' <<<"$logs" | tail -1)
a=$(sed -n 's/^SPIKE1 leg_b call_id=[^ ]* for call_id=\(.*\)$/\1/p' <<<"$logs" | tail -1)
verdict() { if "${@:2}"; then echo "PASS: $1"; else echo "FAIL: $1"; fi; }
verdict 'нога B создана spike1' test -n "$leg"
verdict 'нога B прошла spike2 (приоритет 25)' grep -q "^SPIKE2 INVITE call_id=$leg\$" <<<"$logs"
verdict 'нога B прошла as (приоритет 30)' grep -q "^AS INVITE call_id=$leg\$" <<<"$logs"
verdict 'Call-ID звонящего не прошёл дальше spike1' bash -c "! grep -q '^SPIKE2 INVITE call_id=$a\$' <<<\"\$0\"" "$logs"
verdict 'S-CSCF обработал ногу B' bash -c "docker logs lab-scscf --since $since 2>&1 | grep -q 'SCSCF: INVITE .*, $leg)'"
verdict 'SIPUE2 получил INVITE ноги B' bash -c "docker logs lab-sipue2 --since $since 2>&1 | grep -qiE '^(Call-ID|i): *$leg'"
verdict 'SIPUE1 получил 200/INVITE' bash -c "docker logs lab-sipue1 --since $since 2>&1 | grep -q 'Response msg 200/INVITE'"
if grep -q "^SPIKE1 INVITE call_id=$leg\$" <<<"$logs"; then
  echo 'INFO: S-CSCF начал цепочку заново для ноги B (spike1 видел её)'
else
  echo 'INFO: S-CSCF продолжил цепочку со следующего приоритета'
fi
```

Ожидаемые строки журнала `lab-spike-isc` (Call-ID свои):

```text
SPIKE listening udp:<SIP_AS_IP>:5070
SPIKE1 INVITE call_id=<A>
SPIKE1 leg_b call_id=spike-<hex> for call_id=<A>
SPIKE2 INVITE call_id=spike-<hex>
AS INVITE call_id=spike-<hex>
SPIKE1 relayed SIP/2.0 200 OK call_id=<A>
```

Ожидаемый итог: семь строк `PASS: ...` и одна строка `INFO: ...`. ACK звонящего несёт
Call-ID `<A>`, а у SIPUE2 диалог `spike-…`, поэтому через ~32 с SIPUE2 сам пошлёт
BYE по таймауту ACK — для spike это ожидаемо. Если в журнале через 40 с есть
`SPIKE2 BYE call_id=spike-<hex>`, Record-Route логического AS тоже работает (нужно
record AS для BYE); если нет — запись без перевода закроется по
`MEDIA_SESSION_TTL_SECONDS`, это не блокирует GO.

- [ ] **Step 5: Вернуть стенд в исходное состояние (выполняет пользователь)**

```bash
docker rm -f lab-spike-isc
docker start lab-sip-as
python3 app/tests/integration/spike_isc_chain.py restore
# S-CSCF держит spike-iFC в кэше профиля: сбросить перезапуском.
docker restart lab-scscf
"${compose[@]}" rm -sf sipue1 sipue2
```

Шаги 4 и 5 выполняются в одной сессии bash (Step 5 использует `compose` из Step 4).

Expected: `SPIKE iFC removed: SIPUE1 uses default_ifc.xml`.

- [ ] **Step 6: Решение go/no-go**

- **GO** — все семь `PASS`, `INFO: ... продолжил цепочку ...`. Задачи 7–9 без изменений.
- **GO (цепочка заново)** — все семь `PASS`, `INFO: ... начал цепочку заново ...`.
  translate AS пропускает свои ноги (`dialogs.is_own` → `bypass(..., "own_leg")`,
  задача 9), record (20) всё равно видит ногу B. Задачи 7–9 без изменений.
- **Нога B не дошла до spike2/as, но SIPUE2 её получил** (цепочка пропущена) или
  **S-CSCF ответил на ногу B 4xx/5xx** (`SPIKE1 relayed SIP/2.0 4.. / 5..`):
  1. Диагностика S-CSCF: в `kamailio_scscf.cfg` после строки 424 `loose_route();`
     добавить строку
     ```text
     	xnotice("SCSCF ISC: $rm ci=$ci route_uri=$route_uri\n");
     ```
     `docker restart lab-scscf`, повторить шаг 4 и посмотреть
     `docker logs lab-scscf | grep 'SCSCF ISC'`: для ноги B `route_uri` должен
     содержать ISC-метку S-CSCF (`sip:...@scscf.<IMS_DOMAIN>:6060;lr;s=...`). Если
     метки нет — spike потерял Route (ошибка spike, чинить скрипт).
  2. Fallback F1 без правки Kamailio: повторить шаг 4, добавив в `docker run`
     `-e SPIKE_LEG_B_ROUTE=orig`. Нога B идёт в S-CSCF через `sip:orig@` (строка
     435 `kamailio_scscf.cfg`: `$route_uri =~ "sip:orig@.*"` → `route(orig)`,
     цепочка начинается заново, spike1 пропускает `spike-*` как прокси). Если все
     семь `PASS` — **GO с F1**: в задаче 7 тело `leg_b_routes` заменяется на
     ```python
     def leg_b_routes(a_request: str) -> list[str]:
         """F1: S-CSCF начинает цепочку заново; translate пропустит свою ногу B."""
         return [f"<sip:orig@scscf.{runtime.ims_domain}:{runtime.scscf[1]};lr>"]
     ```
     а тест `test_leg_b_returns_to_scscf_with_isc_route` проверяет
     `Route: <sip:orig@scscf.` вместо `Route: <sip:iscmark@`.
  3. Откатить диагностику: `git checkout -- app/infrastructure/vendor/docker_open5gs/scscf/kamailio_scscf.cfg`.
- **NO-GO** — F1 тоже не даёт семи `PASS`. Остановиться, задачи 2+ не начинать,
  вернуться к дизайну (спецификация, раздел «Риск, проверяемый первым»).

---

### Task 2: iFC по профилю абонента из lab.env и DNS логических AS

**Files:**
- Modify: `scripts/provision.py:12-15` (константы), `scripts/provision.py:40-60` (`subscribers`), `scripts/provision.py:166-218` (`provision`, `main`)
- Modify: `app/config/lab.env:62` (после блока SIPUE2 — новый раздел)
- Modify: `app/infrastructure/configs/dns/ims-dnsmasq.conf:24`
- Modify: `app/tests/integration/verify-ims.sh:9`
- Modify: `app/tests/integration/verify-ims-call.sh:2-6,28-35` (SIPUE1 теперь с услугами — обычный вызов идёт от SIPUE2)
- Modify: `scripts/bench_5g.py:290-293` (то же для замера SIP через 5G)
- Test: `app/tests/unit/test_ifc_generation.py`

**Interfaces:**
- Consumes: `read_env`, `subscribers`, `PyHSS`, `upsert`, `ensure_apn`, `ensure_auc` из `scripts/provision.py`.
- Produces:
  - `provision.SERVICES: dict[str, tuple[str, int]]` = `{"translate": ("translate.as", 10), "record": ("record.as", 20)}`
  - `provision.subscriber_profile(settings: dict, prefix: str) -> tuple[list[str], str]`
  - `provision.ifc_xml(settings: dict, services: list[str]) -> str`
  - `provision.install_ifc(name: str, xml: str) -> str` (возвращает `ifc_path`, например `"ifc-UE1.xml"`)
  - элемент `subscribers()` получает ключи `"services"` и `"language"`
  - ключи `lab.env` из Global Constraints (кроме `RECORDING_ANNOUNCEMENT_*` — задача 12)

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_ifc_generation.py`:

```python
"""iFC по профилю абонента из lab.env: приоритеты, правило «*», DefaultHandling, DNS."""

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import provision  # noqa: E402


class FakeHss:
    def __init__(self):
        self.calls = []

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return None

    def find(self, kind, imsi, id_field):
        return None


def rules(xml):
    """(приоритет, хост AS, DefaultHandling, RequestURI) каждого iFC по порядку."""
    result = []
    for ifc in ET.fromstring(xml.encode("utf-8")).iter("InitialFilterCriteria"):
        server = ifc.findtext("ApplicationServer/ServerName")
        result.append(
            (
                int(ifc.findtext("Priority")),
                re.match(r"sip:([^:;]+)", server).group(1),
                ifc.findtext("ApplicationServer/DefaultHandling"),
                ifc.findtext("TriggerPoint/SPT/RequestURI"),
            )
        )
    return result


class IfcGeneration(unittest.TestCase):
    def setUp(self):
        self.settings = provision.read_env()
        self.domain = self.settings["IMS_DOMAIN"]

    def test_translate_record_chain_in_priority_order(self):
        found = rules(provision.ifc_xml(self.settings, ["translate", "record"]))
        domain = self.domain
        self.assertEqual(
            [(priority, host) for priority, host, _, _ in found],
            [
                (10, f"translate.as.{domain}"),
                (15, f"translate.as.{domain}"),
                (20, f"record.as.{domain}"),
                (30, f"as.{domain}"),
                (40, f"smsc.{domain}"),
            ],
        )

    def test_every_rule_continues_session_when_as_is_down(self):
        found = rules(provision.ifc_xml(self.settings, ["translate", "record"]))
        self.assertEqual({handling for _, _, handling, _ in found}, {"0"})

    def test_star_rule_matches_only_prefixed_request_uri(self):
        found = rules(provision.ifc_xml(self.settings, []))
        star = next(ruri for priority, _, _, ruri in found if priority == 15)
        self.assertRegex(f"sip:*1002@{self.domain}", star)
        self.assertRegex("tel:*1002", star)
        self.assertNotRegex(f"sip:1002@{self.domain}", star)

    def test_subscriber_without_services_keeps_star_and_numbers(self):
        found = rules(provision.ifc_xml(self.settings, []))
        self.assertEqual([priority for priority, *_ in found], [15, 30, 40])

    def test_numbers_rule_kept_for_originating_invite(self):
        xml = provision.ifc_xml(self.settings, [])
        server = f"sip:as.{self.domain}:{self.settings['SIP_AS_PORT']};transport=udp"
        self.assertIn(f"<ServerName>{server}</ServerName>", xml)
        numbers = next(
            ifc
            for ifc in ET.fromstring(xml.encode("utf-8")).iter("InitialFilterCriteria")
            if ifc.findtext("Priority") == "30"
        )
        self.assertEqual(numbers.findtext("TriggerPoint/SPT/Method"), "INVITE")
        self.assertEqual(numbers.findtext("TriggerPoint/SPT/SessionCase"), "0")

    def test_identities_stay_pyhss_templates(self):
        xml = provision.ifc_xml(self.settings, [])
        self.assertIn("<PrivateID>{{ iFC_vars['imsi'] }}", xml)
        self.assertIn("<Identity>tel:{{ iFC_vars['msisdn'] }}</Identity>", xml)


class SubscriberProfiles(unittest.TestCase):
    def test_repository_profiles(self):
        entries = {e["name"]: e for e in provision.subscribers(provision.read_env())}
        profile = {name: (e["services"], e["language"]) for name, e in entries.items()}
        self.assertEqual(
            profile,
            {
                "UE1": (["translate", "record"], "ru"),
                "UE2": ([], "en"),
                "SIPUE1": (["translate", "record"], "ru"),
                "SIPUE2": ([], "en"),
            },
        )

    def test_unknown_service_is_rejected_before_hss(self):
        settings = {**provision.read_env(), "SIPUE2_SERVICES": "translate,fax"}
        with self.assertRaisesRegex(ValueError, "SIPUE2_SERVICES: .*fax"):
            provision.subscribers(settings)

    def test_language_defaults_and_validation(self):
        settings = provision.read_env()
        settings.pop("SIPUE2_LANGUAGE")
        entries = {e["name"]: e for e in provision.subscribers(settings)}
        self.assertEqual(entries["SIPUE2"]["language"], settings["DEFAULT_LANGUAGE"])
        with self.assertRaisesRegex(ValueError, "UE1_LANGUAGE=de"):
            provision.subscribers({**provision.read_env(), "UE1_LANGUAGE": "de"})


class Provisioning(unittest.TestCase):
    def test_each_subscriber_gets_own_generated_ifc(self):
        hss = FakeHss()
        settings = provision.read_env()
        with (
            patch.object(provision, "PyHSS", return_value=hss),
            patch.object(provision, "ensure_apn", return_value=1),
            patch.object(provision, "ensure_auc", return_value=2),
            patch.object(
                provision, "install_ifc", side_effect=lambda name, xml: f"ifc-{name}.xml"
            ) as install,
        ):
            provision.provision(settings)
        ims = [payload for _, path, payload in hss.calls if path == "/ims_subscriber/"]
        self.assertEqual(
            [payload["ifc_path"] for payload in ims],
            ["ifc-UE1.xml", "ifc-UE2.xml", "ifc-SIPUE1.xml", "ifc-SIPUE2.xml"],
        )
        generated = {call.args[0]: call.args[1] for call in install.call_args_list}
        self.assertIn(f"record.as.{settings['IMS_DOMAIN']}", generated["SIPUE1"])
        self.assertNotIn("record.as.", generated["SIPUE2"])

    def test_install_writes_next_to_default_template(self):
        with patch.object(provision.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(provision.install_ifc("UE1", "<xml/>"), "ifc-UE1.xml")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["docker", "exec", "-i", "lab-pyhss"])
        self.assertEqual(command[-1], "/pyhss/ifc-UE1.xml")
        self.assertEqual(run.call_args.kwargs["input"], "<xml/>")

    def test_dns_names_point_to_sip_as(self):
        conf = (ROOT / "app/infrastructure/configs/dns/ims-dnsmasq.conf").read_text(
            encoding="utf-8"
        )
        for name in ("translate.as", "record.as"):
            self.assertIn(f"address=/{name}.__IMS_DOMAIN__/__SIP_AS_IP__", conf)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_ifc_generation.py' -v`
Expected: FAIL/ERROR — `AttributeError: module 'provision' has no attribute 'ifc_xml'`, `KeyError: 'services'`.

- [ ] **Step 3: Добавить профили в `lab.env`**

В `app/config/lab.env` сразу после строки `SIPUE2_IMS_AMF=8000` (строка 62) вставить:

```text

# --- Услуги IMS по профилю абонента -----------------------------------------
# scripts/provision.py собирает из этих строк iFC каждого абонента: услуги через
# запятую (translate, record), язык ru или en. «*номер» включает перевод всем.
DEFAULT_LANGUAGE=ru
UE1_SERVICES=translate,record
UE1_LANGUAGE=ru
UE2_SERVICES=
UE2_LANGUAGE=en
SIPUE1_SERVICES=translate,record
SIPUE1_LANGUAGE=ru
SIPUE2_SERVICES=
SIPUE2_LANGUAGE=en
```

- [ ] **Step 4: Реализовать генерацию iFC в `scripts/provision.py`**

После `KEY_FIELDS = ("ki", "opc", "amf")` (строка 15) добавить:

```python
# Услуга: (хост логического AS в SIP AS, приоритет iFC). Номер 15 — «*номер» →
# translate: после translate (10), поэтому нога B без «*» его не включит повторно.
SERVICES = {"translate": ("translate.as", 10), "record": ("record.as", 20)}
STAR_HOST, STAR_PRIORITY = "translate.as", 15
NUMBERS_HOST, NUMBERS_PRIORITY = "as", 30
SMS_PRIORITY = 40  # был 20 в default_ifc.xml; уступил record
LANGUAGES = ("ru", "en")
SESSION_CONTINUED = 0  # DefaultHandling: AS недоступен — звонок идёт без услуги

IFC_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Сгенерировано scripts/provision.py из lab.env; PyHSS подставляет iFC_vars (Jinja2). -->
<IMSSubscription>
    <PrivateID>{{ iFC_vars['imsi'] }}@ims.mnc{{ iFC_vars['mnc'] }}.mcc{{ iFC_vars['mcc'] }}.3gppnetwork.org</PrivateID>
    <ServiceProfile>
        <PublicIdentity>
            <Identity>sip:{{ iFC_vars['msisdn'] }}@ims.mnc{{ iFC_vars['mnc'] }}.mcc{{ iFC_vars['mcc'] }}.3gppnetwork.org</Identity>
            <Extension>
                <IdentityType>0</IdentityType>
                <Extension>
                    <AliasIdentityGroupID>1</AliasIdentityGroupID>
                </Extension>
            </Extension>
        </PublicIdentity>
        <PublicIdentity>
            <Identity>tel:{{ iFC_vars['msisdn'] }}</Identity>
            <Extension>
                <IdentityType>0</IdentityType>
                <Extension>
                    <AliasIdentityGroupID>1</AliasIdentityGroupID>
                </Extension>
            </Extension>
        </PublicIdentity>
        <PublicIdentity>
            <Identity>sip:{{ iFC_vars['imsi'] }}@ims.mnc{{ iFC_vars['mnc'] }}.mcc{{ iFC_vars['mcc'] }}.3gppnetwork.org</Identity>
            <Extension>
                <IdentityType>0</IdentityType>
            </Extension>
        </PublicIdentity>
"""
IFC_TAIL = "    </ServiceProfile>\n</IMSSubscription>\n"


def spt(group, condition, negated=0):
    return (
        "                <SPT>\n"
        f"                    <ConditionNegated>{negated}</ConditionNegated>\n"
        f"                    <Group>{group}</Group>\n"
        f"                    {condition}\n"
        "                </SPT>\n"
    )


ORIGINATING_INVITE = spt(0, "<Method>INVITE</Method>") + spt(1, "<SessionCase>0</SessionCase>")
STAR_SPT = spt(2, r"<RequestURI>^(sip|tel):\*</RequestURI>")
SMS_SPTS = (
    spt(0, "<Method>MESSAGE</Method>")
    + spt(1, "<SIPHeader><Header>Server</Header></SIPHeader>", negated=1)
    + spt(2, "<SessionCase>0</SessionCase>")
)


def criteria(priority, server, triggers):
    return (
        "        <InitialFilterCriteria>\n"
        f"            <Priority>{priority}</Priority>\n"
        "            <TriggerPoint>\n"
        "                <ConditionTypeCNF>1</ConditionTypeCNF>\n"
        f"{triggers}"
        "            </TriggerPoint>\n"
        "            <ApplicationServer>\n"
        f"                <ServerName>{server}</ServerName>\n"
        f"                <DefaultHandling>{SESSION_CONTINUED}</DefaultHandling>\n"
        "            </ApplicationServer>\n"
        "        </InitialFilterCriteria>\n"
    )


def as_server(settings, host):
    return f"sip:{host}.{settings['IMS_DOMAIN']}:{settings['SIP_AS_PORT']};transport=udp"


def ifc_xml(settings, services):
    """iFC абонента: его услуги, «*номер» → translate и numbers — всем, SMS как прежде."""
    rules = [
        (STAR_PRIORITY, STAR_HOST, ORIGINATING_INVITE + STAR_SPT),
        (NUMBERS_PRIORITY, NUMBERS_HOST, ORIGINATING_INVITE),
    ]
    rules += [(SERVICES[name][1], SERVICES[name][0], ORIGINATING_INVITE) for name in services]
    body = "".join(criteria(p, as_server(settings, host), t) for p, host, t in sorted(rules))
    sms = criteria(SMS_PRIORITY, f"sip:smsc.{settings['IMS_DOMAIN']}:5060", SMS_SPTS)
    return IFC_HEAD + body + sms + IFC_TAIL


def subscriber_profile(settings, prefix):
    """Услуги и язык абонента; ошибка в lab.env — до любого запроса к HSS."""
    raw = settings.get(f"{prefix}_SERVICES", "")
    services = [name.strip() for name in raw.split(",") if name.strip()]
    unknown = [name for name in services if name not in SERVICES]
    if unknown:
        raise ValueError(
            f"{prefix}_SERVICES: неизвестные услуги {', '.join(unknown)}; "
            f"допустимы {', '.join(SERVICES)}"
        )
    language = settings.get(f"{prefix}_LANGUAGE") or settings.get("DEFAULT_LANGUAGE") or "ru"
    if language not in LANGUAGES:
        raise ValueError(f"{prefix}_LANGUAGE={language}: допустимы {', '.join(LANGUAGES)}")
    return services, language


def install_ifc(name, xml):
    """Кладёт iFC рядом с default_ifc.xml в lab-pyhss; start.py пересоздаёт его каждый запуск."""
    path = f"/pyhss/ifc-{name}.xml"
    result = subprocess.run(
        ["docker", "exec", "-i", "lab-pyhss", "sh", "-c", 'cat > "$1"', "_", path],
        input=xml,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"{name}: не удалось записать {path} в lab-pyhss")
    return f"ifc-{name}.xml"
```

В `subscribers()` (строки 54–57) после цикла проверки ключей, перед `result.append(entry)`,
добавить строку:

```python
        entry["services"], entry["language"] = subscriber_profile(settings, prefix)
```

В `provision()` заменить комментарий и словарь `ims` (строки 189–201):

```python
        # iFC собирается из услуг абонента в lab.env и кладётся в lab-pyhss; S-CSCF
        # получает его при следующей регистрации абонента (SAR).
        ims = {
            "imsi": entry["imsi"],
            "msisdn": entry["msisdn"],
            "ifc_path": install_ifc(entry["name"], ifc_xml(settings, entry["services"])),
            "sh_template_path": "default_sh_user_data.xml",
            "scscf": f"sip:scscf.{domain}:{settings['SCSCF_SIP_PORT']}",
            "scscf_realm": domain,
            "scscf_peer": f"scscf.{domain}",
            "pcscf_realm": domain,
            "pcscf_peer": f"pcscf.{domain}",
        }
```

В `main()` заменить строку dry-run (строка 216):

```python
            services = ",".join(entry["services"]) or "-"
            print(
                f"{entry['name']}: IMSI {entry['imsi']}, MSISDN {entry['msisdn']}, "
                f"услуги {services}, язык {entry['language']} (dry-run)"
            )
```

- [ ] **Step 5: DNS-имена логических AS**

В `app/infrastructure/configs/dns/ims-dnsmasq.conf` после строки 24
`address=/as.__IMS_DOMAIN__/__SIP_AS_IP__` добавить:

```text
# Логические AS одного процесса SIP AS (iFC приоритет 10/15 и 20).
address=/translate.as.__IMS_DOMAIN__/__SIP_AS_IP__
address=/record.as.__IMS_DOMAIN__/__SIP_AS_IP__
```

В `app/tests/integration/verify-ims.sh` строку 9 заменить на:

```bash
for entry in "pcscf $PCSCF_IP" "icscf $ICSCF_IP" "scscf $SCSCF_IP" "hss $PYHSS_IP" "as $SIP_AS_IP" "translate.as $SIP_AS_IP" "record.as $SIP_AS_IP"; do
```

- [ ] **Step 6: Обычный вызов в проверках — от абонента без услуг**

SIPUE1 и UE1 теперь подписаны на `translate,record`, поэтому вызов к собеседнику с
другим языком становится переводимым. Проверки «обычного» звонка звонят от SIPUE2/UE2.

`app/tests/integration/verify-ims-call.sh`, строки 2–6 заменить на:

```bash
# Шаги 4–6 обычного вызова: INVITE lab-sipue2 -> lab-sipue1 через P/S-CSCF (у SIPUE2
# нет услуг в lab.env, у SIPUE1 — translate,record только для исходящих), S-CSCF
# вызывает SIP AS по iFC, RTPengine держит медиа обеих сторон, Media Adapter
# передаёт звук в AI Worker. При остановленном AI Worker RTP продолжается
# (fail-open). На время проверки AI Worker останавливается: не запускайте во
# время чужих звонков через AI.
```

строки 28–35 заменить на:

```bash
pjsua lab-sipue2 "m\nsip:${SIPUE1_IMSI}@${IMS_DOMAIN}\n"
call_id=$(wait_call_id '.*AS observed INVITE call_id=\([^ ]*\).*' "$since")
sleep 4

caller_logs=$(docker logs lab-sipue2 --since "$since" 2>&1)
callee_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
check 'вызывающий получил 200/INVITE' grep -q 'Response msg 200/INVITE' <<<"$caller_logs"
check 'вызываемый получил INVITE через IMS' grep -q 'Request msg INVITE' <<<"$callee_logs"
```

`scripts/bench_5g.py`, строки 290–293 заменить на:

```python
    # UE1 подписан на translate,record: замер SIP без услуг — вызов UE2 -> UE1.
    caller = clients[1]
    for _ in range(rounds):
        offset = caller.mark()
        caller.send(f"m\nsip:{settings['UE1_MSISDN']}@{settings['IMS_DOMAIN']}\n")
```

- [ ] **Step 7: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_ifc_generation.py' -v`
Expected: `Ran 12 tests` … `OK`.

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit`
Expected: `OK` (включая `test_subscriber_provisioning.py`).

- [ ] **Step 8: Коммит**

```bash
python3 scripts/check.py
git add scripts/provision.py app/config/lab.env app/infrastructure/configs/dns/ims-dnsmasq.conf \
  app/tests/integration/verify-ims.sh app/tests/integration/verify-ims-call.sh scripts/bench_5g.py \
  app/tests/unit/test_ifc_generation.py
git commit -m "feat: per-subscriber iFC from lab.env and DNS names for logical AS"
```

- [ ] **Step 9: Проверка на стенде (выполняет пользователь)**

До задачи 12 SIP AS ещё не знает `translate.as`/`record.as`: звонки SIPUE1 и UE1 с
новым iFC не проверяйте, только provisioning, DNS и регистрацию.

```bash
python3 scripts/provision.py            # dry-run
python3 scripts/start.py --ims-only
docker restart lab-dns
bash app/tests/integration/verify-ims.sh
docker exec lab-pyhss grep -c 'InitialFilterCriteria>' /pyhss/ifc-SIPUE1.xml
```

Expected: в dry-run строки вида `SIPUE1: IMSI ..., MSISDN 1101, услуги translate,record, язык ru (dry-run)`;
`PASS: dnsmasq: translate.as.<IMS_DOMAIN> -> <SIP_AS_IP>` и `PASS: dnsmasq: record.as.<IMS_DOMAIN> -> <SIP_AS_IP>`;
`PASS: S-CSCF: SAA успешен (профиль и iFC)`; итог `IMS DNS + HSS + REGISTRATION: PASS`;
`grep -c` печатает `10` (пять правил × открывающий и закрывающий тег).

---

### Task 3: SIP AS — перенос в `core/` и `services/numbers.py` без изменения поведения

Сначала фиксируется нынешнее поведение (характеризационные тесты на старом коде),
затем код раскладывается по модулям. Номера 1003–1006, observe и прокси не меняются.

**Files:**
- Create: `app/tests/unit/sip_fakes.py`, `app/tests/unit/test_sip_as_numbers.py`
- Create: `app/services/sip-as/ims_sip/core/__init__.py`, `core/sip.py`, `core/transport.py`, `core/sdp.py`, `core/mrf.py`, `core/proxy.py`, `core/dispatch.py`
- Create: `app/services/sip-as/ims_sip/services/__init__.py`, `services/numbers.py`
- Modify: `app/services/sip-as/ims_sip/app.py:4`
- Modify: `app/tests/unit/test_phone_sdp.py:9-11`
- Modify: `docs/guide-2-ims-ai.md:240,246`, `docs/project-layout.md:57`
- Delete: `app/services/sip-as/ims_sip/{routing.py,control.py,messages.py,sdp.py}`
- Test: `app/tests/unit/test_sip_as_numbers.py`, `app/tests/unit/test_phone_sdp.py`

**Interfaces:**
- Consumes: `ims_sip.runtime` (как есть), `lab_common.http.request_json`.
- Produces:
  - `sip_fakes`: `ENV: dict`, `DOMAIN: str`, `SCSCF: tuple[str, int]`, `RTP_IP: str`, `RTP_A: int`, `RTP_B: int`, `CALLER: str`, `CALLEE: str`, `load_sip_as() -> module`, `FakeHttp` (`calls`, `fail: set[str]`, `voice_calls: dict`, `posted(fragment) -> list[dict]`, `deleted(fragment) -> list[str]`), `SyncThread`, `STATE: tuple[str, ...]`, `reset_state(runtime)`, `SipCase` (`route_request`, `route_response`, `runtime`, `http`, `sent() -> list[tuple[str, tuple]]`, `statuses() -> list[int]`, `requests(method) -> list[str]`, `log() -> str`), `sdp(ip, port) -> str`, `invite(target, call_id="call-a", *, route_host="as", ip=RTP_IP, port=RTP_A, branch="z9hG4bK-a1", caller=CALLER, from_tag="fa1", served=None, to_tag="", compact=False) -> str`, `request(method, call_id, *, uri, from_user, from_tag, to_user, to_tag="", cseq=2, branch="z9hG4bK-r1", route_host=None, body="") -> str`, `response(req, status, reason, *, to_tag="", body="", contact="", record_routes=()) -> str`, `to_tag_of(message) -> str`
  - `core.sip`: `header(message, name) -> str`, `all_headers(message, long_name, compact_name=None) -> list[str]`, `request_method(message) -> str`, `message_call_id(message) -> str`, `local_tag(call_id) -> str`, `transaction_branch(message) -> str`
  - `core.transport`: `local_response(request, status, reason, body="", to_tag="", contact_user=None) -> str`, `send(message: str, peer: tuple[str, int]) -> None`, `send_local_response(request, peer, status_code, reason, *, body="", to_tag="", contact_user="") -> None`
  - `core.sdp`: `accepts_pcmu(message) -> bool`, `offered_media_endpoint(message) -> tuple[str, int] | None`
  - `core.mrf`: `best_effort(method, url, payload=None)`, `notify_adapter(message, service_mode="observe", rtpengine_port=None)`, `stop_adapter(call_id)`, `notify_voice(call_id, remote_ip, remote_port, service_mode)`, `stop_voice(call_id)`, `media_is_anchored(offered_ip, offered_port) -> bool`, `voice_agent_sdp() -> str`
  - `core.proxy`: `build_forwarded_request(message, branch) -> str`, `forward(message, peer) -> None`, `relay_response(message) -> None`
  - `core.dispatch`: `route_request(message, peer) -> None`, `route_response(message) -> None`
  - `services.numbers`: `HOST = "as"`, `handle(message, peer) -> None`

- [ ] **Step 1: Написать фейки SIP AS**

`app/tests/unit/sip_fakes.py`:

```python
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
RTP_B = int(ENV["RTPENGINE_PORT_MIN"]) + 200
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
```

- [ ] **Step 2: Написать характеризационные тесты numbers**

`app/tests/unit/test_sip_as_numbers.py`:

```python
"""Характеризация numbers AS: 1003–1006, observe и прокси не меняются при переносе в core/."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    ENV,
    RTP_A,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    request,
    response,
    to_tag_of,
)

OTHER_PEER = ("198.51.100.1", 6060)


class ServiceNumbers(SipCase):
    def test_service_number_terminates_on_voice_agent(self):
        self.route_request(invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-1"), SCSCF)
        self.assertEqual(self.statuses(), [100, 200])
        answer = self.sent()[-1][0]
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", answer)
        self.assertIn(f"Contact: <sip:{ENV['VOICE_AGENT_SIP_USER']}@", answer)
        self.assertEqual(
            self.http.posted("voice.test/calls"),
            [
                {
                    "call_id": "num-1",
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_A,
                    "service_mode": "translate",
                }
            ],
        )
        session = self.http.posted("media.test/sessions")[0]
        self.assertEqual((session["service_mode"], session["rtpengine_port"]), ("translate", RTP_A))
        self.assertIn(
            "AS terminated INVITE for voice agent call_id=num-1 service=translate", self.log()
        )

    def test_each_service_number_keeps_its_mode(self):
        cases = {
            "VOICE_TRANSCRIBER_MSISDN": "transcribe",
            "VOICE_INTERPRETER_RU_MSISDN": "interpret_ru",
            "VOICE_INTERPRETER_EN_MSISDN": "interpret_en",
            "VOICE_TRANSCRIBER_SIP_USER": "transcribe",
        }
        for key, mode in cases.items():
            with self.subTest(key=key):
                self.route_request(invite(ENV[key], f"num-{key.lower()}"), SCSCF)
                self.assertEqual(self.http.posted("voice.test/calls")[-1]["service_mode"], mode)

    def test_unanchored_media_is_rejected(self):
        message = invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-2", ip="198.51.100.7")
        self.route_request(message, SCSCF)
        self.assertEqual(self.statuses(), [100, 488])
        self.assertEqual(self.http.posted("voice.test/calls"), [])
        self.assertIn("AS rejected unanchored media call_id=num-2", self.log())

    def test_voice_agent_down_answers_503(self):
        self.http.fail.add("voice.test")
        self.route_request(invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-3"), SCSCF)
        self.assertEqual(self.statuses(), [100, 503])
        self.assertIn("AS voice unavailable call_id=num-3", self.log())

    def test_bye_ends_agent_call(self):
        self.route_request(invite(ENV["VOICE_TRANSLATOR_MSISDN"], "num-4"), SCSCF)
        tag = to_tag_of(self.sent()[-1][0])
        user = ENV["VOICE_AGENT_SIP_USER"]
        bye = request(
            "BYE",
            "num-4",
            uri=f"sip:{user}@{ENV['SIP_AS_IP']}:{ENV['SIP_AS_PORT']}",
            from_user=CALLER,
            from_tag="fa1",
            to_user=ENV["VOICE_TRANSLATOR_MSISDN"],
            to_tag=tag,
        )
        self.route_request(bye, SCSCF)
        self.assertEqual(self.statuses()[-1], 200)
        self.assertEqual(len(self.http.deleted("voice.test/calls/num-4")), 1)
        self.assertEqual(len(self.http.deleted("media.test/sessions/num-4")), 1)
        self.assertEqual(self.runtime.agent_calls, {})
        self.assertIn("AS ended voice agent call_id=num-4 method=BYE", self.log())


class ProxiedCalls(SipCase):
    def test_plain_call_is_proxied_and_observed(self):
        self.route_request(invite(CALLEE, "plain-1"), OTHER_PEER)
        [(message, destination)] = self.sent()
        self.assertEqual(destination, SCSCF)
        self.assertTrue(message.startswith(f"INVITE sip:{CALLEE}@"))
        self.assertIn("branch=z9hG4bK-as-z9hG4bK-a1", message)
        route = re.search(r"(?m)^Route: (.+)$", message).group(1)
        self.assertTrue(route.startswith("<sip:iscmark@"))
        self.assertEqual(self.http.posted("media.test/sessions")[0]["service_mode"], "observe")
        self.assertIn("AS observed INVITE call_id=plain-1", self.log())

    def test_response_returns_to_original_peer_without_own_via(self):
        self.route_request(invite(CALLEE, "plain-2"), OTHER_PEER)
        forwarded = self.sent()[0][0]
        self.runtime.sock.reset_mock()
        self.route_response(response(forwarded, 180, "Ringing", to_tag="tb"))
        [(message, destination)] = self.sent()
        self.assertEqual(destination, OTHER_PEER)
        self.assertNotIn("z9hG4bK-as-", message)
        self.assertIn("branch=z9hG4bK-a1", message)

    def test_response_without_own_via_is_dropped(self):
        self.route_response(response(invite(CALLEE, "plain-3"), 200, "OK", to_tag="tb"))
        self.assertEqual(self.sent(), [])
        self.assertIn("AS dropped response without own Via", self.log())

    def test_compact_form_request_is_proxied(self):
        self.route_request(invite(CALLEE, "plain-c", compact=True), OTHER_PEER)
        self.assertEqual(len(self.requests("INVITE")), 1)
        self.assertIn("AS observed INVITE call_id=plain-c", self.log())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Запустить характеризацию на старом коде — проходит**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_numbers.py' -v`
Expected: `Ran 9 tests` … `OK` (тесты фиксируют нынешнее поведение `routing.py`; падение
здесь — ошибка в фейках, а не в коде: исправить `sip_fakes.py`, код не трогать).

- [ ] **Step 4: Перевести `test_phone_sdp.py` на новый путь — падает**

В `app/tests/unit/test_phone_sdp.py` строки 9–11 заменить на:

```python
SPEC = importlib.util.spec_from_file_location(
    "phone_sdp", ROOT / "app/services/sip-as/ims_sip/core/sdp.py"
)
```

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_phone_sdp.py' -v`
Expected: ERROR — `FileNotFoundError: ... ims_sip/core/sdp.py`.

- [ ] **Step 5: Создать `core/`**

`app/services/sip-as/ims_sip/core/__init__.py`:

```python
"""SIP-ядро SIP AS: разбор, транспорт, прокси, B2BUA, MRF и выбор логического AS."""
```

`app/services/sip-as/ims_sip/core/sip.py`:

```python
"""Разбор SIP без состояния: заголовки (полные и компактные имена), tag, Route, CSeq."""

import hashlib
import re
import time


def header(message: str, name: str) -> str:
    match = re.search(rf"(?im)^{re.escape(name)}\s*:\s*(.+)$", message)
    return match.group(1).strip() if match else ""


def all_headers(message: str, long_name: str, compact_name: str | None = None) -> list[str]:
    names = re.escape(long_name)
    if compact_name:
        names += "|" + re.escape(compact_name)
    # ``.`` захватывает и CR строки CRLF; оставленный, он дал бы ``\r\r\n`` в
    # локальном ответе, и Kamailio отверг бы обязательные заголовки.
    return [line.rstrip("\r") for line in re.findall(rf"(?im)^((?:{names})\s*:\s*.+)$", message)]


def request_method(message: str) -> str:
    return message.split("\r\n", 1)[0].split(" ", 1)[0]


def message_call_id(message: str) -> str:
    return header(message, "Call-ID") or header(message, "i")


def local_tag(call_id: str) -> str:
    """Детерминированный tag позволяет одинаково отвечать на retransmit."""
    return hashlib.sha256(call_id.encode()).hexdigest()[:16]


def transaction_branch(message: str) -> str:
    """Поддержать полное и компактное имя SIP-заголовка Via."""
    branch_match = re.search(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=([^;\s]+)", message)
    return branch_match.group(1) if branch_match else str(time.time_ns())
```

`app/services/sip-as/ims_sip/core/transport.py`:

```python
"""UDP-отправка и локальные SIP-ответы логических AS."""

from .. import runtime
from .sip import all_headers, header, message_call_id


def local_response(request, status, reason, body="", to_tag="", contact_user=None):
    lines = [f"SIP/2.0 {status} {reason}"]
    lines.extend(all_headers(request, "Via", "v"))
    lines.extend(all_headers(request, "Record-Route"))
    from_value = header(request, "From") or header(request, "f")
    to_value = header(request, "To") or header(request, "t")
    if to_tag and ";tag=" not in to_value:
        to_value += f";tag={to_tag}"
    lines += [
        f"From: {from_value}",
        f"To: {to_value}",
        f"Call-ID: {message_call_id(request)}",
        f"CSeq: {header(request, 'CSeq')}",
    ]
    if status == 200 and request.startswith("INVITE "):
        user = contact_user or runtime.voice_user
        lines += [
            f"Contact: <sip:{user}@{runtime.bind_ip}:{runtime.bind_port};transport=udp>",
            "Content-Type: application/sdp",
        ]
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def send(message: str, peer: tuple[str, int]) -> None:
    runtime.sock.sendto(message.encode(), peer)


def send_local_response(
    request: str,
    peer: tuple[str, int],
    status_code: int,
    reason: str,
    *,
    body: str = "",
    to_tag: str = "",
    contact_user: str = "",
) -> None:
    send(local_response(request, status_code, reason, body, to_tag, contact_user), peer)
```

`app/services/sip-as/ims_sip/core/sdp.py` (без импорта пакета: `test_phone_sdp.py`
грузит файл по пути):

```python
"""Допуск медиа-контракта PCMU на границе AI-услуг и адрес RTP из SDP."""

import ipaddress
import re


def accepts_pcmu(message: str) -> bool:
    """Reject offers the fixed PT=0 answer cannot satisfy, before allocating RTP.

    Phones may offer only AMR. A relay address alone is not proof that a
    transcoder has inserted PCMU. Inspect SDP, never SIP headers or video PTs.
    Multiple media streams and required QoS preconditions are not implemented.
    """
    headers, separator, body = message.partition("\r\n\r\n")
    if not separator:
        return False
    content_type = re.search(r"(?im)^(?:Content-Type|c):\s*([^;\r\n]+)", headers)
    if not content_type or content_type[1].strip().lower() != "application/sdp":
        return False
    required = re.findall(r"(?im)^Require:\s*([^\r\n]+)", headers)
    if any(
        token.strip().lower() in {"precondition", "100rel"}
        for value in required
        for token in value.split(",")
    ):
        return False
    lines = body.splitlines()
    media = [line.split() for line in lines if line.startswith("m=")]
    if len(media) != 1:
        return False
    audio = media[0]
    if len(audio) < 4 or audio[0] != "m=audio" or audio[2] != "RTP/AVP":
        return False
    if not audio[1].isdigit() or not 0 < int(audio[1]) <= 65535 or "0" not in audio[3:]:
        return False
    # Static PT 0 implies PCMU/8000/1; an explicit conflicting map is invalid.
    maps = re.findall(r"(?im)^a=rtpmap:0\s+([^\r\n]+)", body)
    if any(value.strip().upper() not in {"PCMU/8000", "PCMU/8000/1"} for value in maps):
        return False
    if any(line.lower() in {"a=inactive", "a=sendonly", "a=recvonly"} for line in lines):
        return False
    return not re.search(r"(?im)^a=des:qos\s+mandatory\b", body)


def offered_media_endpoint(message: str) -> tuple[str, int] | None:
    """Извлечь IPv4 и RTP-порт из SDP offer или answer."""
    connection_match = re.search(r"(?im)^c=IN IP4 ([^\s]+)", message)
    media_match = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
    if connection_match is None or media_match is None:
        return None
    try:
        offered_ip = str(ipaddress.ip_address(connection_match.group(1)))
        offered_port = int(media_match.group(1))
    except ValueError:
        return None
    return offered_ip, offered_port
```

`app/services/sip-as/ims_sip/core/mrf.py`:

```python
"""API MRF: Voice Agent (озвучка в ногу) и Media Adapter (поток на распознавание).

Ошибка наблюдения не прерывает звонок; привязка ноги к Voice Agent обязательна.
"""

import re
import time
from urllib.parse import quote

from lab_common.http import request_json

from .. import runtime
from .sip import message_call_id


def best_effort(method, url, payload=None):
    """Используется для необязательного наблюдения и идемпотентной очистки."""
    try:
        request_json(method, url, payload=payload, token=runtime.control_token, timeout=1)
    except Exception as exc:
        print(f"AS service unavailable (call continues) type={type(exc).__name__}", flush=True)


def notify_adapter(message, service_mode="observe", rtpengine_port=None):
    if rtpengine_port is None:
        media = re.search(r"(?im)^m=audio (\d+)\s+RTP/AVP", message)
        rtpengine_port = int(media.group(1)) if media else None
    best_effort(
        "POST",
        runtime.adapter_url,
        {
            "call_id": message_call_id(message),
            "observed_at": time.time(),
            "service_mode": service_mode,
            "rtpengine_port": rtpengine_port,
        },
    )


def stop_adapter(call_id):
    best_effort("DELETE", f"{runtime.adapter_url}/{quote(call_id, safe='')}")


def notify_voice(call_id, remote_ip, remote_port, service_mode):
    # Для TERMINATE-звонка голосовой сервис обязателен: ошибка возвращается SIP-слою.
    request_json(
        "POST",
        runtime.voice_url,
        token=runtime.control_token,
        payload={
            "call_id": call_id,
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "service_mode": service_mode,
        },
    )


def stop_voice(call_id):
    best_effort("DELETE", f"{runtime.voice_url}/{quote(call_id, safe='')}")


def media_is_anchored(offered_ip: str, offered_port: int) -> bool:
    """AI Agent принимает RTP только от настроенного пула RTPengine."""
    return (
        offered_ip == runtime.rtpengine_ip
        and runtime.rtp_port_min <= offered_port <= runtime.rtp_port_max
    )


def voice_agent_sdp() -> str:
    """Сформировать минимальный ответ для единственного кодека PCMU/8000."""
    return (
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
```

`app/services/sip-as/ims_sip/core/proxy.py`:

```python
"""Прокси-путь логического AS: свой Via, снятие своего Route, возврат ответа по Via."""

import re

from .. import runtime
from .sip import transaction_branch
from .transport import send

OWN_ROUTE = re.compile(r"(?im)^(Route\s*:\s*)<sip:as\.[^>]+>\s*,\s*")
OWN_VIA = re.compile(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-([^;\s]+)\r\n")


def build_forwarded_request(message: str, branch: str) -> str:
    request_line, remaining_headers = message.split("\r\n", 1)
    own_via = (
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    )
    # Поглощается только Route текущего AS. Следующий ISC Route возвращает
    # запрос в S-CSCF, где продолжается обычная маршрутизация.
    remaining_headers = OWN_ROUTE.sub(r"\1", remaining_headers, count=1)
    return request_line + "\r\n" + own_via + remaining_headers


def forward(message: str, peer: tuple[str, int]) -> None:
    """Вернуть запрос в S-CSCF; ответ найдёт отправителя по branch своего Via."""
    branch = transaction_branch(message)
    runtime.transactions[branch] = peer
    send(build_forwarded_request(message, branch), runtime.scscf)


def relay_response(message: str) -> None:
    """Удалить собственный Via и вернуть ответ исходному SIP peer."""
    via_match = OWN_VIA.search(message)
    if via_match is None:
        print(f"AS dropped response without own Via: {message.splitlines()[0]}", flush=True)
        return
    branch = via_match.group(1)
    destination_peer = runtime.transactions.get(branch)
    if destination_peer is None:
        print(f"AS dropped response for unknown transaction {branch}", flush=True)
        return
    print(
        f"AS relayed response {message.splitlines()[0]} "
        f"to {destination_peer[0]}:{destination_peer[1]}",
        flush=True,
    )
    send(OWN_VIA.sub("", message, count=1), destination_peer)
```

`app/services/sip-as/ims_sip/core/dispatch.py`:

```python
"""Вход SIP AS: запрос — логическому AS, ответ — по своему Via."""

from ..services import numbers
from .proxy import relay_response


def route_request(message: str, peer: tuple[str, int]) -> None:
    numbers.handle(message, peer)


def route_response(message: str) -> None:
    relay_response(message)
```

- [ ] **Step 6: Создать `services/` и перенести numbers**

`app/services/sip-as/ims_sip/services/__init__.py`:

```python
"""Логические AS одного процесса SIP AS.

Модуль услуги объявляет HOST — имя логического AS до ``.<IMS_DOMAIN>`` (из него
S-CSCF строит Route по iFC) — и handle(message, peer) для запросов с этим Route.
Услуга-B2BUA (translate) реализует on_invite(message, peer), on_answer(call,
response) -> bool и on_bye(call); услуга-прокси (record) — on_invite(message, peer),
on_answer(response) и on_bye(message, peer). Транзакции, Via, Route, ответы и
освобождение MRF делает core.
"""
```

`app/services/sip-as/ims_sip/services/numbers.py`:

```python
"""numbers AS: 1003–1006 завершаются на Voice Agent, остальные вызовы — прокси с observe."""

import re
import threading

from .. import runtime
from ..core.mrf import (
    media_is_anchored,
    notify_adapter,
    notify_voice,
    stop_adapter,
    stop_voice,
    voice_agent_sdp,
)
from ..core.proxy import forward
from ..core.sdp import accepts_pcmu, offered_media_endpoint
from ..core.sip import local_tag, message_call_id, request_method
from ..core.transport import send_local_response

HOST = "as"


def start_agent_call(message, call_id, offered_ip, offered_port, service_mode, tag) -> bool:
    """Создать Voice/Media состояние один раз; INVITE может повторяться."""
    if call_id in runtime.agent_calls:
        return True
    try:
        notify_voice(call_id, offered_ip, offered_port, service_mode)
        runtime.agent_calls[call_id] = {
            "tag": tag,
            "service_mode": service_mode,
            "rtpengine_port": offered_port,
        }
        # Наблюдение не задерживает SIP-ответ и может отказать независимо.
        threading.Thread(
            target=notify_adapter, args=(message, service_mode, offered_port), daemon=True
        ).start()
        return True
    except Exception as error:
        print(f"AS voice unavailable call_id={call_id} type={type(error).__name__}", flush=True)
        return False


def accept_agent_invite(message, peer, call_id, service_mode, tag) -> None:
    send_local_response(message, peer, 100, "Trying")
    media_endpoint = offered_media_endpoint(message)
    if media_endpoint is None or not accepts_pcmu(message):
        send_local_response(message, peer, 488, "Not Acceptable Here", to_tag=tag)
        return
    offered_ip, offered_port = media_endpoint
    # P-CSCF обязан заякорить offer до iFC. Иначе SIP-абонент мог бы заставить
    # Voice Agent отправлять RTP на произвольный адрес (media SSRF/amplification).
    if not media_is_anchored(offered_ip, offered_port):
        print(f"AS rejected unanchored media call_id={call_id}", flush=True)
        send_local_response(message, peer, 488, "Media Must Be Anchored", to_tag=tag)
        return
    if not start_agent_call(message, call_id, offered_ip, offered_port, service_mode, tag):
        send_local_response(message, peer, 503, "Voice Agent Unavailable", to_tag=tag)
        return
    send_local_response(
        message,
        peer,
        200,
        "OK",
        body=voice_agent_sdp(),
        to_tag=tag,
        contact_user=runtime.service_users[service_mode],
    )
    print(
        f"AS terminated INVITE for voice agent call_id={call_id} service={service_mode}",
        flush=True,
    )


def end_agent_call(message, peer, call_id, method, fallback_tag) -> None:
    call = runtime.agent_calls.get(call_id, {})
    send_local_response(message, peer, 200, "OK", to_tag=call.get("tag", fallback_tag))
    runtime.agent_calls.pop(call_id, None)
    # Очистка вспомогательных сервисов не задерживает SIP 200 OK.
    threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
    threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)


def terminate_for_agent(message, peer, service_mode) -> None:
    """Обработать локально один запрос диалога голосового сервиса."""
    method = request_method(message)
    call_id = message_call_id(message)
    tag = local_tag(call_id)
    if method == "INVITE":
        accept_agent_invite(message, peer, call_id, service_mode, tag)
    elif method == "ACK":
        print(f"AS received ACK for voice agent call_id={call_id}", flush=True)
    elif method in {"BYE", "CANCEL"}:
        end_agent_call(message, peer, call_id, method, tag)


def service_mode_for_request(request_line: str, call_id: str) -> str | None:
    """Сначала продолжить известный диалог, затем проверить номер услуги."""
    active_mode = runtime.agent_calls.get(call_id, {}).get("service_mode")
    if active_mode:
        return active_mode
    target_match = re.search(r"^[A-Z]+\s+sip:([^@; ]+)", request_line)
    if target_match:
        return runtime.service_targets.get(target_match.group(1))
    return None


def observe_proxied_dialog(message: str, request_line: str, call_id: str) -> None:
    """Сообщить Media Adapter о начале/завершении обычного звонка."""
    if request_line.startswith("INVITE "):
        print(f"AS observed INVITE call_id={call_id}", flush=True)
        threading.Thread(target=notify_adapter, args=(message, "observe"), daemon=True).start()
    elif request_line.startswith(("BYE ", "CANCEL ")):
        threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()


def handle(message: str, peer: tuple[str, int]) -> None:
    """Номер услуги — завершить на Voice Agent, иначе наблюдать и вернуть в S-CSCF."""
    request_line = message.split("\r\n", 1)[0]
    call_id = message_call_id(message)
    service_mode = service_mode_for_request(request_line, call_id)
    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return
    observe_proxied_dialog(message, request_line, call_id)
    forward(message, peer)
```

- [ ] **Step 7: Переключить точку входа и удалить старые модули**

`app/services/sip-as/ims_sip/app.py`, строку 4 заменить на:

```python
from .core.dispatch import route_request, route_response
```

```bash
git rm app/services/sip-as/ims_sip/routing.py app/services/sip-as/ims_sip/control.py \
  app/services/sip-as/ims_sip/messages.py app/services/sip-as/ims_sip/sdp.py
```

- [ ] **Step 8: Исправить ссылки в документации**

`docs/guide-2-ims-ai.md`, строку 240 заменить на:

```markdown
SIP AS ([core/dispatch.py](../app/services/sip-as/ims_sip/core/dispatch.py)) сравнивает номер
```

строку 246 заменить на:

```markdown
1. `sip-as/ims_sip/core/dispatch.py` — SIP и выбор логического AS (`services/`).
```

`docs/project-layout.md`, строку 57 заменить на:

```markdown
SIP AS — `app/services/sip-as/ims_sip/` (`core/` — SIP, прокси и MRF, `services/` — логические AS, `core/sdp.py` —
```

- [ ] **Step 9: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_numbers.py' -v`
Expected: `Ran 9 tests` … `OK`.

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_phone_sdp.py' -v`
Expected: `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 10: Коммит**

```bash
git add app/tests/unit/sip_fakes.py app/tests/unit/test_sip_as_numbers.py app/tests/unit/test_phone_sdp.py \
  app/services/sip-as/ims_sip/app.py app/services/sip-as/ims_sip/core app/services/sip-as/ims_sip/services \
  docs/guide-2-ims-ai.md docs/project-layout.md
git commit -m "refactor: split SIP AS into core and numbers service"
```

---

### Task 4: Диспетчер по Route, языки абонентов, свои диалоги

**Files:**
- Create: `app/services/sip-as/ims_sip/core/dialogs.py`, `app/services/sip-as/ims_sip/core/subscribers.py`
- Modify: `app/services/sip-as/ims_sip/core/sip.py` (в конец файла), `app/services/sip-as/ims_sip/core/proxy.py` (константы `OWN_ROUTE` и `build_forwarded_request`), `app/services/sip-as/ims_sip/core/dispatch.py` (весь файл), `app/services/sip-as/ims_sip/services/numbers.py` (`handle`, импорты), `app/services/sip-as/ims_sip/runtime.py` (после `service_users`)
- Test: `app/tests/unit/test_sip_as_dispatch.py`

**Interfaces:**
- Consumes: `core.sip.header`, `core.sip.all_headers`, `core.proxy.forward`, `services.numbers` (задача 3).
- Produces:
  - `core.sip.COMPACT: dict[str, str]`, `core.sip.value_of(message, name) -> str`, `core.sip.request_uri(message) -> str`, `core.sip.route_values(message, name="Route") -> list[str]`, `core.sip.top_route_host(message) -> str`
  - `core.subscribers.PROFILES`, `LANGUAGES`, `language_table(environ) -> dict[str, str]`, `uri_user(value) -> str`, `served_user(message) -> str`, `target_user(message) -> str`, `language_for(user, table, default) -> str`
  - `core.dialogs.new_call_id() -> str` (`b2b-<24 hex>`), `is_own(call_id) -> bool`, `forget(call_id) -> None`, `mark_record(call_id) -> None`, `is_marked_record(call_id) -> bool`
  - `core.proxy.OWN_ROUTE`, `core.proxy.OWN_ROUTE_LINE`
  - `core.dispatch.SERVICES: tuple`, `core.dispatch.service_for(message) -> module | None`
  - `runtime.ims_domain: str`, `runtime.languages: dict[str, str]`, `runtime.default_language: str`, `runtime.own_call_ids: set[str]`, `runtime.record_marks: set[str]`

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_sip_as_dispatch.py`:

```python
"""Выбор логического AS по Route, языки абонентов, снятие своего Route, свои диалоги."""

import unittest

from lab_common.http import valid_call_id
from sip_fakes import CALLEE, CALLER, DOMAIN, ENV, SCSCF, SipCase, invite, load_sip_as

load_sip_as()
from ims_sip.core import dialogs, subscribers
from ims_sip.core.proxy import build_forwarded_request
from ims_sip.core.sip import top_route_host

AS_PORT = ENV["SIP_AS_PORT"]


class RouteHost(unittest.TestCase):
    def test_top_route_host_names_logical_as(self):
        message = invite(CALLEE, route_host="translate.as")
        self.assertEqual(top_route_host(message), f"translate.as.{DOMAIN}".lower())

    def test_no_route_means_no_host(self):
        self.assertEqual(top_route_host(invite(CALLEE, route_host=None)), "")


class Languages(unittest.TestCase):
    def test_table_maps_msisdn_and_imsi(self):
        table = subscribers.language_table(ENV)
        self.assertEqual(table[ENV["SIPUE1_MSISDN"]], "ru")
        self.assertEqual(table[ENV["SIPUE1_IMSI"]], "ru")
        self.assertEqual(table[ENV["SIPUE2_MSISDN"]], "en")
        self.assertEqual(table[ENV["UE2_IMSI"]], "en")

    def test_missing_language_uses_default(self):
        env = {key: value for key, value in ENV.items() if key != "SIPUE2_LANGUAGE"}
        table = subscribers.language_table(env)
        self.assertEqual(table[ENV["SIPUE2_MSISDN"]], ENV["DEFAULT_LANGUAGE"])

    def test_unsupported_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "UE1_LANGUAGE=de"):
            subscribers.language_table({**ENV, "UE1_LANGUAGE": "de"})

    def test_served_user_prefers_p_served_user(self):
        message = invite(CALLEE, served=ENV["SIPUE1_IMSI"])
        self.assertEqual(subscribers.served_user(message), ENV["SIPUE1_IMSI"])

    def test_served_user_falls_back_to_from(self):
        message = invite(CALLEE).replace("P-Served-User:", "X-Removed:")
        self.assertEqual(subscribers.served_user(message), CALLER)

    def test_target_user_keeps_star_prefix(self):
        self.assertEqual(subscribers.target_user(invite(f"*{CALLEE}")), f"*{CALLEE}")


class OwnRoute(unittest.TestCase):
    def test_strips_logical_as_route_in_comma_form(self):
        forwarded = build_forwarded_request(invite(CALLEE, route_host="translate.as"), "b1")
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")
        self.assertNotIn("translate.as.", forwarded)

    def test_strips_route_on_its_own_line(self):
        message = invite(CALLEE, route_host="record.as").replace(
            ">, <sip:iscmark@", ">\r\nRoute: <sip:iscmark@"
        )
        forwarded = build_forwarded_request(message, "b2")
        self.assertNotIn("record.as.", forwarded)
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")

    def test_record_route_is_not_touched(self):
        record_route = f"Record-Route: <sip:record.as.{DOMAIN}:{AS_PORT};lr>, <sip:mo@"
        message = invite(CALLEE).replace("Record-Route: <sip:mo@", record_route)
        self.assertIn(record_route, build_forwarded_request(message, "b3"))


class OwnDialogs(SipCase):
    def test_new_call_id_is_valid_and_own(self):
        call_id = dialogs.new_call_id()
        self.assertRegex(call_id, r"^b2b-[0-9a-f]{24}$")
        self.assertTrue(valid_call_id(call_id))
        self.assertTrue(dialogs.is_own(call_id))
        dialogs.forget(call_id)
        self.assertFalse(dialogs.is_own(call_id))

    def test_numbers_does_not_observe_own_leg(self):
        call_id = dialogs.new_call_id()
        self.route_request(invite(CALLEE, call_id), SCSCF)
        self.assertEqual(len(self.requests("INVITE")), 1)
        self.assertEqual(self.http.posted("media.test/sessions"), [])
        self.assertNotIn("AS observed INVITE", self.log())

    def test_unknown_route_host_falls_back_to_numbers(self):
        self.route_request(invite(CALLEE, "plain-x", route_host="unknown.as"), SCSCF)
        self.assertIn("AS observed INVITE call_id=plain-x", self.log())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_dispatch.py' -v`
Expected: ERROR — `ImportError: cannot import name 'dialogs' from 'ims_sip.core'`.

- [ ] **Step 3: Разбор Route и заголовков в `core/sip.py`**

В конец `app/services/sip-as/ims_sip/core/sip.py` добавить:

```python
COMPACT = {"Call-ID": "i", "From": "f", "To": "t", "Via": "v", "Contact": "m", "Content-Type": "c"}


def value_of(message: str, name: str) -> str:
    """Значение заголовка только из части заголовков; компактное имя тоже подходит."""
    head = message.split("\r\n\r\n", 1)[0]
    return header(head, name) or (header(head, COMPACT[name]) if name in COMPACT else "")


def request_uri(message: str) -> str:
    return message.split("\r\n", 1)[0].split(" ")[1]


def route_values(message: str, name: str = "Route") -> list[str]:
    """Все значения <...> заголовка по порядку: и через запятую, и отдельными строками."""
    head = message.split("\r\n\r\n", 1)[0]
    return [value for line in all_headers(head, name) for value in re.findall(r"<[^>]+>", line)]


def top_route_host(message: str) -> str:
    """Хост первого Route: по нему S-CSCF адресует логический AS из iFC."""
    routes = route_values(message)
    match = re.match(r"<sips?:(?:[^@>]+@)?([^:;>]+)", routes[0]) if routes else None
    return match.group(1).lower() if match else ""
```

- [ ] **Step 4: Абоненты и свои диалоги**

`app/services/sip-as/ims_sip/core/subscribers.py`:

```python
"""Абоненты для SIP AS: язык по MSISDN/IMSI из lab.env, обслуживаемый и вызываемый номер."""

import re

from .sip import request_uri, value_of

PROFILES = ("UE1", "UE2", "SIPUE1", "SIPUE2")
LANGUAGES = ("ru", "en")


def language_table(environ) -> dict[str, str]:
    """MSISDN и IMSI каждого абонента -> язык; не задан — DEFAULT_LANGUAGE."""
    default = environ.get("DEFAULT_LANGUAGE") or "ru"
    if default not in LANGUAGES:
        raise ValueError(f"DEFAULT_LANGUAGE={default}: допустимы {', '.join(LANGUAGES)}")
    table = {}
    for prefix in PROFILES:
        language = environ.get(f"{prefix}_LANGUAGE") or default
        if language not in LANGUAGES:
            raise ValueError(f"{prefix}_LANGUAGE={language}: допустимы {', '.join(LANGUAGES)}")
        for key in (f"{prefix}_MSISDN", f"{prefix}_IMSI"):
            if environ.get(key):
                table[environ[key]] = language
    return table


def uri_user(value: str) -> str:
    match = re.search(r"(?:sips?|tel):([^@;>\s]+)", value)
    return match.group(1) if match else ""


def served_user(message: str) -> str:
    """Обслуживаемый абонент: P-Served-User от S-CSCF, иначе From."""
    return uri_user(value_of(message, "P-Served-User") or value_of(message, "From"))


def target_user(message: str) -> str:
    return uri_user(request_uri(message))


def language_for(user: str, table: dict[str, str], default: str) -> str:
    return table.get(user, default)
```

`app/services/sip-as/ims_sip/core/dialogs.py`:

```python
"""Диалоги, созданные самим SIP AS (нога B), и звонки, помеченные record AS."""

import secrets

from .. import runtime


def new_call_id() -> str:
    """Call-ID ноги B без '@': проходит valid_call_id Media Adapter и Voice Agent."""
    call_id = "b2b-" + secrets.token_hex(12)
    runtime.own_call_ids.add(call_id)
    return call_id


def is_own(call_id: str) -> bool:
    return call_id in runtime.own_call_ids


def forget(call_id: str) -> None:
    runtime.own_call_ids.discard(call_id)
    runtime.record_marks.discard(call_id)


def mark_record(call_id: str) -> None:
    runtime.record_marks.add(call_id)


def is_marked_record(call_id: str) -> bool:
    return call_id in runtime.record_marks
```

В `app/services/sip-as/ims_sip/runtime.py` после строки `import socket` добавить:

```python

from .core.subscribers import language_table
```

и в конец файла:

```python
ims_domain = os.environ["IMS_DOMAIN"]
languages = language_table(os.environ)
default_language = os.environ.get("DEFAULT_LANGUAGE") or "ru"
own_call_ids = set()
record_marks = set()
```

- [ ] **Step 5: Снятие Route любого логического AS**

В `app/services/sip-as/ims_sip/core/proxy.py` заменить строку `OWN_ROUTE = ...` на:

```python
# Свой Route — первый, хост <метка>.as.<домен> или as.<домен>: в одной строке со
# следующим ISC Route через запятую либо отдельной строкой.
OWN_ROUTE = re.compile(r"(?im)^(Route\s*:\s*)<sip:(?:[a-z0-9-]+\.)?as\.[^>]+>\s*,\s*")
OWN_ROUTE_LINE = re.compile(r"(?im)^Route\s*:\s*<sip:(?:[a-z0-9-]+\.)?as\.[^>]+>\s*\r\n")
```

и функцию `build_forwarded_request` на:

```python
def build_forwarded_request(message: str, branch: str) -> str:
    request_line, remaining_headers = message.split("\r\n", 1)
    own_via = (
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    )
    # Поглощается только Route текущего AS. Следующий ISC Route возвращает
    # запрос в S-CSCF, где продолжается цепочка iFC.
    stripped = OWN_ROUTE.sub(r"\1", remaining_headers, count=1)
    if stripped == remaining_headers:
        stripped = OWN_ROUTE_LINE.sub("", remaining_headers, count=1)
    return request_line + "\r\n" + own_via + stripped
```

- [ ] **Step 6: Диспетчер и пропуск своих ног в numbers**

`app/services/sip-as/ims_sip/core/dispatch.py` заменить целиком:

```python
"""Вход SIP AS: запрос — логическому AS по первому Route, ответ — по своему Via."""

from .. import runtime
from ..services import numbers
from .proxy import relay_response
from .sip import top_route_host

SERVICES = (numbers,)


def service_for(message: str):
    host = top_route_host(message)
    return next((s for s in SERVICES if host == f"{s.HOST}.{runtime.ims_domain}"), None)


def route_request(message: str, peer: tuple[str, int]) -> None:
    (service_for(message) or numbers).handle(message, peer)


def route_response(message: str) -> None:
    relay_response(message)
```

В `app/services/sip-as/ims_sip/services/numbers.py` после `from .. import runtime` добавить
`from ..core import dialogs` и заменить функцию `handle`:

```python
def handle(message: str, peer: tuple[str, int]) -> None:
    """Номер услуги — завершить на Voice Agent, иначе наблюдать и вернуть в S-CSCF."""
    request_line = message.split("\r\n", 1)[0]
    call_id = message_call_id(message)
    service_mode = service_mode_for_request(request_line, call_id)
    if service_mode:
        terminate_for_agent(message, peer, service_mode)
        return
    # Ногу B, созданную самим SIP AS, уже распознаёт услуга: не наблюдать дважды.
    if not dialogs.is_own(call_id):
        observe_proxied_dialog(message, request_line, call_id)
    forward(message, peer)
```

- [ ] **Step 7: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_*.py' -v`
Expected: `Ran 23 tests` … `OK` (14 новых + 9 характеризационных).

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 8: Коммит**

```bash
git add app/services/sip-as/ims_sip/core app/services/sip-as/ims_sip/runtime.py \
  app/services/sip-as/ims_sip/services/numbers.py app/tests/unit/test_sip_as_dispatch.py
git commit -m "feat: route SIP AS requests to logical AS by top Route"
```

---

### Task 5: Явное API MRF в `core/mrf.py`

**Files:**
- Modify: `app/services/sip-as/ims_sip/core/mrf.py` (импорты и конец файла)
- Modify: `app/services/sip-as/ims_sip/services/numbers.py` (`start_agent_call`, `end_agent_call`, `observe_proxied_dialog`, импорты)
- Modify: `app/services/sip-as/ims_sip/runtime.py` (конец файла)
- Modify: `app/infrastructure/compose/ai.yml:55`
- Test: `app/tests/unit/test_sip_as_mrf.py`

**Interfaces:**
- Consumes: `core.mrf.notify_voice`, `notify_adapter`, `stop_voice`, `stop_adapter`, `best_effort` (задача 3).
- Produces (`core.mrf`):
  - `INTERPRETER_MODES: dict[str, str]` = `{"ru": "interpret_ru", "en": "interpret_en"}`
  - `free_slots() -> int`
  - `bind_leg(message: str, call_id: str, remote_ip: str, remote_port: int, service_mode: str) -> bool`
  - `stream_to_recognition(message: str, service_mode: str, rtpengine_port: int | None = None) -> None`
  - `stop_recognition(call_id: str) -> None`
  - `release(call_id: str) -> None`
  - `play(call_id: str, text: str, voice: str) -> bool` (POST Voice Agent `/calls/<id>/reply`, `reason="announcement"`)
  - `pair(leg_a: tuple[str, str], leg_b: tuple[str, str]) -> None` (POST AI `/pairs`)
  - `unpair(call_id: str) -> None` (DELETE AI `/pairs/<id>`)
  - `record_pair(session_call_id: str, legs: list[tuple[str, str]]) -> None` (POST AI `/recordings`)
  - `announce(call_id: str, parties: list[tuple[str, str, str]]) -> bool` (POST Media Adapter `/sessions/<id>/announce`)
  - `runtime.ai_worker_url: str`, `runtime.voice_status_url: str`, `runtime.voice_max_calls: int`

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_sip_as_mrf.py`:

```python
"""API MRF: места, привязка ноги, озвучка, распознавание, пара, запись, освобождение."""

import unittest

from sip_fakes import CALLEE, ENV, RTP_A, RTP_IP, SipCase, invite, load_sip_as

load_sip_as()
from ims_sip.core import mrf


class MrfApi(SipCase):
    def test_free_slots_from_voice_status(self):
        self.http.voice_calls = {"c1": {}, "c2": {}}
        self.assertEqual(mrf.free_slots(), int(ENV["VOICE_AGENT_MAX_CALLS"]) - 2)

    def test_free_slots_zero_when_voice_agent_down(self):
        self.http.fail.add("voice.test")
        self.assertEqual(mrf.free_slots(), 0)
        self.assertIn("AS mrf status unavailable", self.log())

    def test_bind_leg_registers_voice_and_adapter(self):
        message = invite(CALLEE, "leg-1")
        self.assertTrue(mrf.bind_leg(message, "leg-1", RTP_IP, RTP_A, "interpret_ru"))
        self.assertEqual(
            self.http.posted("voice.test/calls"),
            [
                {
                    "call_id": "leg-1",
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_A,
                    "service_mode": "interpret_ru",
                }
            ],
        )
        session = self.http.posted("media.test/sessions")[0]
        self.assertEqual(
            (session["call_id"], session["service_mode"], session["rtpengine_port"]),
            ("leg-1", "interpret_ru", RTP_A),
        )

    def test_bind_leg_fails_without_voice_agent(self):
        self.http.fail.add("voice.test")
        message = invite(CALLEE, "leg-2")
        self.assertFalse(mrf.bind_leg(message, "leg-2", RTP_IP, RTP_A, "interpret_en"))
        self.assertEqual(self.http.posted("media.test/sessions"), [])
        self.assertIn("AS voice unavailable call_id=leg-2", self.log())

    def test_release_stops_voice_and_adapter(self):
        mrf.release("leg-3")
        self.assertEqual(len(self.http.deleted("voice.test/calls/leg-3")), 1)
        self.assertEqual(len(self.http.deleted("media.test/sessions/leg-3")), 1)

    def test_stop_recognition_keeps_voice_agent(self):
        mrf.stop_recognition("leg-4")
        self.assertEqual(self.http.deleted("voice.test"), [])
        self.assertEqual(len(self.http.deleted("media.test/sessions/leg-4")), 1)

    def test_play_sends_announcement_reply(self):
        self.assertTrue(mrf.play("leg-5", "Внимание", ENV["TTS_VOICE"]))
        self.assertEqual(
            self.http.posted("voice.test/calls/leg-5/reply"),
            [{"text": "Внимание", "voice": ENV["TTS_VOICE"], "reason": "announcement"}],
        )

    def test_play_reports_failure(self):
        self.http.fail.add("voice.test")
        self.assertFalse(mrf.play("leg-6", "Внимание", ENV["TTS_VOICE"]))
        self.assertIn("AS mrf play failed call_id=leg-6", self.log())

    def test_pair_and_unpair(self):
        mrf.pair(("leg-a", "ru"), ("leg-b", "en"))
        legs = [{"call_id": "leg-a", "language": "ru"}, {"call_id": "leg-b", "language": "en"}]
        self.assertEqual(self.http.posted("ai.test/pairs"), [{"legs": legs}])
        mrf.unpair("leg-a")
        self.assertEqual(len(self.http.deleted("ai.test/pairs/leg-a")), 1)

    def test_record_pair(self):
        mrf.record_pair("leg-a", [("leg-a", "caller"), ("leg-b", "callee")])
        self.assertEqual(
            self.http.posted("ai.test/recordings"),
            [
                {
                    "session_call_id": "leg-a",
                    "legs": [
                        {"call_id": "leg-a", "speaker": "caller"},
                        {"call_id": "leg-b", "speaker": "callee"},
                    ],
                }
            ],
        )

    def test_announce_asks_adapter_to_play_to_each_party(self):
        self.assertTrue(mrf.announce("call-r", [("fa1", "Внимание", ENV["TTS_VOICE"])]))
        self.assertEqual(
            self.http.posted("media.test/sessions/call-r/announce"),
            [{"parties": [{"tag": "fa1", "text": "Внимание", "voice": ENV["TTS_VOICE"]}]}],
        )

    def test_announce_failure_is_false(self):
        self.http.fail.add("/announce")
        self.assertFalse(mrf.announce("call-s", [("fa1", "Внимание", ENV["TTS_VOICE"])]))
        self.assertIn("AS mrf announce failed call_id=call-s", self.log())

    def test_stream_to_recognition_uses_service_mode(self):
        mrf.stream_to_recognition(invite(CALLEE, "rec-1"), "record")
        session = self.http.posted("media.test/sessions")[0]
        self.assertEqual(
            (session["call_id"], session["service_mode"], session["rtpengine_port"]),
            ("rec-1", "record", RTP_A),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_mrf.py' -v`
Expected: ERROR/FAIL — `AttributeError: module 'ims_sip.core.mrf' has no attribute 'free_slots'`.

- [ ] **Step 3: Реализовать API MRF**

В `app/services/sip-as/ims_sip/core/mrf.py` после `import re` добавить `import threading`, а в
конец файла:

```python
INTERPRETER_MODES = {"ru": "interpret_ru", "en": "interpret_en"}


def free_slots() -> int:
    """Свободные места Voice Agent; ошибка опроса — мест нет, звонок идёт без перевода."""
    try:
        status = request_json(
            "GET", runtime.voice_status_url, token=runtime.control_token, timeout=1
        )
    except Exception as exc:
        print(f"AS mrf status unavailable type={type(exc).__name__}", flush=True)
        return 0
    return max(0, runtime.voice_max_calls - len((status or {}).get("calls", {})))


def bind_leg(message, call_id, remote_ip, remote_port, service_mode) -> bool:
    """Привязать ногу: Voice Agent обязателен, Media Adapter — в фоне и без отказа звонка."""
    try:
        notify_voice(call_id, remote_ip, remote_port, service_mode)
    except Exception as error:
        print(f"AS voice unavailable call_id={call_id} type={type(error).__name__}", flush=True)
        return False
    stream_to_recognition(message, service_mode, remote_port)
    return True


def stream_to_recognition(message, service_mode, rtpengine_port=None) -> None:
    """Отдавать звук звонка из RTPengine на распознавание (Call-ID берётся из message)."""
    threading.Thread(
        target=notify_adapter, args=(message, service_mode, rtpengine_port), daemon=True
    ).start()


def stop_recognition(call_id) -> None:
    threading.Thread(target=stop_adapter, args=(call_id,), daemon=True).start()


def release(call_id) -> None:
    """Освободить ногу: место Voice Agent и поток распознавания."""
    threading.Thread(target=stop_voice, args=(call_id,), daemon=True).start()
    stop_recognition(call_id)


def play(call_id, text, voice) -> bool:
    """Сыграть фразу в ногу, привязанную к Voice Agent."""
    url = f"{runtime.voice_url}/{quote(call_id, safe='')}/reply"
    payload = {"text": text, "voice": voice, "reason": "announcement"}
    try:
        request_json("POST", url, payload=payload, token=runtime.control_token, timeout=2)
    except Exception as exc:
        print(f"AS mrf play failed call_id={call_id} type={type(exc).__name__}", flush=True)
        return False
    return True


def pair(leg_a, leg_b) -> None:
    """Сообщить AI Worker пару ног перевода: (Call-ID, язык) каждой стороны."""
    legs = [{"call_id": call_id, "language": language} for call_id, language in (leg_a, leg_b)]
    best_effort("POST", f"{runtime.ai_worker_url}/pairs", {"legs": legs})


def unpair(call_id) -> None:
    best_effort("DELETE", f"{runtime.ai_worker_url}/pairs/{quote(call_id, safe='')}")


def record_pair(session_call_id, legs) -> None:
    """Писать обе ноги в одну запись AI Worker: legs — [(Call-ID, caller|callee)]."""
    payload = {
        "session_call_id": session_call_id,
        "legs": [{"call_id": call_id, "speaker": speaker} for call_id, speaker in legs],
    }
    best_effort("POST", f"{runtime.ai_worker_url}/recordings", payload)


def announce(call_id, parties) -> bool:
    """Уведомление через RTPengine звонку без MRF: parties — [(SIP tag, текст, голос)]."""
    url = f"{runtime.adapter_url}/{quote(call_id, safe='')}/announce"
    payload = {"parties": [{"tag": t, "text": x, "voice": v} for t, x, v in parties]}
    try:
        request_json("POST", url, payload=payload, token=runtime.control_token, timeout=40)
    except Exception as exc:
        print(f"AS mrf announce failed call_id={call_id} type={type(exc).__name__}", flush=True)
        return False
    return True
```

В конец `app/services/sip-as/ims_sip/runtime.py` добавить:

```python
ai_worker_url = os.environ["AI_WORKER_URL"].rstrip("/")
voice_status_url = os.environ["VOICE_AGENT_URL"].rstrip("/") + "/status"
voice_max_calls = int(os.environ["VOICE_AGENT_MAX_CALLS"])
```

В `app/infrastructure/compose/ai.yml` после строки 55
(`VOICE_AGENT_URL: http://${VOICE_AGENT_IP}:${VOICE_AGENT_HTTP_PORT}` в сервисе `sip-as`)
добавить:

```yaml
      AI_WORKER_URL: http://${AI_WORKER_IP}:${AI_WORKER_PORT}
```

- [ ] **Step 4: numbers — через API MRF**

В `app/services/sip-as/ims_sip/services/numbers.py` заменить блок импортов на:

```python
import re

from .. import runtime
from ..core import dialogs, mrf
from ..core.mrf import media_is_anchored, voice_agent_sdp
from ..core.proxy import forward
from ..core.sdp import accepts_pcmu, offered_media_endpoint
from ..core.sip import local_tag, message_call_id, request_method
from ..core.transport import send_local_response
```

функцию `start_agent_call` на:

```python
def start_agent_call(message, call_id, offered_ip, offered_port, service_mode, tag) -> bool:
    """Создать Voice/Media состояние один раз; INVITE может повторяться."""
    if call_id in runtime.agent_calls:
        return True
    if not mrf.bind_leg(message, call_id, offered_ip, offered_port, service_mode):
        return False
    runtime.agent_calls[call_id] = {
        "tag": tag,
        "service_mode": service_mode,
        "rtpengine_port": offered_port,
    }
    return True
```

функцию `end_agent_call` на:

```python
def end_agent_call(message, peer, call_id, method, fallback_tag) -> None:
    call = runtime.agent_calls.get(call_id, {})
    send_local_response(message, peer, 200, "OK", to_tag=call.get("tag", fallback_tag))
    runtime.agent_calls.pop(call_id, None)
    # Очистка вспомогательных сервисов не задерживает SIP 200 OK.
    mrf.release(call_id)
    print(f"AS ended voice agent call_id={call_id} method={method}", flush=True)
```

функцию `observe_proxied_dialog` на:

```python
def observe_proxied_dialog(message: str, request_line: str, call_id: str) -> None:
    """Сообщить Media Adapter о начале/завершении обычного звонка."""
    if request_line.startswith("INVITE "):
        print(f"AS observed INVITE call_id={call_id}", flush=True)
        mrf.stream_to_recognition(message, "observe")
    elif request_line.startswith(("BYE ", "CANCEL ")):
        mrf.stop_recognition(call_id)
```

- [ ] **Step 5: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_*.py' -v`
Expected: `Ran 36 tests` … `OK` (характеризация numbers не изменилась).

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 6: Коммит**

```bash
git add app/services/sip-as/ims_sip/core/mrf.py app/services/sip-as/ims_sip/services/numbers.py \
  app/services/sip-as/ims_sip/runtime.py app/infrastructure/compose/ai.yml app/tests/unit/test_sip_as_mrf.py
git commit -m "feat: explicit MRF API in SIP AS core"
```

---

### Task 6: AI Worker — явная пара ног перевода

**Files:**
- Modify: `app/services/ai-worker/ims_ai/runtime.py` (после `stream_hypotheses = {}`)
- Modify: `app/services/ai-worker/ims_ai/api.py` (конец файла)
- Modify: `app/services/ai-worker/ims_ai/interpretation.py:32-45` (`delivery_call`)
- Modify: `app/services/ai-worker/ims_ai/lifecycle.py:92-102` (`clear_call_state`)
- Test: `app/tests/unit/test_ai_pairs.py`

**Interfaces:**
- Consumes: `lab_common.http.json_object`, `require`, `valid_call_id`; `runtime.active_calls`.
- Produces:
  - HTTP `POST /pairs` `{"legs": [{"call_id": str, "language": "ru"|"en"}, {...}]}` → `202`; `DELETE /pairs/<call_id>` → `204`
  - `ims_ai.runtime.pairs: dict[str, str]` (Call-ID ноги → Call-ID партнёра)
  - `ims_ai.api.PAIR_LANGUAGES = {"ru", "en"}`
  - `interpretation.delivery_call(source_call_id, service_mode) -> str` — сначала пара, затем прежнее правило 1005/1006 без ног из пар

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_ai_pairs.py`:

```python
"""AI Worker: явная пара ног от SIP AS вместо поиска единственной противоположной ноги."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/ai-worker"))


class Pairs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        token = Path(cls.temp.name) / "token"
        token.write_text("unit-test-token", encoding="ascii")
        env = {}
        for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env.update(SERVICE_CONTROL_TOKEN_FILE=str(token), VOICE_AGENT_URL="http://localhost")
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        with patch("socket.socket"):
            from ims_ai import api, interpretation, lifecycle, runtime
        cls.interpretation, cls.lifecycle, cls.runtime = interpretation, lifecycle, runtime
        cls.client = api.api.test_client()
        cls.headers = {"Authorization": f"Bearer {runtime.control_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.runtime.pairs.clear()
        self.runtime.active_calls.clear()

    def post_pair(self, first, second):
        legs = [{"call_id": first[0], "language": first[1]}]
        legs.append({"call_id": second[0], "language": second[1]})
        return self.client.post("/pairs", json={"legs": legs}, headers=self.headers)

    def test_pair_routes_each_leg_to_its_partner(self):
        self.assertEqual(self.post_pair(("leg-a", "ru"), ("leg-b", "en")).status_code, 202)
        self.assertEqual(self.interpretation.delivery_call("leg-a", "interpret_ru"), "leg-b")
        self.assertEqual(self.interpretation.delivery_call("leg-b", "interpret_en"), "leg-a")

    def test_two_pairs_at_once(self):
        self.post_pair(("a1", "ru"), ("b1", "en"))
        self.post_pair(("a2", "ru"), ("b2", "en"))
        for call_id, mode in (("a1", "interpret_ru"), ("b1", "interpret_en")):
            self.runtime.active_calls[call_id] = {"service_mode": mode}
        for call_id, mode in (("a2", "interpret_ru"), ("b2", "interpret_en")):
            self.runtime.active_calls[call_id] = {"service_mode": mode}
        self.assertEqual(self.interpretation.delivery_call("a1", "interpret_ru"), "b1")
        self.assertEqual(self.interpretation.delivery_call("b2", "interpret_en"), "a2")

    def test_invalid_pairs_are_rejected(self):
        cases = [
            (("leg-a", "ru"), ("leg-b", "ru")),
            (("leg-a", "ru"), ("leg-a", "en")),
            (("leg-a", "ru"), ("bad id", "en")),
            (("leg-a", "ru"), ("leg-b", "de")),
        ]
        for first, second in cases:
            with self.subTest(first=first, second=second):
                self.assertEqual(self.post_pair(first, second).status_code, 400)
        single = {"legs": [{"call_id": "leg-a", "language": "ru"}]}
        response = self.client.post("/pairs", json=single, headers=self.headers)
        self.assertEqual(response.status_code, 400)

    def test_unpaired_interpreter_legs_keep_old_rule(self):
        self.runtime.active_calls["ru-1"] = {"service_mode": "interpret_ru"}
        self.runtime.active_calls["en-1"] = {"service_mode": "interpret_en"}
        self.assertEqual(self.interpretation.delivery_call("ru-1", "interpret_ru"), "en-1")

    def test_paired_legs_are_not_candidates_for_others(self):
        self.post_pair(("leg-a", "ru"), ("leg-b", "en"))
        self.runtime.active_calls["leg-b"] = {"service_mode": "interpret_en"}
        self.runtime.active_calls["ru-1"] = {"service_mode": "interpret_ru"}
        with self.assertRaises(RuntimeError):
            self.interpretation.delivery_call("ru-1", "interpret_ru")

    def test_delete_removes_both_directions(self):
        self.post_pair(("leg-a", "ru"), ("leg-b", "en"))
        response = self.client.delete("/pairs/leg-a", headers=self.headers)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.runtime.pairs, {})

    def test_call_end_drops_own_pair_entry(self):
        self.post_pair(("leg-a", "ru"), ("leg-b", "en"))
        self.lifecycle.clear_call_state("leg-a")
        self.assertNotIn("leg-a", self.runtime.pairs)
        self.assertEqual(self.runtime.pairs["leg-b"], "leg-a")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_ai_pairs.py' -v`
Expected: ERROR — `AttributeError: module 'ims_ai.runtime' has no attribute 'pairs'`.

- [ ] **Step 3: Реализовать пары**

В `app/services/ai-worker/ims_ai/runtime.py` после строки `stream_hypotheses = {}` добавить:

```python
pairs = {}
```

В конец `app/services/ai-worker/ims_ai/api.py` добавить:

```python
PAIR_LANGUAGES = {"ru", "en"}


@api.post("/pairs")
def register_pair():
    """SIP AS сообщает пару ног B2BUA: перевод каждой ноги уходит в ногу партнёра."""
    legs = json_object(4096).get("legs")
    require(isinstance(legs, list) and len(legs) == 2)
    require(
        all(
            isinstance(leg, dict)
            and valid_call_id(leg.get("call_id"))
            and leg.get("language") in PAIR_LANGUAGES
            for leg in legs
        )
    )
    first, second = legs
    require(first["call_id"] != second["call_id"] and first["language"] != second["language"])
    with runtime.lock:
        runtime.pairs[first["call_id"]] = second["call_id"]
        runtime.pairs[second["call_id"]] = first["call_id"]
    print(f"AI pair_registered calls={[first['call_id'], second['call_id']]}", flush=True)
    return "", 202


@api.delete("/pairs/<call_id>")
def remove_pair(call_id):
    require(valid_call_id(call_id))
    with runtime.lock:
        partner = runtime.pairs.pop(call_id, None)
        if partner is not None and runtime.pairs.get(partner) == call_id:
            runtime.pairs.pop(partner)
    return "", 204
```

В `app/services/ai-worker/ims_ai/interpretation.py` заменить функцию `delivery_call`
(строки 32–45):

```python
def delivery_call(source_call_id, service_mode):
    """Пара от SIP AS важнее; без пары — единственная нога противоположного языка (1005/1006)."""
    if service_mode not in INTERPRETER_MODES:
        return source_call_id
    opposite = "interpret_en" if service_mode == "interpret_ru" else "interpret_ru"
    with runtime.lock:
        partner = runtime.pairs.get(source_call_id)
        if partner is not None:
            return partner
        candidates = [
            call_id
            for call_id, state in runtime.active_calls.items()
            if call_id != source_call_id
            and call_id not in runtime.pairs
            and state.get("service_mode") == opposite
        ]
    if len(candidates) != 1:
        raise RuntimeError("interpreter counterpart is not uniquely available")
    return candidates[0]
```

В `app/services/ai-worker/ims_ai/lifecycle.py` в `clear_call_state` заменить последние две
строки (`with runtime.lock:` / `runtime.active_calls.pop(call_id, None)`) на:

```python
    with runtime.lock:
        runtime.active_calls.pop(call_id, None)
        # Запись партнёра остаётся до конца его ноги: её хвост ещё может переводиться.
        runtime.pairs.pop(call_id, None)
```

- [ ] **Step 4: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_ai_pairs.py' -v`
Expected: `Ran 7 tests` … `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены` (в том числе
`test_phrase_boundaries.py` и `test_service_api.py`).

- [ ] **Step 5: Коммит**

```bash
git add app/services/ai-worker/ims_ai/runtime.py app/services/ai-worker/ims_ai/api.py \
  app/services/ai-worker/ims_ai/interpretation.py app/services/ai-worker/ims_ai/lifecycle.py \
  app/tests/unit/test_ai_pairs.py
git commit -m "feat: explicit interpreter leg pairs in AI Worker"
```

---

### Task 7: B2BUA в `core/b2bua.py` и translate AS (нога B, 180, ответ, 486/480/408)

**Files:**
- Create: `app/services/sip-as/ims_sip/core/b2bua.py`, `app/services/sip-as/ims_sip/services/translate.py`
- Modify: `app/services/sip-as/ims_sip/core/sip.py` (конец файла), `app/services/sip-as/ims_sip/core/dispatch.py` (весь файл), `app/services/sip-as/ims_sip/runtime.py` (конец файла)
- Test: `app/tests/unit/test_sip_as_translate.py`

**Interfaces:**
- Consumes: `core.sip.value_of`, `route_values`, `local_tag`, `message_call_id`, `request_method`; `core.subscribers.served_user`, `target_user`, `language_for`; `core.dialogs.new_call_id`, `forget`; `core.mrf.bind_leg`, `release`, `pair`, `unpair`, `media_is_anchored`, `voice_agent_sdp`, `INTERPRETER_MODES`; `core.proxy.forward`; `core.transport.send`, `send_local_response`.
- Produces:
  - `core.sip.tag_of(value) -> str`, `core.sip.status_code(message) -> int`, `core.sip.angle_uri(value) -> str`
  - `core.b2bua.CONTACT_USER = "b2bua"`, `BRANCH_PREFIX = "z9hG4bK-b2b-"`, `OWN_VIA`
  - `core.b2bua.Leg(call_id, local_tag, local_uri, remote_uri, remote_target, remote_tag="", route_set=[], cseq=0, media=None)`
  - `core.b2bua.Call(a: Leg, b: Leg, a_invite: str, a_peer: tuple, languages: tuple[str, str], on_answer: Callable[[Call, str], bool], on_bye: Callable[[Call], None], b_invite="", b_branch="", state="calling", ringing_sent=False, answered=False, b_final=False)`
  - `core.b2bua.find(call_id) -> Call | None`, `strip_tag(value) -> str`, `contact() -> str`, `leg_b_routes(a_request) -> list[str]`, `leg_b_invite(call, a_request, request_uri) -> str`, `start(a_request, peer, request_uri, languages, on_answer, on_bye) -> Call`, `reply_a(call, status, reason, body="") -> None`, `dialog_request(leg, method, *, cseq=None, body="") -> tuple[str, str]`, `send_in_dialog(call, leg, method) -> None`, `ack_answer(call) -> None`, `ack_failure(call, response) -> None`, `handle_response(message) -> bool`, `leg_b_progress(call, status) -> None`, `leg_b_answered(call, response) -> None`, `leg_b_failed(call, response, status) -> None`, `end(call) -> None`
  - `services.translate.HOST = "translate.as"`, `strip_star(user) -> str`, `caller_language(message) -> str`, `on_invite(message, peer) -> None`, `on_answer(call, response) -> bool`, `on_bye(call) -> None`, `handle(message, peer) -> None`
  - `runtime.b2bua_calls: dict[str, Call]`, `runtime.b2bua_branches: dict[str, Call]`
  - Журнал: `AS b2bua leg_b call_id=<B> for call_id=<A>`, `AS b2bua ringing call_id=<A>`, `AS b2bua answered call_id=<A> leg_b=<B>`, `AS b2bua answer failed call_id=<A>`, `AS b2bua leg_b failed call_id=<A> status=<код>`, `AS translate answered call_id=<A> leg_b=<B> languages=<ru>-<en>`, `AS translate ended call_id=<A>`

Если spike (задача 1) дал «GO с F1», тело `leg_b_routes` берётся из шага 6 задачи 1, а
`test_leg_b_returns_to_scscf_with_isc_route` проверяет `Route: <sip:orig@scscf.`.

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_sip_as_translate.py`:

```python
"""translate AS: нога B через S-CSCF, 180 до ответа UE2, ответ UE1 после 200 UE2, пара в AI."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_A,
    RTP_B,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    load_sip_as,
    response,
    sdp,
)

load_sip_as()
from ims_sip.core import b2bua

CALLEE_CONTACT = f"<sip:{CALLEE}@192.0.2.20:5060>"
TERM_RR = (f"<sip:mt@scscf.{DOMAIN}:{SCSCF[1]};lr>",)


def call_id_of(message):
    return re.search(r"(?m)^Call-ID: (.+)$", message).group(1).strip()


class TranslateCase(SipCase):
    def start_call(self, call_id="tr-1", target=CALLEE, caller=CALLER):
        message = invite(target, call_id, route_host="translate.as", caller=caller)
        self.route_request(message, SCSCF)
        return self.requests("INVITE")[-1]

    def answer(self, leg_b, status=200, reason="OK", ip=RTP_IP):
        body = sdp(ip, RTP_B) if status == 200 else ""
        message = response(
            leg_b,
            status,
            reason,
            to_tag="tb1",
            body=body,
            contact=CALLEE_CONTACT,
            record_routes=TERM_RR,
        )
        self.route_response(message)


class LegB(TranslateCase):
    def test_caller_gets_trying_and_leg_b_goes_to_scscf(self):
        self.start_call()
        self.assertEqual(self.statuses(), [100])
        [(message, destination)] = [(m, d) for m, d in self.sent() if m.startswith("INVITE ")]
        self.assertEqual(destination, SCSCF)
        self.assertTrue(message.startswith(f"INVITE sip:{CALLEE}@{DOMAIN} SIP/2.0"))

    def test_leg_b_has_new_call_id_and_from_tag(self):
        leg_b = self.start_call()
        self.assertRegex(call_id_of(leg_b), r"^b2b-[0-9a-f]{24}$")
        from_value = re.search(r"(?m)^From: (.+)$", leg_b).group(1)
        self.assertIn(f"<sip:{CALLER}@{DOMAIN}>", from_value)
        self.assertNotIn("tag=fa1", from_value)

    def test_leg_b_returns_to_scscf_with_isc_route(self):
        leg_b = self.start_call()
        self.assertRegex(leg_b, r"(?m)^Route: <sip:iscmark@scscf\.")
        self.assertNotIn("translate.as.", leg_b)
        self.assertIn(f"P-Asserted-Identity: <sip:{CALLER}@{DOMAIN}>", leg_b)

    def test_leg_b_offers_voice_agent_media(self):
        leg_b = self.start_call()
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", leg_b)
        self.assertIn(f"c=IN IP4 {ENV['VOICE_AGENT_IP']}", leg_b)

    def test_ringing_is_sent_once(self):
        leg_b = self.start_call()
        for status, reason in ((180, "Ringing"), (180, "Ringing"), (183, "Session Progress")):
            self.route_response(response(leg_b, status, reason, to_tag="tb1"))
        self.assertEqual(self.statuses(), [100, 180])
        self.assertEqual(self.http.posted("voice.test/calls"), [])

    def test_star_prefix_is_stripped_for_leg_b(self):
        leg_b = self.start_call("tr-star", target=f"*{CALLEE}")
        self.assertTrue(leg_b.startswith(f"INVITE sip:{CALLEE}@{DOMAIN} SIP/2.0"))
        self.assertIn(f"To: <sip:{CALLEE}@{DOMAIN}>", leg_b)


class Answer(TranslateCase):
    def test_answer_acks_leg_b_and_answers_caller(self):
        self.answer(self.start_call())
        ack = self.requests("ACK")[-1]
        self.assertTrue(ack.startswith(f"ACK sip:{CALLEE}@192.0.2.20:5060 SIP/2.0"))
        self.assertIn("tag=tb1", ack)
        self.assertIn("CSeq: 1 ACK", ack)
        self.assertIn(f"Route: {TERM_RR[0]}", ack)
        final = [m for m, _ in self.sent() if m.startswith("SIP/2.0 200")][-1]
        self.assertIn("Call-ID: tr-1", final)
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", final)
        self.assertIn("Contact: <sip:b2bua@", final)

    def test_answer_binds_both_legs_with_languages(self):
        leg_b = self.start_call()
        self.answer(leg_b)
        b = call_id_of(leg_b)
        self.assertEqual(
            self.http.posted("voice.test/calls"),
            [
                {
                    "call_id": "tr-1",
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_A,
                    "service_mode": "interpret_ru",
                },
                {
                    "call_id": b,
                    "remote_ip": RTP_IP,
                    "remote_port": RTP_B,
                    "service_mode": "interpret_en",
                },
            ],
        )
        legs = [{"call_id": "tr-1", "language": "ru"}, {"call_id": b, "language": "en"}]
        self.assertEqual(self.http.posted("ai.test/pairs"), [{"legs": legs}])
        self.assertIn(f"AS translate answered call_id=tr-1 leg_b={b} languages=ru-en", self.log())

    def test_caller_is_answered_only_after_callee(self):
        leg_b = self.start_call()
        self.assertNotIn(200, self.statuses())
        self.answer(leg_b)
        self.assertEqual(self.statuses().count(200), 1)

    def test_repeated_200_is_acked_again(self):
        leg_b = self.start_call()
        self.answer(leg_b)
        self.answer(leg_b)
        self.assertEqual(len(self.requests("ACK")), 2)
        self.assertEqual(self.statuses().count(200), 1)

    def test_voice_agent_failure_hangs_up_leg_b_and_rejects_caller(self):
        leg_b = self.start_call()
        self.http.fail.add("voice.test/calls")
        self.answer(leg_b)
        self.assertEqual(len(self.requests("BYE")), 1)
        self.assertEqual(self.statuses()[-1], 500)
        self.assertIsNone(b2bua.find("tr-1"))
        self.assertIn("AS b2bua answer failed call_id=tr-1", self.log())

    def test_unanchored_answer_is_rejected(self):
        leg_b = self.start_call()
        self.answer(leg_b, ip="198.51.100.9")
        self.assertEqual(len(self.requests("BYE")), 1)
        self.assertEqual(self.statuses()[-1], 500)
        self.assertEqual(self.http.posted("voice.test/calls"), [])


class FailedLegB(TranslateCase):
    def test_final_failure_is_relayed_to_caller(self):
        failures = ((486, "Busy Here"), (480, "Temporarily Unavailable"), (408, "Request Timeout"))
        for status, reason in failures:
            with self.subTest(status=status):
                self.runtime.sock.reset_mock()
                leg_b = self.start_call(f"tr-{status}")
                self.answer(leg_b, status, reason)
                ack = self.requests("ACK")[-1]
                branch = re.search(r"branch=(z9hG4bK-b2b-[0-9a-f]+)", leg_b).group(1)
                self.assertIn(branch, ack)
                self.assertIn("CSeq: 1 ACK", ack)
                self.assertIn("tag=tb1", ack)
                self.assertEqual(self.statuses()[-1], status)
                self.assertIn(f"SIP/2.0 {status} {reason}", self.sent()[-2][0] + self.sent()[-1][0])
                self.assertIsNone(b2bua.find(f"tr-{status}"))
                self.assertEqual(self.http.posted("voice.test/calls"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_translate.py' -v`
Expected: ERROR — `ImportError: cannot import name 'b2bua' from 'ims_sip.core'`.

- [ ] **Step 3: Разбор tag, статуса и URI в `core/sip.py`**

В конец `app/services/sip-as/ims_sip/core/sip.py` добавить:

```python
def tag_of(value: str) -> str:
    match = re.search(r";tag=([^;>\s]+)", value)
    return match.group(1) if match else ""


def status_code(message: str) -> int:
    return int(message.split(" ", 2)[1])


def angle_uri(value: str) -> str:
    """URI из <...> заголовка Contact/To; без скобок — до первого параметра."""
    match = re.search(r"<([^>]+)>", value)
    return match.group(1) if match else value.split(";", 1)[0].strip()
```

- [ ] **Step 4: Реализовать B2BUA**

`app/services/sip-as/ims_sip/core/b2bua.py`:

```python
"""B2BUA: две ноги одного звонка через MRF.

Нога A — диалог звонящего, на который отвечает SIP AS. Нога B — новый диалог SIP AS
(свой Call-ID и From tag), который уходит в S-CSCF с ISC-меткой ноги A, чтобы S-CSCF
продолжил цепочку iFC со следующего приоритета. Медиа обеих ног идёт на Voice Agent.
"""

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import runtime
from . import dialogs
from .mrf import media_is_anchored, voice_agent_sdp
from .sdp import offered_media_endpoint
from .sip import (
    all_headers,
    angle_uri,
    local_tag,
    message_call_id,
    route_values,
    status_code,
    tag_of,
    value_of,
)
from .transport import send, send_local_response

CONTACT_USER = "b2bua"
BRANCH_PREFIX = "z9hG4bK-b2b-"
OWN_VIA = re.compile(r"(?im)^(?:Via|v)\s*:[^\r\n]*branch=(z9hG4bK-b2b-[^;\s]+)")


@dataclass
class Leg:
    call_id: str
    local_tag: str
    local_uri: str
    remote_uri: str
    remote_target: str
    remote_tag: str = ""
    route_set: list[str] = field(default_factory=list)
    cseq: int = 0
    media: tuple[str, int] | None = None


@dataclass
class Call:
    a: Leg
    b: Leg
    a_invite: str
    a_peer: tuple[str, int]
    languages: tuple[str, str]
    on_answer: Callable[["Call", str], bool]
    on_bye: Callable[["Call"], None]
    b_invite: str = ""
    b_branch: str = ""
    state: str = "calling"  # calling -> early -> answered -> ended
    ringing_sent: bool = False
    answered: bool = False
    b_final: bool = False


def find(call_id: str) -> Call | None:
    return runtime.b2bua_calls.get(call_id)


def strip_tag(value: str) -> str:
    return re.sub(r";tag=[^;>\s]*", "", value)


def contact() -> str:
    return f"<sip:{CONTACT_USER}@{runtime.bind_ip}:{runtime.bind_port};transport=udp>"


def leg_b_routes(a_request: str) -> list[str]:
    """ISC Route ноги A без своего: S-CSCF продолжит цепочку iFC со следующего приоритета."""
    return route_values(a_request)[1:]


def leg_b_invite(call: Call, a_request: str, request_uri: str) -> str:
    routes = leg_b_routes(a_request)
    body = voice_agent_sdp()
    lines = [
        f"INVITE {request_uri} SIP/2.0",
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch={call.b_branch}",
        "Max-Forwards: 70",
    ]
    if routes:
        lines.append("Route: " + ", ".join(routes))
    lines += all_headers(a_request, "P-Asserted-Identity")
    lines += [
        f"From: {call.b.local_uri};tag={call.b.local_tag}",
        f"To: {call.b.remote_uri}",
        f"Call-ID: {call.b.call_id}",
        "CSeq: 1 INVITE",
        f"Contact: {contact()}",
        "Content-Type: application/sdp",
        f"Content-Length: {len(body.encode())}",
    ]
    return "\r\n".join(lines) + "\r\n\r\n" + body


def start(a_request, peer, request_uri, languages, on_answer, on_bye) -> Call:
    """Принять ногу A (100 Trying) и отправить ногу B в S-CSCF."""
    a_call_id = message_call_id(a_request)
    send_local_response(a_request, peer, 100, "Trying")
    caller = value_of(a_request, "From")
    a = Leg(
        call_id=a_call_id,
        local_tag=local_tag(a_call_id),
        local_uri=strip_tag(value_of(a_request, "To")),
        remote_uri=strip_tag(caller),
        remote_target=angle_uri(value_of(a_request, "Contact")),
        remote_tag=tag_of(caller),
        route_set=route_values(a_request, "Record-Route"),
        media=offered_media_endpoint(a_request),
    )
    b = Leg(
        call_id=dialogs.new_call_id(),
        local_tag=secrets.token_hex(8),
        local_uri=strip_tag(caller),
        remote_uri=f"<{request_uri}>",
        remote_target=request_uri,
        cseq=1,
    )
    call = Call(
        a=a,
        b=b,
        a_invite=a_request,
        a_peer=peer,
        languages=languages,
        on_answer=on_answer,
        on_bye=on_bye,
        b_branch=BRANCH_PREFIX + secrets.token_hex(8),
    )
    call.b_invite = leg_b_invite(call, a_request, request_uri)
    runtime.b2bua_calls[a.call_id] = call
    runtime.b2bua_calls[b.call_id] = call
    runtime.b2bua_branches[call.b_branch] = call
    send(call.b_invite, runtime.scscf)
    print(f"AS b2bua leg_b call_id={b.call_id} for call_id={a.call_id}", flush=True)
    return call


def reply_a(call: Call, status: int, reason: str, body: str = "") -> None:
    send_local_response(
        call.a_invite,
        call.a_peer,
        status,
        reason,
        body=body,
        to_tag=call.a.local_tag,
        contact_user=CONTACT_USER,
    )


def dialog_request(leg: Leg, method: str, *, cseq: int | None = None, body: str = ""):
    """Запрос внутри диалога ноги; уходит в S-CSCF, дальше — по route set ноги."""
    if cseq is None:
        leg.cseq += 1
        cseq = leg.cseq
    branch = BRANCH_PREFIX + secrets.token_hex(8)
    to = leg.remote_uri + (f";tag={leg.remote_tag}" if leg.remote_tag else "")
    lines = [
        f"{method} {leg.remote_target} SIP/2.0",
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch={branch}",
        "Max-Forwards: 70",
    ]
    if leg.route_set:
        lines.append("Route: " + ", ".join(leg.route_set))
    lines += [
        f"From: {leg.local_uri};tag={leg.local_tag}",
        f"To: {to}",
        f"Call-ID: {leg.call_id}",
        f"CSeq: {cseq} {method}",
        f"Contact: {contact()}",
    ]
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body, branch


def send_in_dialog(call: Call, leg: Leg, method: str) -> None:
    message, branch = dialog_request(leg, method)
    runtime.b2bua_branches[branch] = call
    send(message, runtime.scscf)


def ack_answer(call: Call) -> None:
    """ACK на 2xx — отдельная транзакция с номером CSeq INVITE."""
    message, _ = dialog_request(call.b, "ACK", cseq=1)
    send(message, runtime.scscf)


def ack_failure(call: Call, response: str) -> None:
    """ACK на финальный не-2xx — в транзакции INVITE ноги B (тот же branch и Route)."""
    head = call.b_invite.split("\r\n\r\n", 1)[0].split("\r\n")
    names = r"(Via|Max-Forwards|Route|From|Call-ID)\s*:"
    keep = [line for line in head[1:] if re.match(names, line)]
    lines = [
        f"ACK {head[0].split(' ')[1]} SIP/2.0",
        *keep,
        f"To: {value_of(response, 'To')}",
        "CSeq: 1 ACK",
        "Content-Length: 0",
    ]
    send("\r\n".join(lines) + "\r\n\r\n", runtime.scscf)


def handle_response(message: str) -> bool:
    """Ответ на INVITE ноги B или на свой запрос в диалоге; False — ответ не B2BUA."""
    match = OWN_VIA.search(message)
    if match is None:
        return False
    branch = match.group(1)
    call = runtime.b2bua_branches.get(branch)
    status = status_code(message)
    if call is None:
        print(f"AS b2bua dropped response for unknown branch {branch}", flush=True)
        return True
    if branch != call.b_branch:
        if status >= 200:
            runtime.b2bua_branches.pop(branch, None)
        return True
    if status < 200:
        leg_b_progress(call, status)
    elif status < 300:
        leg_b_answered(call, message)
    else:
        leg_b_failed(call, message, status)
    return True


def leg_b_progress(call: Call, status: int) -> None:
    """Звонящий слышит 180 один раз, пока UE2 не ответил."""
    if status in (180, 183) and call.state == "calling" and not call.ringing_sent:
        call.ringing_sent = True
        call.state = "early"
        reply_a(call, 180, "Ringing")
        print(f"AS b2bua ringing call_id={call.a.call_id}", flush=True)


def leg_b_answered(call: Call, response: str) -> None:
    """200 от UE2: ACK, привязка ног услугой и только потом 200 звонящему."""
    b = call.b
    if call.answered:
        ack_answer(call)
        return
    b.remote_tag = tag_of(value_of(response, "To"))
    b.remote_target = angle_uri(value_of(response, "Contact")) or b.remote_target
    b.route_set = list(reversed(route_values(response, "Record-Route")))
    b.media = offered_media_endpoint(response)
    call.b_final = True
    ack_answer(call)
    if call.state == "ended":
        # Звонящий отменил вызов раньше, чем пришёл ответ UE2.
        send_in_dialog(call, b, "BYE")
        runtime.b2bua_branches.pop(call.b_branch, None)
        return
    anchored = b.media is not None and media_is_anchored(*b.media)
    if not anchored or not call.on_answer(call, response):
        print(f"AS b2bua answer failed call_id={call.a.call_id}", flush=True)
        send_in_dialog(call, b, "BYE")
        reply_a(call, 500, "Media Unavailable")
        end(call)
        return
    call.answered = True
    call.state = "answered"
    reply_a(call, 200, "OK", voice_agent_sdp())
    print(f"AS b2bua answered call_id={call.a.call_id} leg_b={b.call_id}", flush=True)


def leg_b_failed(call: Call, response: str, status: int) -> None:
    """486/480/408 и любой финальный не-2xx от UE2 — тот же ответ звонящему."""
    call.b_final = True
    ack_failure(call, response)
    if call.state == "ended":
        runtime.b2bua_branches.pop(call.b_branch, None)
        return
    reply_a(call, status, response.split("\r\n", 1)[0].split(" ", 2)[2])
    print(f"AS b2bua leg_b failed call_id={call.a.call_id} status={status}", flush=True)
    end(call)


def end(call: Call) -> None:
    """Забыть обе ноги и отдать услуге освобождение MRF и пары."""
    if call.state == "ended":
        return
    call.state = "ended"
    runtime.b2bua_calls.pop(call.a.call_id, None)
    runtime.b2bua_calls.pop(call.b.call_id, None)
    if call.b_final:
        runtime.b2bua_branches.pop(call.b_branch, None)
    dialogs.forget(call.b.call_id)
    call.on_bye(call)
```

- [ ] **Step 5: Реализовать translate AS**

`app/services/sip-as/ims_sip/services/translate.py`:

```python
"""translate AS: B2BUA с переводом. Нога A — звонящий <-> MRF, нога B — MRF <-> вызываемый."""

from .. import runtime
from ..core import b2bua, mrf, proxy
from ..core.sip import request_method, tag_of, value_of
from ..core.subscribers import language_for, served_user, target_user

HOST = "translate.as"


def strip_star(user: str) -> str:
    """«*номер» разово включает перевод; дальше звонок идёт на номер без префикса."""
    return user[1:] if user.startswith("*") else user


def caller_language(message: str) -> str:
    return language_for(served_user(message), runtime.languages, runtime.default_language)


def on_invite(message: str, peer: tuple[str, int]) -> None:
    callee = strip_star(target_user(message))
    callee_language = language_for(callee, runtime.languages, runtime.default_language)
    languages = (caller_language(message), callee_language)
    request_uri = f"sip:{callee}@{runtime.ims_domain}"
    b2bua.start(message, peer, request_uri, languages, on_answer, on_bye)


def on_answer(call: b2bua.Call, response: str) -> bool:
    """Обе ноги к Voice Agent в режимах своих языков, затем пара в AI Worker."""
    (lang_a, lang_b), a, b = call.languages, call.a, call.b
    if a.media is None:
        return False
    if not mrf.bind_leg(call.a_invite, a.call_id, *a.media, mrf.INTERPRETER_MODES[lang_a]):
        return False
    if not mrf.bind_leg(response, b.call_id, *b.media, mrf.INTERPRETER_MODES[lang_b]):
        mrf.release(a.call_id)
        return False
    mrf.pair((a.call_id, lang_a), (b.call_id, lang_b))
    print(
        f"AS translate answered call_id={a.call_id} leg_b={b.call_id} "
        f"languages={lang_a}-{lang_b}",
        flush=True,
    )
    return True


def on_bye(call: b2bua.Call) -> None:
    if not call.answered:
        return
    for leg in (call.a, call.b):
        mrf.release(leg.call_id)
    mrf.unpair(call.a.call_id)
    print(f"AS translate ended call_id={call.a.call_id}", flush=True)


def handle(message: str, peer: tuple[str, int]) -> None:
    if request_method(message) == "INVITE" and not tag_of(value_of(message, "To")):
        on_invite(message, peer)
        return
    proxy.forward(message, peer)
```

В конец `app/services/sip-as/ims_sip/runtime.py` добавить:

```python
b2bua_calls = {}
b2bua_branches = {}
```

`app/services/sip-as/ims_sip/core/dispatch.py` заменить целиком:

```python
"""Вход SIP AS: запрос — логическому AS по первому Route, ответ — B2BUA или по своему Via."""

from .. import runtime
from ..services import numbers, translate
from . import b2bua
from .proxy import relay_response
from .sip import top_route_host

SERVICES = (translate, numbers)


def service_for(message: str):
    host = top_route_host(message)
    return next((s for s in SERVICES if host == f"{s.HOST}.{runtime.ims_domain}"), None)


def route_request(message: str, peer: tuple[str, int]) -> None:
    (service_for(message) or numbers).handle(message, peer)


def route_response(message: str) -> None:
    if not b2bua.handle_response(message):
        relay_response(message)
```

- [ ] **Step 6: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_*.py' -v`
Expected: `Ran 49 tests` … `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 7: Коммит**

```bash
git add app/services/sip-as/ims_sip/core/b2bua.py app/services/sip-as/ims_sip/core/sip.py \
  app/services/sip-as/ims_sip/core/dispatch.py app/services/sip-as/ims_sip/services/translate.py \
  app/services/sip-as/ims_sip/runtime.py app/tests/unit/test_sip_as_translate.py
git commit -m "feat: translate AS as B2BUA with leg B through S-CSCF"
```

---

### Task 8: B2BUA — BYE с каждой стороны, CANCEL, re-INVITE/UPDATE, повтор INVITE

**Files:**
- Modify: `app/services/sip-as/ims_sip/core/b2bua.py` (импорты и конец файла)
- Modify: `app/services/sip-as/ims_sip/core/transport.py` (`local_response`, импорт)
- Modify: `app/services/sip-as/ims_sip/services/translate.py` (`handle`, импорты)
- Modify: `app/services/sip-as/ims_sip/core/dispatch.py` (`route_request`, импорт)
- Test: `app/tests/unit/test_sip_as_b2bua_teardown.py`

**Interfaces:**
- Consumes: всё из задачи 7.
- Produces:
  - `core.b2bua.same_transaction(message, request) -> bool`, `cancel_b(call) -> None`, `handle_request(message, peer) -> None`
  - `core.transport.local_response`: `Contact` в `200` на `INVITE` и `UPDATE`; `Content-Type: application/sdp` — всегда, когда есть тело
  - Журнал: `AS b2bua refreshed <INVITE|UPDATE> call_id=<id>`, `AS b2bua cancelled call_id=<A>`, `AS b2bua ended call_id=<A> by=<a|b>`

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_sip_as_b2bua_teardown.py`:

```python
"""B2BUA: BYE с каждой стороны, CANCEL до ответа, re-INVITE/UPDATE на своей ноге."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_B,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    load_sip_as,
    request,
    response,
    sdp,
    to_tag_of,
)

load_sip_as()
from ims_sip.core import b2bua
from ims_sip.core.sip import local_tag

AS_URI = f"sip:b2bua@{ENV['SIP_AS_IP']}:{ENV['SIP_AS_PORT']}"
CALLEE_CONTACT = f"<sip:{CALLEE}@192.0.2.20:5060>"
TERM_RR = (f"<sip:mt@scscf.{DOMAIN}:{SCSCF[1]};lr>",)


def call_id_of(message):
    return re.search(r"(?m)^Call-ID: (.+)$", message).group(1).strip()


def from_tag_of(message):
    return re.search(r"(?m)^From: .*;tag=([0-9a-f]+)", message).group(1)


class Teardown(SipCase):
    def start_call(self, call_id="tr-1"):
        self.route_request(invite(CALLEE, call_id, route_host="translate.as"), SCSCF)
        return self.requests("INVITE")[-1]

    def reply_b(self, leg_b, status, reason):
        body = sdp(RTP_IP, RTP_B) if status == 200 else ""
        self.route_response(
            response(
                leg_b,
                status,
                reason,
                to_tag="tb1",
                body=body,
                contact=CALLEE_CONTACT,
                record_routes=TERM_RR,
            )
        )

    def establish(self):
        leg_b = self.start_call()
        self.reply_b(leg_b, 200, "OK")
        return leg_b, call_id_of(leg_b), from_tag_of(leg_b)

    def cancel_a(self, call_id="tr-1"):
        return request(
            "CANCEL",
            call_id,
            uri=f"sip:{CALLEE}@{DOMAIN}",
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            cseq=1,
            branch="z9hG4bK-a1",
            route_host="translate.as",
        )

    def test_bye_from_caller_hangs_up_callee(self):
        _, b, _ = self.establish()
        bye = request(
            "BYE",
            "tr-1",
            uri=AS_URI,
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag=local_tag("tr-1"),
        )
        self.route_request(bye, SCSCF)
        self.assertEqual(self.statuses()[-1], 200)
        [sent_bye] = self.requests("BYE")
        self.assertTrue(sent_bye.startswith(f"BYE sip:{CALLEE}@192.0.2.20:5060 SIP/2.0"))
        self.assertIn(f"Call-ID: {b}", sent_bye)
        self.assertIn("CSeq: 2 BYE", sent_bye)
        self.assertIn(f"Route: {TERM_RR[0]}", sent_bye)
        for call_id in ("tr-1", b):
            self.assertEqual(len(self.http.deleted(f"voice.test/calls/{call_id}")), 1)
        self.assertEqual(len(self.http.deleted("ai.test/pairs/tr-1")), 1)
        self.assertIsNone(b2bua.find("tr-1"))
        self.assertIn("AS b2bua ended call_id=tr-1 by=a", self.log())
        self.assertIn("AS translate ended call_id=tr-1", self.log())

    def test_bye_from_callee_hangs_up_caller(self):
        _, b, b_tag = self.establish()
        bye = request(
            "BYE", b, uri=AS_URI, from_user=CALLEE, from_tag="tb1", to_user=CALLER, to_tag=b_tag
        )
        self.route_request(bye, SCSCF)
        [sent_bye] = self.requests("BYE")
        self.assertTrue(sent_bye.startswith(f"BYE sip:{CALLER}@192.0.2.10:5060 SIP/2.0"))
        self.assertIn("Call-ID: tr-1", sent_bye)
        self.assertIn(f"tag={local_tag('tr-1')}", sent_bye)
        self.assertIn("tag=fa1", sent_bye)
        self.assertIn(f"Route: <sip:mo@scscf.{DOMAIN}", sent_bye)
        self.assertIsNone(b2bua.find(b))
        self.assertIn("AS b2bua ended call_id=tr-1 by=b", self.log())

    def test_cancel_before_answer(self):
        leg_b = self.start_call()
        self.route_response(response(leg_b, 180, "Ringing", to_tag="tb1"))
        self.route_request(self.cancel_a(), SCSCF)
        self.assertEqual(self.statuses(), [100, 180, 200, 487])
        [cancel] = self.requests("CANCEL")
        branch = re.search(r"branch=(z9hG4bK-b2b-[0-9a-f]+)", leg_b).group(1)
        self.assertIn(branch, cancel)
        self.assertIn("CSeq: 1 CANCEL", cancel)
        self.assertIsNone(b2bua.find("tr-1"))
        self.reply_b(leg_b, 487, "Request Terminated")
        self.assertEqual(len(self.requests("ACK")), 1)
        self.assertEqual(self.statuses(), [100, 180, 200, 487])
        self.assertEqual(self.http.posted("voice.test/calls"), [])
        self.assertIn("AS b2bua cancelled call_id=tr-1", self.log())

    def test_answer_after_cancel_is_hung_up(self):
        leg_b = self.start_call()
        self.route_response(response(leg_b, 180, "Ringing", to_tag="tb1"))
        self.route_request(self.cancel_a(), SCSCF)
        self.reply_b(leg_b, 200, "OK")
        self.assertEqual(len(self.requests("ACK")), 1)
        self.assertEqual(len(self.requests("BYE")), 1)
        self.assertEqual(self.statuses(), [100, 180, 200, 487])
        self.assertEqual(self.http.posted("voice.test/calls"), [])

    def test_reinvite_is_answered_locally(self):
        _, b, b_tag = self.establish()
        before = len(self.requests("INVITE"))
        reinvite = request(
            "INVITE",
            b,
            uri=AS_URI,
            from_user=CALLEE,
            from_tag="tb1",
            to_user=CALLER,
            to_tag=b_tag,
            cseq=2,
            branch="z9hG4bK-re1",
            body=sdp(RTP_IP, RTP_B),
        )
        self.route_request(reinvite, SCSCF)
        answer = self.sent()[-1][0]
        self.assertTrue(answer.startswith("SIP/2.0 200 OK"))
        self.assertIn(f"m=audio {ENV['VOICE_AGENT_RTP_PORT']} RTP/AVP 0", answer)
        self.assertIn("Contact: <sip:b2bua@", answer)
        self.assertEqual(len(self.requests("INVITE")), before)
        self.assertEqual(len(self.http.posted("voice.test/calls")), 2)
        self.assertIn(f"AS b2bua refreshed INVITE call_id={b}", self.log())

    def test_update_is_answered_locally(self):
        self.establish()
        update = request(
            "UPDATE",
            "tr-1",
            uri=AS_URI,
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag=local_tag("tr-1"),
            cseq=3,
            branch="z9hG4bK-up1",
            body=sdp(RTP_IP, 4000),
        )
        self.route_request(update, SCSCF)
        answer = self.sent()[-1][0]
        self.assertTrue(answer.startswith("SIP/2.0 200 OK"))
        self.assertIn("Content-Type: application/sdp", answer)
        self.assertIn("Contact: <sip:b2bua@", answer)
        self.assertEqual(self.requests("UPDATE"), [])

    def test_invite_retransmission_gets_trying(self):
        self.start_call()
        self.route_request(invite(CALLEE, "tr-1", route_host="translate.as"), SCSCF)
        self.assertEqual(self.statuses(), [100, 100])
        self.assertEqual(len(self.requests("INVITE")), 1)

    def test_ack_for_rejected_caller_is_absorbed(self):
        leg_b = self.start_call("tr-ack")
        self.reply_b(leg_b, 486, "Busy Here")
        self.assertEqual(to_tag_of(self.sent()[-1][0]), local_tag("tr-ack"))
        before = len(self.sent())
        ack = request(
            "ACK",
            "tr-ack",
            uri=f"sip:{CALLEE}@{DOMAIN}",
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag=local_tag("tr-ack"),
            cseq=1,
            branch="z9hG4bK-a1",
            route_host="translate.as",
        )
        self.route_request(ack, SCSCF)
        self.assertEqual(len(self.sent()), before)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_b2bua_teardown.py' -v`
Expected: FAIL — в `test_bye_from_caller_hangs_up_callee` нет отправленного `BYE`
(`ValueError: not enough values to unpack`), в `test_invite_retransmission_gets_trying` создаётся
вторая нога B.

- [ ] **Step 3: Локальный ответ на UPDATE и тело без INVITE**

В `app/services/sip-as/ims_sip/core/transport.py` заменить строку импорта из `.sip` на
`from .sip import all_headers, header, message_call_id, request_method`, а блок
`if status == 200 and request.startswith("INVITE "):` … до `lines.append(f"Content-Length: …")` на:

```python
    if status == 200 and request_method(request) in {"INVITE", "UPDATE"}:
        user = contact_user or runtime.voice_user
        lines.append(f"Contact: <sip:{user}@{runtime.bind_ip}:{runtime.bind_port};transport=udp>")
    if body:
        lines.append("Content-Type: application/sdp")
    lines.append(f"Content-Length: {len(body.encode())}")
```

- [ ] **Step 4: Запросы внутри диалогов B2BUA**

В `app/services/sip-as/ims_sip/core/b2bua.py` в импорт из `.sip` добавить `request_method` и
`transaction_branch`, а в конец файла:

```python
def same_transaction(message: str, request: str) -> bool:
    return transaction_branch(message) == transaction_branch(request)


def cancel_b(call: Call) -> None:
    """CANCEL ноги B: те же Request-URI, Via, Route, From, To и Call-ID, что у INVITE."""
    head = call.b_invite.split("\r\n\r\n", 1)[0].split("\r\n")
    names = r"(Via|Max-Forwards|Route|From|To|Call-ID)\s*:"
    keep = [line for line in head[1:] if re.match(names, line)]
    lines = [
        f"CANCEL {head[0].split(' ')[1]} SIP/2.0",
        *keep,
        "CSeq: 1 CANCEL",
        "Content-Length: 0",
    ]
    send("\r\n".join(lines) + "\r\n\r\n", runtime.scscf)


def handle_request(message: str, peer: tuple[str, int]) -> None:
    """Запрос в диалоге ноги A или B: ответить на своей ноге, другой — только BYE/CANCEL."""
    call_id = message_call_id(message)
    call = find(call_id)
    method = request_method(message)
    leg = call.a if call_id == call.a.call_id else call.b
    if method == "ACK":
        return
    if method == "INVITE" and leg is call.a and same_transaction(message, call.a_invite):
        send_local_response(message, peer, 100, "Trying")  # повтор INVITE ноги A
        return
    if method in {"INVITE", "UPDATE"}:
        # Удержание и session timer: MRF остаётся точкой медиа, другая нога не трогается.
        send_local_response(
            message,
            peer,
            200,
            "OK",
            body=voice_agent_sdp(),
            to_tag=leg.local_tag,
            contact_user=CONTACT_USER,
        )
        print(f"AS b2bua refreshed {method} call_id={call_id}", flush=True)
        return
    send_local_response(message, peer, 200, "OK", to_tag=leg.local_tag)
    if method == "CANCEL" and leg is call.a and not call.answered:
        reply_a(call, 487, "Request Terminated")
        if not call.b_final:
            cancel_b(call)
        print(f"AS b2bua cancelled call_id={call.a.call_id}", flush=True)
        end(call)
    elif method == "BYE":
        other = call.b if leg is call.a else call.a
        if call.answered:
            send_in_dialog(call, other, "BYE")
        side = "a" if leg is call.a else "b"
        print(f"AS b2bua ended call_id={call.a.call_id} by={side}", flush=True)
        end(call)
```

- [ ] **Step 5: translate и диспетчер передают диалоги в B2BUA**

В `app/services/sip-as/ims_sip/services/translate.py` заменить импорт
`from ..core.sip import request_method, tag_of, value_of` на
`from ..core.sip import local_tag, message_call_id, request_method, tag_of, value_of` и функцию
`handle` на:

```python
def handle(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    method = request_method(message)
    to_tag = tag_of(value_of(message, "To"))
    if b2bua.find(call_id) is not None:
        b2bua.handle_request(message, peer)
    elif method == "INVITE" and not to_tag:
        on_invite(message, peer)
    elif method == "ACK" and to_tag == local_tag(call_id):
        return  # ACK на наш не-2xx ответ ноге A: транзакция уже завершена
    else:
        proxy.forward(message, peer)
```

В `app/services/sip-as/ims_sip/core/dispatch.py` добавить импорт
`from .sip import message_call_id, top_route_host` (вместо `from .sip import top_route_host`) и
заменить `route_request`:

```python
def route_request(message: str, peer: tuple[str, int]) -> None:
    service = service_for(message)
    # BYE/re-INVITE ноги B2BUA приходят на Contact SIP AS, без Route логического AS.
    if service is None and b2bua.find(message_call_id(message)) is not None:
        b2bua.handle_request(message, peer)
        return
    (service or numbers).handle(message, peer)
```

- [ ] **Step 6: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_*.py' -v`
Expected: `Ran 57 tests` … `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 7: Коммит**

```bash
git add app/services/sip-as/ims_sip/core/b2bua.py app/services/sip-as/ims_sip/core/transport.py \
  app/services/sip-as/ims_sip/core/dispatch.py app/services/sip-as/ims_sip/services/translate.py \
  app/tests/unit/test_sip_as_b2bua_teardown.py
git commit -m "feat: B2BUA teardown, CANCEL and local re-INVITE handling"
```

---

### Task 9: translate AS — прозрачный режим и `*номер`

**Files:**
- Modify: `app/services/sip-as/ims_sip/services/translate.py` (весь файл)
- Test: `app/tests/unit/test_sip_as_translate_bypass.py`

**Interfaces:**
- Consumes: `core.mrf.free_slots`, `media_is_anchored`; `core.sdp.accepts_pcmu`, `offered_media_endpoint`; `core.dialogs.is_own`; `core.proxy.forward`; `runtime.service_targets`, `runtime.languages`.
- Produces:
  - `services.translate.LEGS_PER_CALL = 2`, `STAR` (regex `*` в Request-URI)
  - `services.translate.bypass_reason(message) -> str | None` — одно из `own_leg`, `service_number`, `unknown_callee`, `same_language`, `media`, `no_mrf`
  - `services.translate.bypass(message, peer, reason) -> None`
  - Журнал: `AS translate bypass call_id=<id> reason=<причина>`

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_sip_as_translate_bypass.py`:

```python
"""translate AS без перевода: прозрачный прокси с причиной в журнале, без 503 звонящему."""

import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_B,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    load_sip_as,
    response,
    sdp,
)

load_sip_as()
from ims_sip.core import b2bua, dialogs

SAME_LANGUAGE = ENV["UE1_MSISDN"]  # ru, как у SIPUE1


class Bypass(SipCase):
    def call(self, target, call_id, **options):
        self.route_request(invite(target, call_id, route_host="translate.as", **options), SCSCF)

    def assert_bypassed(self, call_id, reason):
        [forwarded] = self.requests("INVITE")
        self.assertIn("branch=z9hG4bK-as-", forwarded)
        self.assertIsNone(b2bua.find(call_id))
        self.assertEqual(self.statuses(), [])
        self.assertIn(f"AS translate bypass call_id={call_id} reason={reason}", self.log())
        return forwarded

    def test_same_language_is_proxied(self):
        self.call(SAME_LANGUAGE, "by-1")
        forwarded = self.assert_bypassed("by-1", "same_language")
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")

    def test_service_number_passes_unchanged(self):
        self.call(ENV["VOICE_TRANSLATOR_MSISDN"], "by-2")
        forwarded = self.assert_bypassed("by-2", "service_number")
        self.assertTrue(forwarded.startswith(f"INVITE sip:{ENV['VOICE_TRANSLATOR_MSISDN']}@"))

    def test_unknown_callee(self):
        self.call("5550000", "by-3")
        self.assert_bypassed("by-3", "unknown_callee")

    def test_own_leg_passes(self):
        call_id = dialogs.new_call_id()
        self.call(CALLEE, call_id)
        self.assert_bypassed(call_id, "own_leg")

    def test_unanchored_media(self):
        self.call(CALLEE, "by-5", ip="198.51.100.7")
        self.assert_bypassed("by-5", "media")

    def test_no_free_mrf_slots(self):
        max_calls = int(ENV["VOICE_AGENT_MAX_CALLS"])
        self.http.voice_calls = {f"c{index}": {} for index in range(max_calls - 1)}
        self.call(CALLEE, "by-6")
        self.assert_bypassed("by-6", "no_mrf")

    def test_voice_status_down_counts_as_no_mrf(self):
        self.http.fail.add("voice.test/status")
        self.call(CALLEE, "by-7")
        self.assert_bypassed("by-7", "no_mrf")

    def test_star_bypass_strips_prefix(self):
        self.call(f"*{SAME_LANGUAGE}", "by-8")
        forwarded = self.assert_bypassed("by-8", "same_language")
        self.assertTrue(forwarded.startswith(f"INVITE sip:{SAME_LANGUAGE}@{DOMAIN} SIP/2.0"))

    def test_star_from_subscriber_without_translate(self):
        self.call(f"*{CALLER}", "by-9", caller=ENV["SIPUE2_MSISDN"])
        [leg_b] = self.requests("INVITE")
        self.assertTrue(leg_b.startswith(f"INVITE sip:{CALLER}@{DOMAIN} SIP/2.0"))
        answer = response(
            leg_b,
            200,
            "OK",
            to_tag="tb1",
            body=sdp(RTP_IP, RTP_B),
            contact=f"<sip:{CALLER}@192.0.2.20:5060>",
        )
        self.route_response(answer)
        self.assertRegex(
            self.log(), r"AS translate answered call_id=by-9 leg_b=b2b-[0-9a-f]+ languages=en-ru"
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_translate_bypass.py' -v`
Expected: FAIL — `AS translate bypass ...` нет в журнале, для `by-1`/`by-2` создаётся нога B.

- [ ] **Step 3: Реализовать прозрачный режим**

`app/services/sip-as/ims_sip/services/translate.py` заменить целиком:

```python
"""translate AS: B2BUA с переводом или прозрачный прокси, если переводить нечего или нечем.

Нога A — звонящий <-> MRF, нога B — MRF <-> вызываемый. Без перевода звонок идёт
дальше по цепочке iFC как обычный: звонящий не получает 503.
"""

import re

from .. import runtime
from ..core import b2bua, dialogs, mrf, proxy
from ..core.mrf import media_is_anchored
from ..core.sdp import accepts_pcmu, offered_media_endpoint
from ..core.sip import local_tag, message_call_id, request_method, tag_of, value_of
from ..core.subscribers import language_for, served_user, target_user

HOST = "translate.as"
LEGS_PER_CALL = 2  # нога A и нога B занимают два места Voice Agent
STAR = re.compile(r"^(\S+ (?:sips?|tel):)\*")


def strip_star(user: str) -> str:
    """«*номер» разово включает перевод; дальше звонок идёт на номер без префикса."""
    return user[1:] if user.startswith("*") else user


def caller_language(message: str) -> str:
    return language_for(served_user(message), runtime.languages, runtime.default_language)


def bypass_reason(message: str) -> str | None:
    """Почему звонок идёт без перевода; None — переводить."""
    if dialogs.is_own(message_call_id(message)):
        return "own_leg"
    callee = strip_star(target_user(message))
    if callee in runtime.service_targets:
        return "service_number"
    if callee not in runtime.languages:
        return "unknown_callee"
    if caller_language(message) == runtime.languages[callee]:
        return "same_language"
    endpoint = offered_media_endpoint(message)
    if endpoint is None or not accepts_pcmu(message) or not media_is_anchored(*endpoint):
        return "media"
    if mrf.free_slots() < LEGS_PER_CALL:
        return "no_mrf"
    return None


def bypass(message: str, peer: tuple[str, int], reason: str) -> None:
    print(f"AS translate bypass call_id={message_call_id(message)} reason={reason}", flush=True)
    proxy.forward(STAR.sub(r"\1", message, count=1), peer)


def on_invite(message: str, peer: tuple[str, int]) -> None:
    reason = bypass_reason(message)
    if reason is not None:
        bypass(message, peer, reason)
        return
    callee = strip_star(target_user(message))
    languages = (caller_language(message), runtime.languages[callee])
    request_uri = f"sip:{callee}@{runtime.ims_domain}"
    b2bua.start(message, peer, request_uri, languages, on_answer, on_bye)


def on_answer(call: b2bua.Call, response: str) -> bool:
    """Обе ноги к Voice Agent в режимах своих языков, затем пара в AI Worker."""
    (lang_a, lang_b), a, b = call.languages, call.a, call.b
    if a.media is None:
        return False
    if not mrf.bind_leg(call.a_invite, a.call_id, *a.media, mrf.INTERPRETER_MODES[lang_a]):
        return False
    if not mrf.bind_leg(response, b.call_id, *b.media, mrf.INTERPRETER_MODES[lang_b]):
        mrf.release(a.call_id)
        return False
    mrf.pair((a.call_id, lang_a), (b.call_id, lang_b))
    print(
        f"AS translate answered call_id={a.call_id} leg_b={b.call_id} "
        f"languages={lang_a}-{lang_b}",
        flush=True,
    )
    return True


def on_bye(call: b2bua.Call) -> None:
    if not call.answered:
        return
    for leg in (call.a, call.b):
        mrf.release(leg.call_id)
    mrf.unpair(call.a.call_id)
    print(f"AS translate ended call_id={call.a.call_id}", flush=True)


def handle(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    method = request_method(message)
    to_tag = tag_of(value_of(message, "To"))
    if b2bua.find(call_id) is not None:
        b2bua.handle_request(message, peer)
    elif method == "INVITE" and not to_tag:
        on_invite(message, peer)
    elif method == "ACK" and to_tag == local_tag(call_id):
        return  # ACK на наш не-2xx ответ ноге A: транзакция уже завершена
    else:
        proxy.forward(message, peer)
```

- [ ] **Step 4: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_*.py' -v`
Expected: `Ran 66 tests` … `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 5: Коммит**

```bash
git add app/services/sip-as/ims_sip/services/translate.py app/tests/unit/test_sip_as_translate_bypass.py
git commit -m "feat: translate AS bypass and star-prefix one-off translation"
```

---

### Task 10: AI Worker — запись обеих сторон и режим `record`

**Files:**
- Modify: `app/services/ai-worker/ims_ai/runtime.py` (после `pairs = {}`)
- Modify: `app/services/ai-worker/ims_ai/api.py` (импорт и конец файла)
- Modify: `app/services/ai-worker/ims_ai/recording.py` (конец файла)
- Modify: `app/services/ai-worker/ims_ai/transcription.py` (весь файл)
- Modify: `app/services/ai-worker/ims_ai/lifecycle.py:13-18` (`FINALIZED_RECORDING_MODES`), `:105-112` (`finalize_call`), импорт
- Modify: `app/services/ai-worker/ims_ai/segmentation.py:16` (`DIALOGUE_MODES`)
- Modify: `app/services/ai-worker/ims_ai/utterances.py:29-34` (`requested_language`)
- Modify: `app/services/ai-worker/ims_ai/settings.py:122-130` (`service_modes`)
- Modify: `app/services/media-adapter/ims_media/runtime.py` (`allowed_service_modes`)
- Modify: `app/tests/unit/test_media_routing.py` (новый тест в конец класса)
- Test: `app/tests/unit/test_ai_recording.py`

**Interfaces:**
- Consumes: `recording.recording_session`, `save_recording_turn` (как есть); `runtime.pairs` (задача 6).
- Produces:
  - HTTP `POST /recordings` `{"session_call_id": str, "legs": [{"call_id": str, "speaker": "caller"|"callee"}]}` → `202`
  - `ims_ai.api.SPEAKERS = {"caller", "callee"}`
  - `ims_ai.runtime.record_legs: dict[str, dict]`, `record_sessions: dict[str, set[str]]`, `recording_lock: threading.Lock`
  - `recording.add_recording_legs(session_call_id, legs: list[tuple[str, str]]) -> None`
  - `recording.recording_target(call_id, service_mode, event) -> tuple[str, str] | None` — (ключ записи, говорящий)
  - `recording.finished_recording(call_id) -> str | None` — ключ записи, которую можно закрыть
  - режим `record` в `settings.service_modes`, `segmentation.DIALOGUE_MODES`, `lifecycle.FINALIZED_RECORDING_MODES`, `ims_media.runtime.allowed_service_modes`; `utterances.requested_language("record") is None`

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_ai_recording.py`:

```python
"""AI Worker: запись обеих ног перевода в одну сессию и режим record (как у 1004)."""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app/services/ai-worker"))


class Recording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        token = Path(cls.temp.name) / "token"
        token.write_text("unit-test-token", encoding="ascii")
        env = {}
        for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env.update(SERVICE_CONTROL_TOKEN_FILE=str(token), VOICE_AGENT_URL="http://localhost")
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        with patch("socket.socket"):
            from ims_ai import (
                api,
                lifecycle,
                runtime,
                segmentation,
                settings,
                transcription,
                utterances,
            )
        cls.lifecycle, cls.runtime, cls.settings = lifecycle, runtime, settings
        cls.segmentation, cls.transcription = segmentation, transcription
        cls.utterances = utterances
        cls.client = api.api.test_client()
        cls.headers = {"Authorization": f"Bearer {runtime.control_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        for name, value in (
            ("recording_root", self.root),
            ("recording_enabled", True),
            ("transcript_normalization", "raw"),
        ):
            patcher = patch.object(self.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("record_legs", "record_sessions", "recordings"):
            getattr(self.runtime, name).clear()

    def register(self, session, legs):
        payload = {"session_call_id": session, "legs": legs}
        return self.client.post("/recordings", json=payload, headers=self.headers)

    def register_pair(self):
        legs = [
            {"call_id": "leg-a", "speaker": "caller"},
            {"call_id": "leg-b", "speaker": "callee"},
        ]
        return self.register("leg-a", legs)

    def turn(self, call_id, mode, transcript, language, stream="s1"):
        event = {"call_ids": [call_id], "source_stream_id": stream}
        result = {
            "service_mode": mode,
            "audio_duration_seconds": 0.02,
            "audio_sha256": "0" * 64,
            "detected_language": language,
        }
        self.transcription.record_transcript(b"\xff" * 160, event, result, transcript, language)

    def session_dir(self, call_id):
        return self.root / hashlib.sha256(call_id.encode()).hexdigest()[:20]

    def transcript_lines(self, call_id):
        text = (self.session_dir(call_id) / "transcript.txt").read_text(encoding="utf-8")
        return text.splitlines()

    def test_register_recording_maps_legs(self):
        self.assertEqual(self.register_pair().status_code, 202)
        self.assertEqual(self.runtime.record_legs["leg-b"]["session_call_id"], "leg-a")
        self.assertEqual(self.runtime.record_sessions["leg-a"], {"leg-a", "leg-b"})

    def test_invalid_recording_is_rejected(self):
        cases = [
            ("leg-a", [{"call_id": "leg-a", "speaker": "agent"}]),
            ("bad id", [{"call_id": "leg-a", "speaker": "caller"}]),
            ("leg-a", [{"call_id": f"leg-{n}", "speaker": "caller"} for n in range(3)]),
        ]
        for session, legs in cases:
            with self.subTest(session=session, legs=len(legs)):
                self.assertEqual(self.register(session, legs).status_code, 400)

    def test_both_legs_write_one_transcript(self):
        self.register_pair()
        self.turn("leg-a", "interpret_ru", "Привет", "ru")
        self.turn("leg-b", "interpret_en", "Hello", "en")
        lines = self.transcript_lines("leg-a")
        self.assertTrue(lines[0].startswith("[caller/ru]"))
        self.assertTrue(lines[1].startswith("[callee/en]"))
        self.assertFalse(self.session_dir("leg-b").exists())

    def test_unregistered_interpreter_leg_is_not_recorded(self):
        self.turn("ru-1", "interpret_ru", "Привет", "ru")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pair_recording_closes_after_last_leg(self):
        self.register_pair()
        self.turn("leg-a", "interpret_ru", "Привет", "ru")
        self.turn("leg-b", "interpret_en", "Hello", "en")
        self.lifecycle.finalize_call("leg-a")
        self.assertFalse((self.session_dir("leg-a") / "completed.json").exists())
        self.lifecycle.finalize_call("leg-b")
        self.assertTrue((self.session_dir("leg-a") / "completed.json").exists())
        self.assertEqual(self.runtime.record_sessions, {})

    def test_record_mode_labels_two_streams(self):
        self.turn("rec-1", "record", "Привет", "ru", stream="s1")
        self.turn("rec-1", "record", "Hello", "en", stream="s2")
        lines = self.transcript_lines("rec-1")
        self.assertTrue(lines[0].startswith("[speaker_1/ru]"))
        self.assertTrue(lines[1].startswith("[speaker_2/en]"))

    def test_record_mode_is_known_everywhere(self):
        self.assertIn("record", self.settings.service_modes)
        self.assertTrue(self.segmentation.is_dialogue_mode("record"))
        self.assertIn("record", self.lifecycle.FINALIZED_RECORDING_MODES)
        self.assertIsNone(self.utterances.requested_language("record"))

    def test_transcribe_still_records_caller(self):
        self.turn("t-1", "transcribe", "Привет", "ru")
        self.assertTrue(self.transcript_lines("t-1")[0].startswith("[caller/ru]"))


if __name__ == "__main__":
    unittest.main()
```

В конец класса `MediaRouting` в `app/tests/unit/test_media_routing.py` добавить:

```python
    def test_record_mode_is_allowed(self):
        self.assertIn("record", self.rtpengine.runtime.allowed_service_modes)
```

- [ ] **Step 2: Запустить тесты — падают**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_ai_recording.py' -v`
Expected: ERROR/FAIL — `/recordings` отвечает `404`, `AttributeError: ... 'record_legs'`.

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_media_routing.py' -v`
Expected: FAIL — `'record' not found in {...}` в `test_record_mode_is_allowed`.

- [ ] **Step 3: Состояние и API записи**

В `app/services/ai-worker/ims_ai/runtime.py` после строки `pairs = {}` добавить:

```python
record_legs = {}
record_sessions = {}
recording_lock = threading.Lock()
```

В `app/services/ai-worker/ims_ai/api.py` после `from .maintenance import expire_events`
добавить `from .recording import add_recording_legs`, а в конец файла:

```python
SPEAKERS = {"caller", "callee"}


@api.post("/recordings")
def register_recording():
    """SIP AS (record + translate) просит писать обе ноги звонка в одну запись."""
    data = json_object(4096)
    session_call_id = data.get("session_call_id")
    legs = data.get("legs")
    require(valid_call_id(session_call_id))
    require(isinstance(legs, list) and 1 <= len(legs) <= 2)
    require(
        all(
            isinstance(leg, dict)
            and valid_call_id(leg.get("call_id"))
            and leg.get("speaker") in SPEAKERS
            for leg in legs
        )
    )
    with runtime.lock:
        add_recording_legs(session_call_id, [(leg["call_id"], leg["speaker"]) for leg in legs])
    print(f"AI recording_registered legs={len(legs)}", flush=True)
    return "", 202
```

В конец `app/services/ai-worker/ims_ai/recording.py` добавить:

```python
def add_recording_legs(session_call_id, legs):
    """Ноги одного звонка пишутся в одну запись; закрыть её можно после последней ноги."""
    runtime.record_sessions.setdefault(session_call_id, set()).update(cid for cid, _ in legs)
    for call_id, speaker in legs:
        runtime.record_legs[call_id] = {"session_call_id": session_call_id, "speaker": speaker}


def recording_target(call_id, service_mode, event):
    """(ключ записи, говорящий) для реплики или None — эту ногу не записывают."""
    leg = runtime.record_legs.get(call_id)
    if leg is not None:
        return leg["session_call_id"], leg["speaker"]
    if service_mode == "transcribe":
        return call_id, "caller"
    if service_mode in {"bilingual_test", "record"}:
        recording = recording_session(call_id)
        source_key = event.get("source_stream_id") or str(event.get("ssrc"))
        speaker = recording["speakers"].setdefault(
            source_key, f"speaker_{len(recording['speakers']) + 1}"
        )
        return call_id, speaker
    return None


def finished_recording(call_id):
    """Ключ записи, которую закрывает конец этой ноги; None — другие ноги ещё говорят."""
    leg = runtime.record_legs.pop(call_id, None)
    if leg is None:
        return call_id
    session_call_id = leg["session_call_id"]
    remaining = runtime.record_sessions.get(session_call_id, set())
    remaining.discard(call_id)
    if remaining:
        return None
    runtime.record_sessions.pop(session_call_id, None)
    return session_call_id
```

- [ ] **Step 4: Сохранение реплики по цели записи**

`app/services/ai-worker/ims_ai/transcription.py` заменить целиком:

```python
"""Сохранение реплики: нормализация, метка спикера и приватная запись."""

from __future__ import annotations

from . import runtime, settings
from .audio import decode_pcm8
from .llm import (
    cyrillic_chars,
    normalize_transcript,
)
from .recording import recording_target, save_recording_turn


def record_transcript(ulaw, event, result, transcript, detected_language):
    service_mode = result["service_mode"]
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else None
    target = recording_target(call_id, service_mode, event) if call_id else None
    if target is None:
        return
    session_call_id, speaker = target

    normalized_transcript = transcript
    if transcript and settings.transcript_normalization == "raw":
        result.update({"normalization_applied": False, "transcript_kind": "raw_asr"})
    elif transcript:
        try:
            normalized_transcript, normalization_ms = normalize_transcript(
                transcript, detected_language
            )
            result.update(
                {
                    "normalization_applied": True,
                    "normalization_llm_model": settings.llm_model,
                    "normalization_processing_ms": normalization_ms,
                    "normalized_transcript_chars": len(normalized_transcript),
                    "normalized_transcript_cyrillic_chars": cyrillic_chars(normalized_transcript),
                }
            )
            print(
                f"AI transcript_normalized model={settings.llm_model} input_chars={len(transcript)} "
                f"output_chars={len(normalized_transcript)} llm_ms={normalization_ms:.3f} "
                f"calls={call_ids}",
                flush=True,
            )
        except Exception as exc:
            # Fail closed for text persistence: keep the WAV so the turn can
            # be reprocessed, but never label raw STT output as normalized.
            normalized_transcript = ""
            result.update(
                {
                    "normalization_applied": False,
                    "normalization_error_type": type(exc).__name__,
                }
            )
            print(
                f"AI transcript_normalization_failed model={settings.llm_model} "
                f"type={type(exc).__name__} calls={call_ids}",
                flush=True,
            )
    # Две ноги одного звонка пишут в один каталог из разных обработчиков.
    with runtime.recording_lock:
        saved = save_recording_turn(
            session_call_id, decode_pcm8(ulaw), normalized_transcript, result, speaker
        )
    if saved:
        result.update(
            {
                "recording_session_id": saved["session_id"],
                "recording_saved": saved["saved"],
                "recording_turn": saved.get("turn"),
                "recording_limit_reached": saved.get("limit_reached", False),
            }
        )
```

- [ ] **Step 5: Режим `record` и закрытие записи после последней ноги**

`app/services/ai-worker/ims_ai/lifecycle.py`: строки 13–18 заменить на

```python
FINALIZED_RECORDING_MODES = {
    "transcribe",
    "bilingual_test",
    "interpret_ru",
    "interpret_en",
    "record",
}
```

в импортах после `from .queueing import enqueue_utterance, wait_for_call` добавить
`from .recording import finished_recording`, а функцию `finalize_call` заменить на:

```python
def finalize_call(call_id: str) -> None:
    """Завершить хвост аудио, запись и память одного SIP-диалога."""
    # SIP endpoints commonly suppress RTP during silence. Flush the last
    # transcription turn on BYE because no trailing silent frames may arrive.
    flush_buffered_speech(call_id)
    wait_for_call(call_id)
    # Запись пары закрывается концом последней ноги, а не первой.
    session_call_id = finished_recording(call_id)
    if session_call_id is not None:
        finalize_recording(session_call_id)
    clear_call_state(call_id)
```

`app/services/ai-worker/ims_ai/segmentation.py`, строку 16 заменить на:

```python
DIALOGUE_MODES = {"bilingual_test", "interpret_ru", "interpret_en", "record"}
```

`app/services/ai-worker/ims_ai/utterances.py`, функцию `requested_language` (строки 29–34)
заменить на:

```python
def requested_language(service_mode: str) -> str | None:
    """Режим переводчика задаёт язык входной ноги; диалог и запись определяют его сами."""
    language = source_language(service_mode)
    if language is None and service_mode not in {"bilingual_test", "record"}:
        language = settings.language or None
    return language
```

`app/services/ai-worker/ims_ai/settings.py`, множество `service_modes` (строки 122–130)
заменить на:

```python
service_modes = {
    "observe",
    "translate",
    "transcribe",
    "assistant",
    "bilingual_test",
    "interpret_ru",
    "interpret_en",
    "record",
}
```

`app/services/media-adapter/ims_media/runtime.py`, множество `allowed_service_modes`
заменить на:

```python
allowed_service_modes = {
    "observe",
    "translate",
    "transcribe",
    "assistant",
    "bilingual_test",
    "interpret_ru",
    "interpret_en",
    "record",
}
```

- [ ] **Step 6: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_ai_recording.py' -v`
Expected: `Ran 8 tests` … `OK`.

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit`
Expected: `OK` (в том числе `test_phrase_boundaries.py`: хвосты 1004 и интерпретатора закрываются как раньше).

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 7: Коммит**

```bash
git add app/services/ai-worker/ims_ai app/services/media-adapter/ims_media/runtime.py \
  app/tests/unit/test_ai_recording.py app/tests/unit/test_media_routing.py
git commit -m "feat: two-leg recording sessions and record mode in AI Worker"
```

---

### Task 11: Уведомление о записи — WAV от Voice Agent и `play media` в RTPengine

**Files:**
- Modify: `app/services/voice-agent/ims_voice/audio.py` (импорт, конец файла)
- Modify: `app/services/voice-agent/ims_voice/runtime.py` (после `reply_max_chars`)
- Modify: `app/services/voice-agent/ims_voice/api.py` (импорты, `reply`, конец файла)
- Modify: `app/services/media-adapter/ims_media/rtpengine.py` (конец файла)
- Modify: `app/services/media-adapter/ims_media/runtime.py` (после `worker_url`)
- Modify: `app/services/media-adapter/ims_media/api.py` (импорты, конец файла)
- Modify: `app/infrastructure/compose/ai.yml:76`
- Modify: `app/tests/unit/test_media_routing.py:24-27` (`env.update`)
- Test: `app/tests/unit/test_announcements.py`

**Interfaces:**
- Consumes: `ims_voice.audio.synthesize(text, voice) -> bytes` (PCMU), `ims_voice.media.enqueue_audio(call_id, text, reason, voice, reply_id=None) -> bool`, `ims_media.rtpengine._decode`.
- Produces:
  - `ims_voice.audio.ulaw_wav(payload: bytes) -> bytes` (WAV, формат 7 — G.711 µ-law, 8000 Гц, моно)
  - `ims_voice.runtime.announcement_max_bytes = 48000`
  - HTTP Voice Agent `POST /announcements` `{"text", "voice"}` → `200 {"wav_base64": str}`; `413`, если звук длиннее 6 с
  - HTTP Voice Agent `POST /calls/<id>/reply` принимает `reason` из `ims_voice.api.REPLY_REASONS = {"llm_reply", "announcement"}` (по умолчанию `llm_reply`)
  - `ims_voice.api.spoken_text(data) -> str`
  - `ims_media.rtpengine._encode(value) -> bytes`, `_command(payload: dict) -> dict`, `play_media(call_id: str, from_tag: str, blob: bytes) -> int | None`
  - `ims_media.runtime.voice_agent_url: str`
  - HTTP Media Adapter `POST /sessions/<call_id>/announce` `{"parties": [{"tag", "text", "voice"}]}` → `204`; `502` при ошибке TTS/RTPengine
  - `ims_media.api.TAG` (regex SIP tag), `ims_media.api.fetch_announcement(text, voice) -> bytes`
  - Журнал: `MEDIA announced call_id=<id> parties=<n>`, `MEDIA announce_failed call_id=<id> type=<класс>`

- [ ] **Step 1: Написать падающий тест**

`app/tests/unit/test_announcements.py`:

```python
"""Уведомление о записи: WAV µ-law от Voice Agent и команда play media в RTPengine."""

import base64
import importlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class FakeSocket:
    """NG-сокет RTPengine: отвечает тем же cookie, что пришёл в запросе."""

    def __init__(self, reply=b"d6:result2:oke"):
        self.sent, self.reply = [], reply

    def settimeout(self, value):
        return None

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recv(self, size):
        return self.sent[-1][0].split(b" ", 1)[0] + b" " + self.reply

    def close(self):
        return None


class Announcements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        token = Path(cls.temp.name) / "token"
        token.write_text("unit-test-token", encoding="ascii")
        env = {}
        for line in (ROOT / "app/config/lab.env").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env.update(
            SERVICE_CONTROL_TOKEN_FILE=str(token),
            AI_WORKER_URL="http://localhost",
            VOICE_AGENT_URL="http://localhost",
        )
        cls.environment = patch.dict(os.environ, env)
        cls.environment.start()
        for service in ("voice-agent", "media-adapter"):
            sys.path.insert(0, str(ROOT / "app/services" / service))
        with patch("socket.socket"):
            cls.voice_api = importlib.import_module("ims_voice.api")
            cls.audio = importlib.import_module("ims_voice.audio")
            cls.media_api = importlib.import_module("ims_media.api")
            cls.rtpengine = importlib.import_module("ims_media.rtpengine")
        cls.voice = cls.voice_api.api.test_client()
        cls.media = cls.media_api.api.test_client()
        cls.headers = {"Authorization": f"Bearer {cls.voice_api.runtime.control_token}"}
        cls.tts_voice = cls.voice_api.runtime.tts_voice

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def test_ulaw_wav_header(self):
        wav = self.audio.ulaw_wav(b"\x7f" * 10)
        self.assertEqual((wav[:4], wav[8:12], wav[12:16]), (b"RIFF", b"WAVE", b"fmt "))
        self.assertEqual(struct.unpack("<HHIIHH", wav[20:34]), (7, 1, 8000, 8000, 1, 8))
        self.assertEqual(struct.unpack("<I", wav[4:8])[0], len(wav) - 8)
        self.assertTrue(wav.endswith(b"data" + struct.pack("<I", 10) + b"\x7f" * 10))

    def test_announcement_returns_wav(self):
        with patch.object(self.voice_api, "synthesize", return_value=b"\xff" * 800) as tts:
            response = self.voice.post(
                "/announcements",
                json={"text": "Внимание", "voice": self.tts_voice},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        wav = base64.b64decode(response.get_json()["wav_base64"])
        self.assertEqual(wav[:4], b"RIFF")
        tts.assert_called_once_with("Внимание", self.tts_voice)

    def test_long_announcement_is_rejected(self):
        too_long = b"\xff" * (self.voice_api.runtime.announcement_max_bytes + 1)
        with patch.object(self.voice_api, "synthesize", return_value=too_long):
            response = self.voice.post(
                "/announcements", json={"text": "Внимание"}, headers=self.headers
            )
        self.assertEqual(response.status_code, 413)

    def test_unknown_voice_is_rejected(self):
        response = self.voice.post(
            "/announcements", json={"text": "Внимание", "voice": "xx"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_reply_accepts_announcement_reason(self):
        self.voice_api.runtime.calls["ann-1"] = {}
        self.addCleanup(self.voice_api.runtime.calls.pop, "ann-1", None)
        with patch.object(self.voice_api, "enqueue_audio", return_value=True) as enqueue:
            response = self.voice.post(
                "/calls/ann-1/reply",
                json={"text": "Внимание", "voice": self.tts_voice, "reason": "announcement"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once_with("ann-1", "Внимание", "announcement", self.tts_voice, None)

    def test_reply_rejects_unknown_reason(self):
        self.voice_api.runtime.calls["ann-2"] = {}
        self.addCleanup(self.voice_api.runtime.calls.pop, "ann-2", None)
        response = self.voice.post(
            "/calls/ann-2/reply",
            json={"text": "Внимание", "reason": "greeting"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_encode_matches_decoder(self):
        encoded = self.rtpengine._encode({"command": "play media", "blob": b"ab", "n": 3})
        decoded, end = self.rtpengine._decode(encoded)
        self.assertEqual(end, len(encoded))
        self.assertEqual(decoded, {b"blob": b"ab", b"command": b"play media", b"n": 3})

    def test_command_checks_cookie_and_result(self):
        fake = FakeSocket()
        with patch.object(self.rtpengine.socket, "socket", return_value=fake):
            self.assertEqual(self.rtpengine._command({"command": "ping"}), {b"result": b"ok"})
        data, address = fake.sent[0]
        self.assertTrue(data.endswith(b" d7:command4:pinge"))
        runtime = self.rtpengine.runtime
        self.assertEqual(address, (runtime.rtpengine_ip, runtime.rtpengine_ng_port))
        failing = FakeSocket(reply=b"d6:result5:errore")
        with patch.object(self.rtpengine.socket, "socket", return_value=failing):
            with self.assertRaises(ValueError):
                self.rtpengine._command({"command": "ping"})

    def test_play_media_command(self):
        reply = {b"result": b"ok", b"duration": 2000}
        with patch.object(self.rtpengine, "_command", return_value=reply) as command:
            self.assertEqual(self.rtpengine.play_media("c1", "fa1", b"RIFF"), 2000)
        command.assert_called_once_with(
            {"command": "play media", "call-id": "c1", "from-tag": "fa1", "blob": b"RIFF"}
        )

    def test_announce_plays_to_each_party(self):
        parties = [
            {"tag": "fa1", "text": "Внимание", "voice": "ru"},
            {"tag": "tb1", "text": "Attention", "voice": "en-us"},
        ]
        with (
            patch.object(self.media_api, "fetch_announcement", return_value=b"RIFFwav"),
            patch.object(self.media_api, "play_media") as play,
        ):
            response = self.media.post(
                "/sessions/c1/announce", json={"parties": parties}, headers=self.headers
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            [call.args for call in play.call_args_list],
            [("c1", "fa1", b"RIFFwav"), ("c1", "tb1", b"RIFFwav")],
        )

    def test_announce_failure_is_502(self):
        parties = [{"tag": "fa1", "text": "Внимание", "voice": "ru"}]
        with (
            patch.object(self.media_api, "fetch_announcement", return_value=b"RIFFwav"),
            patch.object(self.media_api, "play_media", side_effect=ValueError("rtpengine")),
        ):
            response = self.media.post(
                "/sessions/c2/announce", json={"parties": parties}, headers=self.headers
            )
        self.assertEqual(response.status_code, 502)

    def test_announce_rejects_bad_tag(self):
        parties = [{"tag": "bad tag", "text": "Внимание", "voice": "ru"}]
        response = self.media.post(
            "/sessions/c3/announce", json={"parties": parties}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
```

В `app/tests/unit/test_media_routing.py` строки 24–27 (`env.update(...)`) заменить на:

```python
        env.update(
            SERVICE_CONTROL_TOKEN_FILE=str(token),
            AI_WORKER_URL="http://localhost:8092",
            VOICE_AGENT_URL="http://localhost:8093",
        )
```

- [ ] **Step 2: Запустить тест — он падает**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_announcements.py' -v`
Expected: ERROR/FAIL — `AttributeError: module 'ims_voice.audio' has no attribute 'ulaw_wav'`,
`/announcements` отвечает `404`.

- [ ] **Step 3: Voice Agent — WAV уведомления и причина `announcement`**

В `app/services/voice-agent/ims_voice/audio.py` после `import os` добавить `import struct`, а в
конец файла:

```python
def ulaw_wav(payload: bytes) -> bytes:
    """Обернуть PCMU в WAV (формат 7, G.711 µ-law): так его играет RTPengine play media."""
    fmt = struct.pack("<HHIIHHH", 7, 1, 8000, 8000, 1, 8, 0)
    padding = b"\0" if len(payload) % 2 else b""
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"fact"
        + struct.pack("<II", 4, len(payload))
        + b"data"
        + struct.pack("<I", len(payload))
        + payload
        + padding
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body
```

В `app/services/voice-agent/ims_voice/runtime.py` после строки
`reply_max_chars = int(os.environ["VOICE_AGENT_REPLY_MAX_CHARS"])` добавить:

```python
# 6 с PCMU: WAV уведомления уходит в RTPengine одной UDP-датаграммой NG.
announcement_max_bytes = 48000
```

В `app/services/voice-agent/ims_voice/api.py` заменить строку `import ipaddress` на

```python
import base64
import ipaddress
```

после `from . import calls, runtime` добавить `from .audio import synthesize, ulaw_wav`,
функцию `reply` заменить на:

```python
REPLY_REASONS = {"llm_reply", "announcement"}


def spoken_text(data: dict) -> str:
    require(isinstance(data.get("text"), str))
    text = " ".join(data["text"].split())
    require(bool(text) and len(text) <= runtime.reply_max_chars)
    require(not any(ord(char) < 32 for char in text))
    return text


@api.post("/calls/<call_id>/reply")
def reply(call_id):
    require(valid_call_id(call_id))
    data = json_object()
    text = spoken_text(data)
    voice = data.get("voice", runtime.tts_voice)
    reason = data.get("reason", "llm_reply")
    reply_id = data.get("reply_id")
    require(isinstance(voice, str) and voice in runtime.allowed_tts_voices)
    require(isinstance(reason, str) and reason in REPLY_REASONS)
    require(
        reply_id is None
        or (isinstance(reply_id, str) and runtime.reply_id_pattern.fullmatch(reply_id) is not None)
    )
    with runtime.lock:
        require(call_id in runtime.calls, 404)
    require(enqueue_audio(call_id, text, reason, voice, reply_id), 429)
    return "", 202
```

и в конец файла добавить:

```python
@api.post("/announcements")
def announcement():
    """WAV уведомления для RTPengine play media: звонок без MRF слышит его от RTPengine."""
    data = json_object()
    text = spoken_text(data)
    voice = data.get("voice", runtime.tts_voice)
    require(isinstance(voice, str) and voice in runtime.allowed_tts_voices)
    payload = synthesize(text, voice)
    require(len(payload) <= runtime.announcement_max_bytes, 413)
    return jsonify(wav_base64=base64.b64encode(ulaw_wav(payload)).decode("ascii"))
```

- [ ] **Step 4: Media Adapter — `play media` и `/announce`**

В конец `app/services/media-adapter/ims_media/rtpengine.py` добавить:

```python
def _encode(value):
    """bencode для NG: int, str/bytes, list, dict (ключи по возрастанию)."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(_encode(k) + _encode(v) for k, v in items) + b"e"
    raise TypeError(f"bencode: unsupported {type(value).__name__}")


def _command(payload):
    """Одна команда NG со своим cookie; ответ без result=ok — ошибка."""
    cookie = ("media-adapter-" + secrets.token_hex(8)).encode("ascii")
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.settimeout(runtime.rtpengine_query_timeout)
    try:
        address = (runtime.rtpengine_ip, runtime.rtpengine_ng_port)
        control.sendto(cookie + b" " + _encode(payload), address)
        response = control.recv(65535)
    finally:
        control.close()
    prefix = cookie + b" "
    if not response.startswith(prefix):
        raise ValueError("RTPengine returned a mismatched control cookie")
    decoded, end = _decode(response, len(prefix))
    if end != len(response) or decoded.get(b"result") != b"ok":
        raise ValueError(f"RTPengine {payload['command']} failed")
    return decoded


def play_media(call_id, from_tag, blob):
    """Сыграть WAV в звонок RTPengine стороне с этим SIP tag (уведомление о записи)."""
    response = _command(
        {"command": "play media", "call-id": call_id, "from-tag": from_tag, "blob": blob}
    )
    return response.get(b"duration")
```

В `app/services/media-adapter/ims_media/runtime.py` после строки
`worker_url = worker_base_url + "/observe"` добавить:

```python
voice_agent_url = os.environ["VOICE_AGENT_URL"].rstrip("/")
```

В `app/services/media-adapter/ims_media/api.py` заменить блок импортов на:

```python
import base64
import re
import threading
from urllib.parse import quote

from flask import abort, jsonify
from lab_common.http import create_api, json_object, request_json, require, valid_call_id

from . import runtime
from .rtpengine import play_media
```

и в конец файла добавить:

```python
TAG = re.compile(r"^[A-Za-z0-9_.+~-]{1,64}$")


def fetch_announcement(text, voice):
    """WAV уведомления синтезирует Voice Agent: голоса и TTS живут только там."""
    data = request_json(
        "POST",
        runtime.voice_agent_url + "/announcements",
        payload={"text": text, "voice": voice},
        token=runtime.control_token,
        timeout=30,
    )
    return base64.b64decode(data["wav_base64"])


@api.post("/sessions/<call_id>/announce")
def announce(call_id):
    """Уведомление о записи каждой стороне звонка без MRF: RTPengine play media по SIP tag."""
    require(valid_call_id(call_id))
    parties = json_object(8192).get("parties")
    require(isinstance(parties, list) and 1 <= len(parties) <= 2)
    require(
        all(
            isinstance(party, dict)
            and isinstance(party.get("tag"), str)
            and TAG.fullmatch(party["tag"]) is not None
            and isinstance(party.get("text"), str)
            and isinstance(party.get("voice"), str)
            for party in parties
        )
    )
    try:
        for party in parties:
            wav = fetch_announcement(party["text"], party["voice"])
            play_media(call_id, party["tag"], wav)
    except Exception as exc:
        print(f"MEDIA announce_failed call_id={call_id} type={type(exc).__name__}", flush=True)
        abort(502)
    print(f"MEDIA announced call_id={call_id} parties={len(parties)}", flush=True)
    return "", 204
```

В `app/infrastructure/compose/ai.yml` после строки 76
(`AI_WORKER_URL: http://${AI_WORKER_IP}:${AI_WORKER_PORT}` в сервисе `media-adapter`)
добавить:

```yaml
      VOICE_AGENT_URL: http://${VOICE_AGENT_IP}:${VOICE_AGENT_HTTP_PORT}
```

- [ ] **Step 5: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_announcements.py' -v`
Expected: `Ran 12 tests` … `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены` (в том числе
`test_service_api.py` и `test_media_routing.py`).

- [ ] **Step 6: Коммит**

```bash
git add app/services/voice-agent/ims_voice app/services/media-adapter/ims_media \
  app/infrastructure/compose/ai.yml app/tests/unit/test_announcements.py app/tests/unit/test_media_routing.py
git commit -m "feat: recording announcement via Voice Agent WAV and RTPengine play media"
```

---

### Task 12: record AS — пометка, уведомление, запись обеих сторон

**Files:**
- Create: `app/services/sip-as/ims_sip/services/record.py`
- Modify: `app/services/sip-as/ims_sip/core/sip.py` (конец файла)
- Modify: `app/services/sip-as/ims_sip/core/proxy.py` (весь файл)
- Modify: `app/services/sip-as/ims_sip/core/dispatch.py` (импорт услуг и `SERVICES`)
- Modify: `app/services/sip-as/ims_sip/services/numbers.py` (`handle`)
- Modify: `app/services/sip-as/ims_sip/services/translate.py` (импорты, `on_answer`, новая функция)
- Modify: `app/services/sip-as/ims_sip/runtime.py` (конец файла)
- Modify: `app/config/lab.env` (раздел «Услуги IMS по профилю абонента»)
- Modify: `app/services/media-adapter/ims_media/rtpengine.py` (`resolve_subscriber_port`), `app/services/media-adapter/ims_media/publish.py:12,15-75` (импорт, `match_session`, `refresh_subscriber_ports`)
- Modify: `app/tests/unit/test_media_routing.py` (новые тесты в конец класса)
- Test: `app/tests/unit/test_sip_as_record.py`

**Interfaces:**
- Consumes: `core.mrf.announce`, `stream_to_recognition`, `stop_recognition`, `play`, `record_pair`; `core.dialogs.mark_record`, `is_marked_record`, `is_own`, `forget`; AI `POST /recordings` (задача 10); Media Adapter `POST /sessions/<id>/announce` (задача 11).
- Produces:
  - `core.sip.cseq_method(message) -> str`
  - `core.proxy.build_forwarded_request(message, branch, record_route="") -> str`, `core.proxy.forward(message, peer, *, record_route="", on_answer=None) -> None` — `on_answer(response)` вызывается на финальный ответ на INVITE
  - `services.record.HOST = "record.as"`, `parties(invite, response) -> list[tuple[str, str, str]]`, `start_recording(invite, response) -> None`, `on_answer(response) -> None`, `on_invite(message, peer) -> None`, `on_bye(message, peer) -> None`, `handle(message, peer) -> None`
  - `services.translate.start_pair_recording(call) -> None`
  - `runtime.answer_hooks: dict`, `runtime.record_invites: dict[str, str]`, `runtime.announcements: dict[str, tuple[str, str]]`
  - `ims_media.rtpengine.resolve_subscriber_ports(call_id) -> list[int]`; сессия `record` хранит `subscriber_ports` всех сторон
  - Журнал: `AS record marked call_id=<id>`, `AS record marked call_id=<B> via=translate`, `AS record started call_id=<id>`, `AS record started call_id=<A> legs=2`, `AS record skipped call_id=<id> reason=announcement`, `AS record ended call_id=<id>`, `MEDIA mapped call_id=<id> subscriber_port=<p> sides=<n>`

- [ ] **Step 1: Написать падающие тесты**

`app/tests/unit/test_sip_as_record.py`:

```python
"""record AS: пометка звонка, Record-Route, уведомление, поток в AI, запись пары перевода."""

import re
import unittest

from sip_fakes import (
    CALLEE,
    CALLER,
    DOMAIN,
    ENV,
    RTP_B,
    RTP_IP,
    SCSCF,
    SipCase,
    invite,
    load_sip_as,
    request,
    response,
    sdp,
)

load_sip_as()
from ims_sip.core import dialogs

AS_PORT = ENV["SIP_AS_PORT"]
OTHER_PEER = ("198.51.100.1", 6060)
RECORD_RR = f"Record-Route: <sip:record.as.{DOMAIN}:{AS_PORT};transport=udp;lr>"
RU = (ENV["RECORDING_ANNOUNCEMENT_RU"], ENV["TTS_VOICE"])
EN = (ENV["RECORDING_ANNOUNCEMENT_EN"], ENV["TTS_TRANSLATION_VOICE"])


def call_id_of(message):
    return re.search(r"(?m)^Call-ID: (.+)$", message).group(1).strip()


class RecordProxy(SipCase):
    def forward_call(self, call_id, target=CALLEE):
        self.route_request(invite(target, call_id, route_host="record.as"), OTHER_PEER)
        return self.requests("INVITE")[-1]

    def answer(self, forwarded, status=200, reason="OK"):
        body = sdp(RTP_IP, RTP_B) if status == 200 else ""
        self.route_response(response(forwarded, status, reason, to_tag="tb1", body=body))

    def sessions(self):
        return [p for p in self.http.posted("media.test/sessions") if "service_mode" in p]

    def test_marks_call_and_adds_record_route(self):
        forwarded = self.forward_call("rec-1")
        self.assertIn(RECORD_RR, forwarded)
        self.assertLess(forwarded.index(RECORD_RR), forwarded.index("Record-Route: <sip:mo@"))
        self.assertRegex(forwarded, r"(?m)^Route: <sip:iscmark@")
        self.assertTrue(dialogs.is_marked_record("rec-1"))
        self.assertEqual(self.sessions(), [])
        self.assertIn("AS record marked call_id=rec-1", self.log())

    def test_answer_announces_then_streams(self):
        self.answer(self.forward_call("rec-2"))
        self.assertEqual(self.sent()[-1][1], OTHER_PEER)
        parties = [
            {"tag": "fa1", "text": RU[0], "voice": RU[1]},
            {"tag": "tb1", "text": EN[0], "voice": EN[1]},
        ]
        self.assertEqual(self.http.posted("/announce"), [{"parties": parties}])
        [session] = self.sessions()
        self.assertEqual((session["call_id"], session["service_mode"]), ("rec-2", "record"))
        urls = [url for _, url, _ in self.http.calls]
        announce = next(i for i, url in enumerate(urls) if url.endswith("/announce"))
        self.assertLess(announce, urls.index("http://media.test/sessions"))
        self.assertIn("AS record started call_id=rec-2", self.log())

    def test_failed_announcement_skips_recording(self):
        self.http.fail.add("/announce")
        self.answer(self.forward_call("rec-3"))
        self.assertEqual(self.sessions(), [])
        self.assertIn("AS record skipped call_id=rec-3 reason=announcement", self.log())

    def test_rejected_call_is_not_recorded(self):
        self.answer(self.forward_call("rec-r"), 486, "Busy Here")
        self.assertEqual(self.http.posted("/announce"), [])
        self.assertEqual(self.runtime.record_invites, {})

    def test_bye_stops_recording(self):
        self.answer(self.forward_call("rec-4"))
        bye = request(
            "BYE",
            "rec-4",
            uri=f"sip:{CALLEE}@192.0.2.20:5060",
            from_user=CALLER,
            from_tag="fa1",
            to_user=CALLEE,
            to_tag="tb1",
            route_host="record.as",
        )
        self.route_request(bye, SCSCF)
        [forwarded_bye] = self.requests("BYE")
        self.assertNotIn(f"record.as.{DOMAIN}", forwarded_bye)
        self.assertEqual(len(self.http.deleted("media.test/sessions/rec-4")), 1)
        self.assertFalse(dialogs.is_marked_record("rec-4"))
        self.assertIn("AS record ended call_id=rec-4", self.log())

    def test_service_number_passes_unchanged(self):
        forwarded = self.forward_call("rec-5", target=ENV["VOICE_TRANSCRIBER_MSISDN"])
        self.assertNotIn(RECORD_RR, forwarded)
        self.assertFalse(dialogs.is_marked_record("rec-5"))
        self.assertNotIn("AS record marked", self.log())

    def test_translate_leg_is_marked_without_own_recording(self):
        call_id = dialogs.new_call_id()
        forwarded = self.forward_call(call_id)
        self.assertNotIn(RECORD_RR, forwarded)
        self.assertTrue(dialogs.is_marked_record(call_id))
        self.assertEqual(self.runtime.record_invites, {})
        self.assertIn(f"AS record marked call_id={call_id} via=translate", self.log())

    def test_numbers_skips_marked_call(self):
        dialogs.mark_record("rec-n")
        self.route_request(invite(CALLEE, "rec-n"), SCSCF)
        self.assertNotIn("AS observed INVITE", self.log())


class TranslatedRecording(SipCase):
    def translated_call(self):
        self.route_request(invite(CALLEE, "tr-r", route_host="translate.as"), SCSCF)
        leg_b = self.requests("INVITE")[-1]
        via_record = f"Route: <sip:record.as.{DOMAIN}:{AS_PORT};transport=udp;lr>, <sip:iscmark@"
        self.route_request(leg_b.replace("Route: <sip:iscmark@", via_record), SCSCF)
        answer = response(
            leg_b,
            200,
            "OK",
            to_tag="tb1",
            body=sdp(RTP_IP, RTP_B),
            contact=f"<sip:{CALLEE}@192.0.2.20:5060>",
        )
        return call_id_of(leg_b), answer

    def test_translated_call_records_both_legs_after_announcement(self):
        b, answer = self.translated_call()
        self.route_response(answer)
        self.assertEqual(
            self.http.posted("/reply"),
            [
                {"text": RU[0], "voice": RU[1], "reason": "announcement"},
                {"text": EN[0], "voice": EN[1], "reason": "announcement"},
            ],
        )
        legs = [{"call_id": "tr-r", "speaker": "caller"}, {"call_id": b, "speaker": "callee"}]
        expected = [{"session_call_id": "tr-r", "legs": legs}]
        self.assertEqual(self.http.posted("ai.test/recordings"), expected)
        self.assertIn("AS record started call_id=tr-r legs=2", self.log())

    def test_play_failure_skips_pair_recording(self):
        _, answer = self.translated_call()
        self.http.fail.add("/reply")
        self.route_response(answer)
        self.assertEqual(self.http.posted("ai.test/recordings"), [])
        self.assertIn("AS record skipped call_id=tr-r reason=announcement", self.log())


if __name__ == "__main__":
    unittest.main()
```

В конец класса `MediaRouting` в `app/tests/unit/test_media_routing.py` добавить:

```python
    def test_record_session_matches_both_subscriber_sides(self):
        active = {
            "rec": {
                "rtpengine_port": 30010,
                "subscriber_port": 30020,
                "subscriber_ports": [30020, 30022],
                "service_mode": "record",
            },
            "other": {"rtpengine_port": 30030, "subscriber_port": 30040},
        }
        self.assertEqual(self.match_session(4000, 30022, "caller_to_core", active)[0], "rec")
        self.assertEqual(self.match_session(4002, 30020, "caller_to_core", active)[0], "rec")

    def test_query_returns_every_subscriber_side(self):
        hosts = self.rtpengine.runtime.ims_ue_network.hosts()
        tags = {}
        for name, port in ((b"caller", 30020), (b"callee", 30022)):
            stream = {
                b"local port": port,
                b"flags": [b"RTP"],
                b"endpoint": {b"address": str(next(hosts)).encode("ascii")},
            }
            tags[name] = {b"medias": [{b"type": b"audio", b"streams": [stream]}]}
        reply = {b"result": b"ok", b"tags": tags}
        with patch.object(self.rtpengine, "_query", return_value=reply):
            self.assertEqual(self.rtpengine.resolve_subscriber_ports("call"), [30020, 30022])
            self.assertEqual(self.rtpengine.resolve_subscriber_port("call"), 30020)

    def test_observe_keeps_single_subscriber_side(self):
        from ims_media import publish

        active = {
            "obs": {"rtpengine_port": 30010, "service_mode": "observe"},
            "rec": {"rtpengine_port": 30012, "service_mode": "record"},
        }
        with (
            patch.object(publish, "resolve_subscriber_ports", return_value=[30020, 30022]),
            patch.dict(publish.runtime.sessions, {}, clear=True),
        ):
            publish.refresh_subscriber_ports(active)
        self.assertEqual(active["obs"]["subscriber_ports"], [30020])
        self.assertEqual(active["rec"]["subscriber_ports"], [30020, 30022])
```

- [ ] **Step 2: Запустить тесты — падают**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_record.py' -v`
Expected: ERROR — `KeyError: 'RECORDING_ANNOUNCEMENT_RU'` (ключа ещё нет в `lab.env`).

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_media_routing.py' -v`
Expected: ERROR — `AttributeError: ... has no attribute 'resolve_subscriber_ports'`.

- [ ] **Step 3: Тексты уведомления в `lab.env`**

В `app/config/lab.env` после строки `SIPUE2_LANGUAGE=en` добавить:

```text
# Уведомление перед записью (record): каждая сторона слышит его на своём языке;
# звук не длиннее 6 с (предел одной команды play media к RTPengine).
RECORDING_ANNOUNCEMENT_RU="Внимание. Разговор записывается для локальной расшифровки."
RECORDING_ANNOUNCEMENT_EN="Attention. This call is recorded for a local transcript."
```

- [ ] **Step 4: Прокси с Record-Route и хуком ответа**

В конец `app/services/sip-as/ims_sip/core/sip.py` добавить:

```python
def cseq_method(message: str) -> str:
    value = header(message.split("\r\n\r\n", 1)[0], "CSeq")
    return value.split()[-1].upper() if value else ""
```

`app/services/sip-as/ims_sip/core/proxy.py` заменить целиком:

```python
"""Прокси-путь логического AS: свой Via, снятие своего Route, Record-Route, хук ответа."""

import re

from .. import runtime
from .sip import cseq_method, status_code, transaction_branch
from .transport import send

# Свой Route — первый, хост <метка>.as.<домен> или as.<домен>: в одной строке со
# следующим ISC Route через запятую либо отдельной строкой.
OWN_ROUTE = re.compile(r"(?im)^(Route\s*:\s*)<sip:(?:[a-z0-9-]+\.)?as\.[^>]+>\s*,\s*")
OWN_ROUTE_LINE = re.compile(r"(?im)^Route\s*:\s*<sip:(?:[a-z0-9-]+\.)?as\.[^>]+>\s*\r\n")
OWN_VIA = re.compile(r"(?im)^(?:Via|v)\s*:\s*[^\r\n]*branch=z9hG4bK-as-([^;\s]+)\r\n")


def build_forwarded_request(message: str, branch: str, record_route: str = "") -> str:
    request_line, remaining_headers = message.split("\r\n", 1)
    own_via = (
        f"Via: SIP/2.0/UDP {runtime.bind_ip}:{runtime.bind_port};branch=z9hG4bK-as-{branch}\r\n"
    )
    if record_route:
        # Логический AS остаётся в пути диалога: BYE придёт к нему и закроет услугу.
        host = f"{record_route}.{runtime.ims_domain}:{runtime.bind_port}"
        own_via += f"Record-Route: <sip:{host};transport=udp;lr>\r\n"
    # Поглощается только Route текущего AS. Следующий ISC Route возвращает
    # запрос в S-CSCF, где продолжается цепочка iFC.
    stripped = OWN_ROUTE.sub(r"\1", remaining_headers, count=1)
    if stripped == remaining_headers:
        stripped = OWN_ROUTE_LINE.sub("", remaining_headers, count=1)
    return request_line + "\r\n" + own_via + stripped


def forward(message: str, peer: tuple[str, int], *, record_route: str = "", on_answer=None):
    """Вернуть запрос в S-CSCF; on_answer(response) — на финальный ответ на INVITE."""
    branch = transaction_branch(message)
    runtime.transactions[branch] = peer
    if on_answer is not None:
        runtime.answer_hooks[branch] = on_answer
    send(build_forwarded_request(message, branch, record_route), runtime.scscf)


def relay_response(message: str) -> None:
    """Удалить собственный Via и вернуть ответ исходному SIP peer."""
    via_match = OWN_VIA.search(message)
    if via_match is None:
        print(f"AS dropped response without own Via: {message.splitlines()[0]}", flush=True)
        return
    branch = via_match.group(1)
    destination_peer = runtime.transactions.get(branch)
    if destination_peer is None:
        print(f"AS dropped response for unknown transaction {branch}", flush=True)
        return
    print(
        f"AS relayed response {message.splitlines()[0]} "
        f"to {destination_peer[0]}:{destination_peer[1]}",
        flush=True,
    )
    response = OWN_VIA.sub("", message, count=1)
    send(response, destination_peer)
    if status_code(message) >= 200 and cseq_method(message) == "INVITE":
        hook = runtime.answer_hooks.pop(branch, None)
        if hook is not None:
            hook(response)
```

- [ ] **Step 5: Реализовать record AS**

`app/services/sip-as/ims_sip/services/record.py`:

```python
"""record AS: прокси с пометкой записи.

Без перевода звук звонка идёт из RTPengine в AI Worker (как observe) после
уведомления каждой стороне. Если звонок переводится, нога B проходит record AS
по цепочке iFC: он только помечает её, а translate пишет обе ноги MRF.
"""

import threading

from .. import runtime
from ..core import dialogs, mrf, proxy
from ..core.sip import message_call_id, request_method, status_code, tag_of, value_of
from ..core.subscribers import language_for, served_user, target_user

HOST = "record.as"


def parties(invite: str, response: str) -> list[tuple[str, str, str]]:
    """(SIP tag, текст, голос) уведомления для звонящего и вызываемого на их языках."""
    default = runtime.default_language
    caller = language_for(served_user(invite), runtime.languages, default)
    callee = language_for(target_user(invite), runtime.languages, default)
    return [
        (tag_of(value_of(invite, "From")), *runtime.announcements[caller]),
        (tag_of(value_of(response, "To")), *runtime.announcements[callee]),
    ]


def start_recording(invite: str, response: str) -> None:
    call_id = message_call_id(invite)
    # Без уведомления не записываем: сторона должна знать о записи.
    if not mrf.announce(call_id, parties(invite, response)):
        print(f"AS record skipped call_id={call_id} reason=announcement", flush=True)
        return
    mrf.stream_to_recognition(invite, "record")
    print(f"AS record started call_id={call_id}", flush=True)


def on_answer(response: str) -> None:
    invite = runtime.record_invites.pop(message_call_id(response), None)
    if invite is not None and 200 <= status_code(response) < 300:
        # Уведомление играет до нескольких секунд: SIP-цикл его не ждёт.
        threading.Thread(target=start_recording, args=(invite, response), daemon=True).start()


def on_invite(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    if target_user(message) in runtime.service_targets:
        proxy.forward(message, peer)  # 1003–1006 работают как раньше
        return
    dialogs.mark_record(call_id)
    if dialogs.is_own(call_id):
        proxy.forward(message, peer)
        print(f"AS record marked call_id={call_id} via=translate", flush=True)
        return
    runtime.record_invites[call_id] = message
    proxy.forward(message, peer, record_route=HOST, on_answer=on_answer)
    print(f"AS record marked call_id={call_id}", flush=True)


def on_bye(message: str, peer: tuple[str, int]) -> None:
    call_id = message_call_id(message)
    proxy.forward(message, peer)
    if dialogs.is_own(call_id):
        return  # ногу B освобождает B2BUA
    runtime.record_invites.pop(call_id, None)
    dialogs.forget(call_id)
    mrf.stop_recognition(call_id)
    print(f"AS record ended call_id={call_id}", flush=True)


def handle(message: str, peer: tuple[str, int]) -> None:
    method = request_method(message)
    if method == "INVITE" and not tag_of(value_of(message, "To")):
        on_invite(message, peer)
    elif method in {"BYE", "CANCEL"}:
        on_bye(message, peer)
    else:
        proxy.forward(message, peer)
```

В конец `app/services/sip-as/ims_sip/runtime.py` добавить:

```python
answer_hooks = {}
record_invites = {}
announcements = {
    "ru": (os.environ["RECORDING_ANNOUNCEMENT_RU"], os.environ["TTS_VOICE"]),
    "en": (os.environ["RECORDING_ANNOUNCEMENT_EN"], os.environ["TTS_TRANSLATION_VOICE"]),
}
```

В `app/services/sip-as/ims_sip/core/dispatch.py` заменить строки
`from ..services import numbers, translate` и `SERVICES = (translate, numbers)` на:

```python
from ..services import numbers, record, translate
```

```python
SERVICES = (translate, record, numbers)
```

В `app/services/sip-as/ims_sip/services/numbers.py` в функции `handle` заменить строки
комментария и условия перед `observe_proxied_dialog` на:

```python
    # Ногу B (B2BUA) и звонок под записью уже распознаёт услуга: не наблюдать дважды.
    if not (dialogs.is_own(call_id) or dialogs.is_marked_record(call_id)):
```

- [ ] **Step 6: translate пишет обе ноги, если звонок помечен record**

В `app/services/sip-as/ims_sip/services/translate.py` заменить строку `import re` на

```python
import re
import threading
```

функцию `on_answer` на:

```python
def on_answer(call: b2bua.Call, response: str) -> bool:
    """Обе ноги к Voice Agent в режимах своих языков, затем пара в AI Worker."""
    (lang_a, lang_b), a, b = call.languages, call.a, call.b
    if a.media is None:
        return False
    if not mrf.bind_leg(call.a_invite, a.call_id, *a.media, mrf.INTERPRETER_MODES[lang_a]):
        return False
    if not mrf.bind_leg(response, b.call_id, *b.media, mrf.INTERPRETER_MODES[lang_b]):
        mrf.release(a.call_id)
        return False
    mrf.pair((a.call_id, lang_a), (b.call_id, lang_b))
    print(
        f"AS translate answered call_id={a.call_id} leg_b={b.call_id} "
        f"languages={lang_a}-{lang_b}",
        flush=True,
    )
    # record AS (приоритет 20) пометил ногу B, когда она шла по цепочке iFC.
    if dialogs.is_marked_record(b.call_id):
        threading.Thread(target=start_pair_recording, args=(call,), daemon=True).start()
    return True


def start_pair_recording(call: b2bua.Call) -> None:
    """Уведомление каждой стороне голосом MRF, затем запись обеих ног в одну сессию AI."""
    legs = ((call.a.call_id, call.languages[0]), (call.b.call_id, call.languages[1]))
    for call_id, language in legs:
        text, voice = runtime.announcements[language]
        if not mrf.play(call_id, text, voice):
            print(f"AS record skipped call_id={call.a.call_id} reason=announcement", flush=True)
            return
    mrf.record_pair(call.a.call_id, [(call.a.call_id, "caller"), (call.b.call_id, "callee")])
    print(f"AS record started call_id={call.a.call_id} legs=2", flush=True)
```

- [ ] **Step 7: Media Adapter — обе стороны звонка для `record`**

В `app/services/media-adapter/ims_media/rtpengine.py` функцию `resolve_subscriber_port`
заменить на:

```python
def resolve_subscriber_ports(call_id):
    """Even relay ports of every call side whose remote endpoint is an IMS subscriber."""
    ports = []
    try:
        response = _query(call_id)
        for tag in response.get(b"tags", {}).values():
            for media in tag.get(b"medias", []):
                if media.get(b"type") != b"audio":
                    continue
                for stream in media.get(b"streams", []):
                    endpoint = stream.get(b"endpoint", {})
                    address = endpoint.get(b"address", b"").decode("ascii")
                    port = stream.get(b"local port")
                    if (
                        b"RTP" in stream.get(b"flags", [])
                        and runtime.is_subscriber(address)
                        and runtime.port_min <= port <= runtime.port_max
                        and port % 2 == 0
                    ):
                        ports.append(port)
    except (OSError, ValueError, IndexError, KeyError, UnicodeError, TypeError) as exc:
        print(f"MEDIA RTPengine query failed type={type(exc).__name__}", flush=True)
    return ports


def resolve_subscriber_port(call_id):
    """Return the first even relay port whose remote endpoint is in the IMS UE pool."""
    ports = resolve_subscriber_ports(call_id)
    return ports[0] if ports else None
```

В `app/services/media-adapter/ims_media/publish.py` строку 12 заменить на
`from .rtpengine import resolve_subscriber_ports`, в `match_session` заменить блок
`matching_sessions = [...]` после `if direction != "caller_to_core": return None` на:

```python
    # Запись (record) слушает все стороны звонка, остальные режимы — одну.
    matching_sessions = [
        (call_id, session)
        for call_id, session in active_sessions.items()
        if destination_port in session.get("subscriber_ports", (session.get("subscriber_port"),))
    ]
```

и функцию `refresh_subscriber_ports` на:

```python
def refresh_subscriber_ports(active_sessions: dict) -> None:
    """Один раз получить у RTPengine порты абонентских сторон каждого звонка."""
    for call_id, current_session in list(active_sessions.items()):
        is_terminated_call = current_session.get("rtpengine_port") is not None
        already_resolved = current_session.get("subscriber_port") is not None
        if not is_terminated_call or already_resolved:
            continue

        ports = resolve_subscriber_ports(call_id)
        if not ports:
            continue
        if current_session.get("service_mode") != "record":
            ports = ports[:1]

        resolved_session = dict(current_session)
        resolved_session.update(subscriber_port=ports[0], subscriber_ports=ports)
        active_sessions[call_id] = resolved_session

        with runtime.lock:
            if call_id in runtime.sessions:
                runtime.sessions[call_id].update(subscriber_port=ports[0], subscriber_ports=ports)

        print(
            f"MEDIA mapped call_id={call_id} subscriber_port={ports[0]} sides={len(ports)}",
            flush=True,
        )
```

- [ ] **Step 8: Запустить тесты — проходят**

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_sip_as_*.py' -v`
Expected: `Ran 76 tests` … `OK`.

Run: `PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit -p 'test_media_routing.py' -v`
Expected: `OK`.

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 9: Коммит**

```bash
git add app/services/sip-as/ims_sip app/config/lab.env app/services/media-adapter/ims_media \
  app/tests/unit/test_sip_as_record.py app/tests/unit/test_media_routing.py
git commit -m "feat: record AS with announcement and two-sided transcript"
```

---

### Task 13: Интеграция — сценарии 1–4 на SIPUE и через 5G

**Files:**
- Create: `app/tests/integration/verify-services.sh`
- Modify: `app/tests/integration/verify-5g-ue.sh:1-7` (шапка), `:50-54` (`stop_clients`), `:185-200` (тест B), перед `finish` (строка 212) — тесты D, E, F

**Interfaces:**
- Consumes: журналы задач 7–12: `AS b2bua leg_b call_id=<B> for call_id=<A>`, `AS translate answered call_id=<A> leg_b=<B> languages=<a>-<b>`, `AS record marked call_id=<B> via=translate`, `AS record started call_id=<A> legs=2`, `AS b2bua ended call_id=<A> by=a`, `AS observed INVITE call_id=<id>`; Voice Agent `VOICE tts call_id=<id> reason=announcement|llm_reply state=sent ... voice=<voice>`; AI Worker `AI pair_registered calls=[...]`, `AI recording_finalized session=<sha256(A)[:20]>`, `GET /events`; `common.sh` (`check`, `finish`, `pjsua`, `fresh_clients`, `service_get`, `wait_call_id`, `hangup_clients`).
- Produces: `verify-services.sh` с финальной строкой `IMS SERVICES: TRANSLATE + RECORD + STAR + PLAIN + AS DOWN: PASS`; тесты D, E, F в `verify-5g-ue.sh` (финальная строка не меняется: `5G UE -> IMS -> AI: PASS`).

Предусловие для всех шагов на стенде (Linux, стенд запущен `python3 scripts/start.py`, задачи 1–12 влиты):
iFC читается S-CSCF при регистрации и кэшируется, поэтому после изменения услуг в `lab.env`:

```bash
python3 scripts/provision.py --apply && docker restart lab-scscf
```

- [ ] **Step 1: Написать сценарии на SIPUE**

`app/tests/integration/verify-services.sh`:

```bash
#!/usr/bin/env bash
# Услуги IMS по профилю абонента (iFC из lab.env, scripts/provision.py):
# 1) SIPUE1 (ru, translate+record) -> SIPUE2 (en): B2BUA translate AS, перевод в обе
#    стороны через MRF, уведомление и запись обеих сторон в один transcript.txt;
# 2) SIPUE2 -> *SIPUE1: разовый перевод en-ru без записи;
# 3) SIPUE2 -> SIPUE1: обычный звонок без MRF, только наблюдение;
# 4) SIP AS остановлен: звонок проходит (DefaultHandling SESSION_CONTINUED).
# После изменения услуг: python3 scripts/provision.py --apply && docker restart lab-scscf.
# Печатаются только Call-ID и метаданные, не текст. Без -e: сбой — строка FAIL.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

as_stopped=0
cleanup() {
    hangup_clients
    if ((as_stopped)); then docker start lab-sip-as >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
as_log() { docker logs lab-sip-as --since "$1" 2>&1; }
rtp_info() {
    docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" \
        call "$1" info 2>&1 || true
}
# Ждать строку (grep -E) в журнале контейнера начиная с момента since.
wait_for() {
    local container=$1 pattern=$2 seconds=$3 since=$4 deadline=$((SECONDS + $3))
    while ((SECONDS < deadline)); do
        docker logs "$container" --since "$since" 2>&1 | grep -Eq -- "$pattern" && return 0
        sleep 1
    done
    return 1
}
absent() { ! grep -Eq -- "$1" <<<"$2"; }
# Распознанные реплики ноги в AI Worker: "<всего> <с кириллицей>".
leg_languages() {
    service_get lab-ai-worker AI_WORKER_PORT /events | python3 -c '
import json, sys
events = [e for e in json.load(sys.stdin).get("events", [])
          if sys.argv[1] in e.get("call_ids", []) and e.get("processed_at", 0) >= float(sys.argv[2])
          and e.get("transcript_chars", 0) > 0]
print(len(events), sum(1 for e in events if e.get("transcript_cyrillic_chars", 0) > 0))' "$1" "$2"
}
# Проигрыватель WAV диалога -> последний вызов в конференц-мосту PJSUA.
connect_playback() {
    local client=$1 rows player call
    pjsua "$client" 'cl\n'
    sleep 1
    rows=$(docker logs "$client" 2>&1 | grep -E '^ *Port #')
    player=$(grep '\.wav' <<<"$rows" | sed -E 's/^ *Port #0*([0-9]+).*/\1/' | tail -1)
    call=$(grep -E '\] +sip:' <<<"$rows" | sed -E 's/^ *Port #0*([0-9]+).*/\1/' | tail -1)
    [[ -n $player && -n $call ]] && pjsua "$client" "cc\n$player\n$call\n"
}
in_worker() { docker exec lab-ai-worker sh -c "$1"; }

echo "===== 1: SIPUE1 ($SIPUE1_LANGUAGE) -> SIPUE2 ($SIPUE2_LANGUAGE): translate + record ====="
export SIPUE1_PLAYBACK_FILE=$INTERPRETER_DIALOGUE_UE1_FILE
export SIPUE2_PLAYBACK_FILE=$INTERPRETER_DIALOGUE_UE2_FILE SIPUE_AUTO_CONFERENCE=0
check 'тестовые клиенты зарегистрированы (WAV диалога)' fresh_clients
since=$(now)
since_epoch=$(date +%s)
pjsua lab-sipue1 "m\nsip:${SIPUE2_IMSI}@${IMS_DOMAIN}\n"
a=$(wait_call_id '.*AS b2bua leg_b call_id=[^ ]* for call_id=\([^ ]*\).*' "$since")
b=$(wait_call_id '.*AS b2bua leg_b call_id=\([^ ]*\) for call_id=.*' "$since")
printf 'INFO: leg_a=%s leg_b=%s\n' "$a" "$b"
check 'translate AS принял ногу A и создал ногу B' test -n "$a" -a -n "$b"
check 'record AS пометил ногу B (via=translate)' \
    wait_for lab-sip-as "AS record marked call_id=$b via=translate" 15 "$since"
check 'SIPUE2 получил INVITE ноги B' wait_for lab-sipue2 "^(Call-ID|i): $b" 15 "$since"
check 'SIPUE1 получил 200/INVITE' wait_for lab-sipue1 'Response msg 200/INVITE' 30 "$since"
check 'перевод ru-en' wait_for lab-sip-as "AS translate answered call_id=$a leg_b=$b languages=ru-en" \
    10 "$since"
check 'AI Worker: пара ног зарегистрирована' wait_for lab-ai-worker 'AI pair_registered' 10 "$since"
check 'уведомление в ноге A (ru)' \
    wait_for lab-voice-agent "VOICE tts call_id=$a reason=announcement state=sent.*voice=$TTS_VOICE" \
    30 "$since"
check 'уведомление в ноге B (en)' wait_for lab-voice-agent \
    "VOICE tts call_id=$b reason=announcement state=sent.*voice=$TTS_TRANSLATION_VOICE" 30 "$since"
check 'запись обеих ног начата' wait_for lab-sip-as "AS record started call_id=$a legs=2" 30 "$since"

# Диалог: каждая сторона говорит на своём языке; уведомление уже прозвучало.
connect_playback lab-sipue1
connect_playback lab-sipue2
check 'перевод SIPUE1 доставлен в ногу B английским голосом' wait_for lab-voice-agent \
    "VOICE tts call_id=$b reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" 180 "$since"
check 'перевод SIPUE2 доставлен в ногу A русским голосом' wait_for lab-voice-agent \
    "VOICE tts call_id=$a reason=llm_reply state=sent.*voice=$TTS_VOICE" 180 "$since"

leg_a_rtp=$(rtp_info "$a")
leg_b_rtp=$(rtp_info "$b")
check 'RTPengine: нога A — SIPUE1 без SIPUE2' eval \
    'grep -q "$SIPUE1_IP" <<<"$leg_a_rtp" && absent "$SIPUE2_IP" "$leg_a_rtp"'
check 'RTPengine: нога B — SIPUE2 без SIPUE1' eval \
    'grep -q "$SIPUE2_IP" <<<"$leg_b_rtp" && absent "$SIPUE1_IP" "$leg_b_rtp"'
read -r b_total b_cyrillic <<<"$(leg_languages "$b" "$since_epoch")"
printf 'INFO: leg_b utterances=%s cyrillic=%s\n' "${b_total:-0}" "${b_cyrillic:-0}"
check 'нога B: речь SIPUE2 распознана' test "${b_total:-0}" -gt 0
check 'нога B: русская речь SIPUE1 в неё не попала' test "${b_cyrillic:-1}" = 0

pjsua lab-sipue1 'ha\n'
check 'B2BUA закрыл обе ноги по BYE со стороны A' \
    wait_for lab-sip-as "AS b2bua ended call_id=$a by=a" 15 "$since"
check 'SIPUE2: BYE ноги B дошёл' wait_for lab-sipue2 'DISCONNECTED' 15 "$since"
session=$(printf '%s' "$a" | sha256sum | cut -c1-20)
check 'AI Worker: запись закрыта после обеих ног' \
    wait_for lab-ai-worker "AI recording_finalized session=$session" 30 "$since"
check 'transcript.txt: реплики звонящего' \
    in_worker "grep -q '^\[caller/' $RECORDING_ROOT/$session/transcript.txt"
check 'transcript.txt: реплики вызываемого' \
    in_worker "grep -q '^\[callee/' $RECORDING_ROOT/$session/transcript.txt"
printf 'INFO: session=%s\n' "$session"
sleep 2

echo "===== 2: SIPUE2 -> *SIPUE1: разовый перевод en-ru без записи ====="
since=$(now)
pjsua lab-sipue2 "m\nsip:*${SIPUE1_IMSI}@${IMS_DOMAIN}\n"
check 'SIPUE2 получил 200/INVITE' wait_for lab-sipue2 'Response msg 200/INVITE' 30 "$since"
check 'перевод en-ru' wait_for lab-sip-as 'AS translate answered call_id=[^ ]+ leg_b=[^ ]+ languages=en-ru' \
    10 "$since"
check 'без записи: record AS не участвует' absent 'AS record (marked|started)' "$(as_log "$since")"
pjsua lab-sipue2 'ha\n'
check 'SIPUE1: BYE дошёл' wait_for lab-sipue1 'DISCONNECTED' 15 "$since"
sleep 2

echo "===== 3: SIPUE2 -> SIPUE1: обычный звонок без MRF ====="
since=$(now)
pjsua lab-sipue2 "m\nsip:${SIPUE1_IMSI}@${IMS_DOMAIN}\n"
plain=$(wait_call_id '.*AS observed INVITE call_id=\([^ ]*\).*' "$since")
check 'SIPUE2 получил 200/INVITE' wait_for lab-sipue2 'Response msg 200/INVITE' 30 "$since"
check 'numbers AS наблюдает звонок' test -n "$plain"
check 'B2BUA не создавал ногу B' absent 'AS b2bua leg_b' "$(as_log "$since")"
plain_rtp=$(rtp_info "$plain")
check 'RTPengine: медиа обеих сторон в одном звонке' eval \
    'grep -q "$SIPUE1_IP" <<<"$plain_rtp" && grep -q "$SIPUE2_IP" <<<"$plain_rtp"'
pjsua lab-sipue2 'ha\n'
sleep 2

echo "===== 4: SIP AS остановлен: SIPUE1 -> SIPUE2 без услуг ====="
docker stop -t 1 lab-sip-as >/dev/null
as_stopped=1
since=$(now)
pjsua lab-sipue1 "m\nsip:${SIPUE2_IMSI}@${IMS_DOMAIN}\n"
# S-CSCF ждёт каждый AS цепочки до fr_timer и продолжает (DefaultHandling 0).
check 'звонок соединился без SIP AS (SESSION_CONTINUED)' \
    wait_for lab-sipue1 'Response msg 200/INVITE' 60 "$since"
pjsua lab-sipue1 'ha\n'
docker start lab-sip-as >/dev/null
as_stopped=0

finish 'IMS SERVICES: TRANSLATE + RECORD + STAR + PLAIN + AS DOWN'
```

- [ ] **Step 2: Offline-проверки**

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены`.

- [ ] **Step 3: Запустить на стенде со старым iFC — падает**

На стенде, до `provision.py --apply` (у абонентов ещё iFC из `default_ifc.xml`):

Run: `bash app/tests/integration/verify-services.sh`
Expected: `FAIL: translate AS принял ногу A и создал ногу B` … `IMS SERVICES: TRANSLATE + RECORD + STAR + PLAIN + AS DOWN: FAIL`.

- [ ] **Step 4: Применить iFC и запустить — проходит**

Run: `python3 scripts/provision.py --apply && docker restart lab-scscf && bash app/tests/integration/verify-services.sh`
Expected: все строки `PASS:` и последняя `IMS SERVICES: TRANSLATE + RECORD + STAR + PLAIN + AS DOWN: PASS`.

Если не проходит сценарий 1 при `PASS` spike (задача 1): `docker logs lab-scscf | grep 'SCSCF ISC'` —
нога B должна прийти с `route_uri` ISC-метки, а не как новый исходящий звонок.

- [ ] **Step 5: Тесты D, E, F через 5G в `verify-5g-ue.sh`**

Строки 1–7 (шапку) заменить на:

```bash
#!/usr/bin/env bash
# Вызовы через 5G, а не из сети ядра: PJSUA запускается внутри namespace UE OAI
# (scripts/rfsim.sh up) и ходит в IMS через туннель oaitun, gNB и UPF. Проверяет
# PDU-сессию в пуле IMS, REGISTER абонентов UE1/UE2 с адресом туннеля, перевод
# 1003 для UE1, обычный вызов UE2 -> UE1 со звуком в обе стороны, расшифровку 1004
# для UE2, услуги профиля UE1 (перевод и запись UE1 -> UE2), «*номер» UE2 -> *UE1 и
# звонок при остановленном SIP AS. Аутентификация — SIP Digest, IMS AKA и IPsec
# здесь не проверяются. Нужны sudo (ip netns, chroot) и образ lab-pjsua.
```

функцию `stop_clients` (строки 50–54) заменить на:

```bash
stop_clients() {
    for n in 1 2; do ue_cmd "$n" 'ha\nq\n' 2>/dev/null || true; done
    sleep 1
    sudo pkill -f -- "[c]hroot $jail" 2>/dev/null || true
    docker start lab-sip-as >/dev/null 2>&1 || true  # тест F мог упасть с остановленным AS
}
```

тест B (строки 185–200) заменить на (у UE1 теперь translate и record, обычный вызов — от UE2):

```bash
echo "===== B: UE2 -> UE1 ($UE2_MSISDN -> $UE1_MSISDN) ====="
offset1=$(mark 1)
offset2=$(mark 2)
ue_cmd 2 "m\nsip:$UE1_MSISDN@$IMS_DOMAIN\n"
check 'UE2: 200/INVITE от UE1' wait_log 2 'Response msg 200/INVITE' 30 "$offset2"
check 'UE1: вызов принят' wait_log 1 'state changed to CONFIRMED' 10 "$offset1"
connect_player 1
connect_player 2
sleep 20
# 20 с при ptime 20 мс — около 1000 пакетов; порог оставляет запас на рывки rfsim.
for n in 1 2; do
    rx=$(rx_packets "$n")
    check "UE$n: звук от собеседника (RX ${rx:-0} > 500)" test "${rx:-0}" -gt 500
done
ue_cmd 2 'ha\n'
check 'UE1: BYE дошёл' wait_log 1 'DISCONNECTED' 15 "$offset1"
```

перед строкой `finish '5G UE -> IMS -> AI'` (после теста C) вставить:

```bash
sleep 2
echo "===== D: UE1 -> UE2: перевод $UE1_LANGUAGE-$UE2_LANGUAGE и запись ====="
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset1=$(mark 1)
offset2=$(mark 2)
ue_cmd 1 "m\nsip:$UE2_MSISDN@$IMS_DOMAIN\n"
check 'UE1: 200/INVITE (нога A translate AS)' wait_log 1 'Response msg 200/INVITE' 40 "$offset1"
check 'SIP AS: перевод ru-en' wait_docker lab-sip-as 'AS translate answered .* languages=ru-en' 10
check 'SIP AS: запись обеих ног после уведомления' \
    wait_docker lab-sip-as 'AS record started call_id=[^ ]+ legs=2' 40
say_once 1
check 'Voice Agent: перевод UE1 озвучен английским голосом' \
    wait_docker lab-voice-agent "reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" 120
ue_cmd 1 'ha\n'
check 'UE2: BYE ноги B дошёл' wait_log 2 'DISCONNECTED' 15 "$offset2"
check 'AI Worker: запись закрыта' wait_docker lab-ai-worker 'AI recording_finalized session=' 30
sleep 2

echo "===== E: UE2 -> *UE1: разовый перевод ====="
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset1=$(mark 1)
offset2=$(mark 2)
ue_cmd 2 "m\nsip:*$UE1_MSISDN@$IMS_DOMAIN\n"
check 'UE2: 200/INVITE' wait_log 2 'Response msg 200/INVITE' 40 "$offset2"
check 'SIP AS: перевод en-ru' wait_docker lab-sip-as 'AS translate answered .* languages=en-ru' 10
ue_cmd 2 'ha\n'
check 'UE1: BYE дошёл' wait_log 1 'DISCONNECTED' 15 "$offset1"
sleep 2

echo '===== F: SIP AS остановлен: UE1 -> UE2 ====='
docker stop -t 1 lab-sip-as >/dev/null
offset1=$(mark 1)
ue_cmd 1 "m\nsip:$UE2_MSISDN@$IMS_DOMAIN\n"
check 'UE1: 200/INVITE без SIP AS (DefaultHandling)' wait_log 1 'Response msg 200/INVITE' 60 "$offset1"
ue_cmd 1 'ha\n'
docker start lab-sip-as >/dev/null
```

- [ ] **Step 6: Запустить через 5G — проходит**

На стенде с ядром партнёра и rfsim (`docs/guide-5-5g-scripts.md`):

Run: `scripts/verify-5g.sh`
Expected: строки `PASS:` тестов A–F, в том числе `PASS: SIP AS: запись обеих ног после уведомления`,
`PASS: SIP AS: перевод en-ru`, `PASS: UE1: 200/INVITE без SIP AS (DefaultHandling)`; последняя —
`5G UE -> IMS -> AI: PASS`.

- [ ] **Step 7: Коммит**

```bash
git add --chmod=+x app/tests/integration/verify-services.sh
git add app/tests/integration/verify-5g-ue.sh
git commit -m "test: IMS services scenarios on SIPUE and over 5G"
```

---

### Task 14: Регрессия на стенде и документация

**Files:**
- Modify: `docs/guide-2-ims-ai.md` (раздел 3 строки 143–167, раздел 5 строки 30–37 и 198, раздел 6 строки 234–243 и 251)
- Modify: `docs/project-layout.md` (абзац «SIP AS — …», список тестов строки 67–90)
- Modify: `docs/guide-5-5g-scripts.md:20-37,107,117-118`
- Modify: `docs/guide-4-5g-manual.md:183-187`
- Modify: `docs/guide-1-ims-core.md:251`
- Modify: `CHANGELOG.md` (раздел `## [Unreleased]`)

**Interfaces:**
- Consumes: всё из задач 1–13; финальные строки проверок.
- Produces: документация, совпадающая с кодом; итог регрессии.

- [ ] **Step 1: Регрессия на стенде — по одной, в этом порядке**

На Linux-стенде после `python3 scripts/provision.py --apply && docker restart lab-scscf`:

| Run | Expected (последняя строка) |
|---|---|
| `python3 scripts/start.py` | `STARTED: IMS + AI (baseline) — сервисы готовы; вызовы проверяются тестами app/tests/integration` |
| `bash app/tests/integration/verify-ims.sh` | `IMS DNS + HSS + REGISTRATION: PASS` |
| `bash app/tests/integration/verify-ims-call.sh` | `IMS CALL + AS + RTPENGINE + AI FAIL-OPEN: PASS` |
| `bash app/tests/integration/verify-voice-agent.sh` | `VOICE AGENT SERVICE NUMBER: PASS` |
| `bash app/tests/integration/verify-translation.sh` | `RU SPEECH -> STT -> EN TRANSLATION -> TTS -> RTP: PASS` |
| `bash app/tests/integration/verify-transcription.sh` | `OPT-IN RECORDING -> STT -> LLM NORMALIZATION -> TRANSCRIPT: PASS` |
| `python3 app/tests/integration/verify_interpreter.py` | JSON с `"pass": true`, код выхода 0 |
| `bash app/tests/integration/verify-services.sh` | `IMS SERVICES: TRANSLATE + RECORD + STAR + PLAIN + AS DOWN: PASS` |
| `bash app/tests/integration/verify-security.sh` | `SECURITY/PRIVACY GATE: PASS` |
| `scripts/verify-5g.sh` (только со стендом 5G) | `5G UE -> IMS -> AI: PASS` |

Номера 1003–1006 (`verify-voice-agent.sh`, `verify-translation.sh`, `verify-transcription.sh`,
`verify_interpreter.py`) должны пройти без изменений их скриптов. Любой `FAIL` — остановиться и
чинить в задаче, к которой относится код, а не в документации.

- [ ] **Step 2: `docs/guide-2-ims-ai.md` — услуги**

В разделе 3 строки

```markdown
- **1001, 1002** — телефоны `UE1`, `UE2`; обычный вызов без AI. **1101, 1102** —
  тестовые клиенты.
```

заменить на:

```markdown
- **1001, 1002** — телефоны `UE1`, `UE2`; **1101, 1102** — тестовые клиенты `SIPUE1`,
  `SIPUE2`. Услуги абонента задаёт его профиль в `lab.env` (`*_SERVICES`, `*_LANGUAGE`):
  у `UE1` и `SIPUE1` — `translate,record` и `ru`, у `UE2` и `SIPUE2` — без услуг, `en`.
- **translate** — звонок абоненту с другим языком идёт через MRF (Voice Agent): каждый
  слышит перевод речи собеседника на своём языке, исходный звук между ними не
  передаётся. Тот же язык, номер услуги или занятый MRF — звонок идёт как обычный.
- **record** — после уведомления каждой стороне на её языке записываются обе стороны.
- **`*номер`** — разовый перевод с любого абонента, например `*1101`.
- **Обычный вызов** (1002 → 1001, 1102 → 1101) — без MRF; AI только наблюдает звук.
```

строку `Записывается только вызов на 1004 и только после уведомления:` заменить на:

```markdown
Записываются вызов на 1004 и звонки абонента с услугой `record` — только после
уведомления. Звонок с `record` пишет обе стороны в один каталог (имя — первые 20 hex
SHA-256 от Call-ID звонящего), строки `transcript.txt` начинаются с `[caller/<язык>]`
или `[callee/<язык>]`:
```

- [ ] **Step 3: `docs/guide-2-ims-ai.md` — проверки**

В блоке команд раздела «2. Проверки по шагам вызова» после строки
`python3 app/tests/integration/verify_interpreter.py` добавить строку:

```bash
bash app/tests/integration/verify-services.sh
```

В разделе 5 строку `1. **Шаги 7–8: \`verify-ims-call.sh\`** — вызов 1101 → 1102: INVITE через P/S-CSCF,`
заменить на:

```markdown
1. **Шаги 7–8: `verify-ims-call.sh`** — вызов 1102 → 1101: INVITE через P/S-CSCF,
```

и после пункта 5 (`verify_interpreter.py`, перед пунктом `6. **\`verify-security.sh\`**`) вставить,
а `6.` переименовать в `7.`:

```markdown
6. **`verify-services.sh`** — услуги профиля: 1101 → 1102 — перевод ru-en в обе стороны
   через MRF, уведомление и запись обеих сторон; 1102 → `*1101` — разовый перевод без
   записи; 1102 → 1101 — обычный звонок без MRF; при остановленном SIP AS звонок
   соединяется (`DefaultHandling 0`). После изменения услуг в `lab.env`:
   `python3 scripts/provision.py --apply && docker restart lab-scscf`.
```

- [ ] **Step 4: `docs/guide-2-ims-ai.md` — как вызов попадает в AI**

В разделе 6 два абзаца — от `PyHSS при provisioning записывает каждому абоненту iFC из`
до `Вызов на номер услуги он завершает сам и соединяет с Voice Agent.` — заменить на:

```markdown
`scripts/provision.py` собирает каждому абоненту iFC из его профиля в `lab.env` и
записывает в PyHSS: translate (приоритет 10) на `sip:translate.as.<IMS_DOMAIN>`,
`*номер` (15) — на translate всем, record (20) на `sip:record.as.<IMS_DOMAIN>`, numbers
(30) на `sip:as.<IMS_DOMAIN>`, SMS (40). У всех правил `DefaultHandling 0`: при
недоступном AS звонок продолжается без услуги. Все логические AS — один контейнер
`lab-sip-as` на одном порту; S-CSCF кэширует iFC, поэтому после изменения профиля
нужны `provision.py --apply` и `docker restart lab-scscf`.

SIP AS ([core/dispatch.py](../app/services/sip-as/ims_sip/core/dispatch.py)) выбирает
логический AS по хосту первого `Route` (`services/translate.py`, `services/record.py`,
`services/numbers.py`). translate — B2BUA: нога A заканчивается на Voice Agent, нога B
уходит в S-CSCF и идёт дальше по цепочке iFC. record — прокси с `Record-Route`, numbers
наблюдает обычный вызов или сам отвечает на номер услуги и соединяет с Voice Agent.
```

строку `6. \`ai-worker/ims_ai/transcription.py\` — нормализация и сохранение текста (1004).` заменить на:

```markdown
6. `ai-worker/ims_ai/transcription.py` — нормализация и сохранение текста (1004, record).
```

- [ ] **Step 5: `docs/project-layout.md`**

Абзац, начинающийся с `SIP AS — \`app/services/sip-as/ims_sip/\`` и заканчивающийся
`образа: после его изменения пересоберите их все.`, заменить на:

```markdown
SIP AS — `app/services/sip-as/ims_sip/`: `core/` — SIP без состояния (`sip.py`),
транспорт, SDP, прокси, B2BUA (`b2bua.py`), API MRF (`mrf.py`), языки абонентов и вход
(`dispatch.py`); `services/` — логические AS `translate.py`, `record.py`, `numbers.py`.
Voice Agent — `app/services/voice-agent/ims_voice/` (`calls.py` — жизнь вызова и
очередь озвучки, `media.py` — RTP, `api.py` — в том числе WAV уведомления). Media
Adapter — `app/services/media-adapter/ims_media/` (`rtpengine.py` — запросы и
`play media`). Файлы `worker.py`, `server.py`, `agent.py`, `adapter.py` — короткие
точки входа. Пакет `lab_common` копируется во все четыре образа: после его изменения
пересоберите их все.
```

строку ``- `verify_interpreter.py` — 1005/1006: перевод в обе стороны и задержка.`` дополнить
следующей строкой:

```markdown
- `verify-services.sh` — услуги профиля: translate + record, `*номер`, обычный звонок, AS остановлен.
```

строку про `verify-5g-ue.sh` заменить на:

```markdown
- `verify-5g-ue.sh` — абоненты UE через OAI rfsim (`scripts/rfsim.sh`): 1003, UE2↔UE1, 1004, перевод и запись UE1 → UE2, `*номер`, AS остановлен.
```

после строки ``- `test_cpu_ai_profiles.py` — направления OPUS-MT, без LLM в CPU-режимах.`` добавить:

```markdown
- `sip_fakes.py` — не тест: фейковые сокет, HTTP и потоки, построители SIP для тестов SIP AS.
- `test_ifc_generation.py` — iFC из профилей `lab.env`, приоритеты, DNS логических AS.
- `test_sip_as_numbers.py` — 1003–1006 и наблюдение обычного вызова.
- `test_sip_as_dispatch.py` — логический AS по `Route`, языки, свои диалоги.
- `test_sip_as_mrf.py` — API MRF: места, ноги, озвучка, пара, запись, уведомление.
- `test_sip_as_translate.py` — нога B через S-CSCF, 180, ответ и пара перевода.
- `test_sip_as_b2bua_teardown.py` — 486/480/408, BYE с каждой стороны, CANCEL, re-INVITE.
- `test_sip_as_translate_bypass.py` — `*номер` и звонок без перевода.
- `test_sip_as_record.py` — record AS: пометка, уведомление, запись пары перевода.
- `test_ai_pairs.py` — пары ног перевода в AI Worker.
- `test_ai_recording.py` — запись обеих сторон в один `transcript.txt`.
- `test_announcements.py` — WAV уведомления и `play media` RTPengine.
```

- [ ] **Step 6: `docs/guide-5-5g-scripts.md`, `docs/guide-4-5g-manual.md`, `docs/guide-1-ims-core.md`**

В `docs/guide-5-5g-scripts.md` строки

```text
===== B: UE1 -> UE2 (1001 -> 1002) =====
PASS: UE1: звук от собеседника (RX 1100 > 500)
PASS: UE2: звук от собеседника (RX 1100 > 500)
===== C: UE2 -> расшифровка 1004 =====
PASS: AI Worker: фраза UE2 распознана
```

заменить на:

```text
===== B: UE2 -> UE1 (1002 -> 1001) =====
PASS: UE1: звук от собеседника (RX 1100 > 500)
PASS: UE2: звук от собеседника (RX 1100 > 500)
===== C: UE2 -> расшифровка 1004 =====
PASS: AI Worker: фраза UE2 распознана
===== D: UE1 -> UE2: перевод ru-en и запись =====
PASS: SIP AS: запись обеих ног после уведомления
PASS: Voice Agent: перевод UE1 озвучен английским голосом
PASS: AI Worker: запись закрыта
===== E: UE2 -> *UE1: разовый перевод =====
PASS: SIP AS: перевод en-ru
===== F: SIP AS остановлен: UE1 -> UE2 =====
PASS: UE1: 200/INVITE без SIP AS (DefaultHandling)
```

там же в строке со ссылкой на `verify-5g-ue.sh` (`— шаги 6–8 и тесты A–C:`) заменить
`тесты A–C` на `тесты A–F`,
а строки ``- тест B: …`` и ``- тест C: …`` — на:

```markdown
- тест B: UE2 → UE1, оба вызова `CONFIRMED`, через 20 с RX больше 500 у обоих, BYE дошёл;
- тест C: `utterance_processed` с ненулевым `transcript_chars`;
- тест D: UE1 → UE2 — `languages=ru-en`, `record started ... legs=2`, английский перевод
  в ноге B, `recording_finalized` после BYE;
- тест E: UE2 → `*UE1` — `languages=en-ru`;
- тест F: `lab-sip-as` остановлен — UE1 → UE2 всё равно получает 200/INVITE.
```

В `docs/guide-4-5g-manual.md` строки 183–187 (тест B) заменить на:

```markdown
**Тест B. UE2 → UE1** (`UE1_MSISDN`, у нас 1001)

У UE1 в профиле translate и record, поэтому обычный вызов делает UE2. В PJSUA UE2: `m`,
`sip:1001@<IMS_DOMAIN>`. UE1 отвечает сам (`--auto-answer`), в обоих терминалах
`state changed to CONFIRMED`. На каждой стороне `cl` и `cc` (плеер → вызов), через 20 с
`dq` на обеих. Результат: RX больше 500 пакетов (20 с при ptime 20 мс — около 1000).
`h` в UE2; у UE1 — `DISCONNECTED`, BYE дошёл. Звонок UE1 → UE2 идёт с переводом и
записью — его проверяет тест D в `verify-5g-ue.sh`.
```

В `docs/guide-1-ims-core.md` строку 251
`Другие вызовы отличаются только шагами 9–12. При обычном вызове 1001 → 1002 SIP AS`
заменить на:

```markdown
Другие вызовы отличаются только шагами 9–12. При обычном вызове 1002 → 1001 SIP AS
```

- [ ] **Step 7: `CHANGELOG.md`**

Сразу после строки `## [Unreleased]` и пустой строки за ней вставить:

```markdown
- feat: услуги IMS по профилю абонента по 3GPP ISC: `scripts/provision.py` собирает iFC
  из `lab.env` (`*_SERVICES`, `*_LANGUAGE`), логические AS `translate.as`, `record.as` и
  `as` в одном `lab-sip-as`, `DefaultHandling 0`. translate — B2BUA с ногой B через
  S-CSCF и переводом в обе стороны через MRF; `*номер` — разовый перевод; record —
  уведомление каждой стороне (Voice Agent или RTPengine `play media`) и запись обеих
  сторон в один `transcript.txt`. SIP AS разделён на `core/` и `services/`. Обычный
  вызов в проверках — 1102 → 1101 и UE2 → UE1; новая проверка `verify-services.sh`.
```

- [ ] **Step 8: Offline-проверки**

Run: `python3 scripts/check.py`
Expected: `OFFLINE CHECKS: PASS — стенд не запускался, вызовы не проверены` (проверка ссылок
в документации проходит: `routing.py` больше нигде не упоминается).

Run: `git grep -n "routing.py\|1101 → 1102\|UE1 -> UE2 (1001" -- docs`
Expected: пустой вывод.

- [ ] **Step 9: Коммит**

```bash
git add docs/guide-1-ims-core.md docs/guide-2-ims-ai.md docs/guide-4-5g-manual.md \
  docs/guide-5-5g-scripts.md docs/project-layout.md CHANGELOG.md
git commit -m "docs: IMS services by subscriber profile"
```
