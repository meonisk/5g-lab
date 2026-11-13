"""Временная услуга вызываемого (term-iFC) у SIPUE2 — для проверки отказа AS на стороне B.

    python3 app/tests/integration/term_ifc.py install   # iFC SIPUE2 + term-правило на as
    python3 app/tests/integration/term_ifc.py restore   # iFC SIPUE2 из lab.env

Файл iFC тот же (ifc-SIPUE2.xml), меняется только содержимое: S-CSCF прочитает его при
следующем SAR, поэтому после install/restore нужны docker restart lab-scscf и новая
регистрация клиентов. Правило ведёт на lab-sip-as; тест держит его остановленным.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import provision  # noqa: E402

SUBSCRIBER = "SIPUE2"
TERM_PRIORITY = 50
TERMINATING_INVITE = provision.spt(0, "<Method>INVITE</Method>") + provision.spt(
    1, "<SessionCase>1</SessionCase>"
)


def ifc(settings, with_term):
    entry = next(e for e in provision.subscribers(settings) if e["name"] == SUBSCRIBER)
    text = provision.ifc_xml(settings, entry["services"])
    if not with_term:
        return text
    server = provision.as_server(settings, provision.NUMBERS_HOST)
    rule = provision.criteria(TERM_PRIORITY, server, TERMINATING_INVITE)
    return text.replace(provision.IFC_TAIL, rule + provision.IFC_TAIL, 1)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("install", "restore"):
        raise SystemExit(__doc__)
    settings = provision.read_env()
    provision.install_ifc(SUBSCRIBER, ifc(settings, action == "install"))
    print(f"{SUBSCRIBER}: term-iFC {'installed' if action == 'install' else 'removed'}")


if __name__ == "__main__":
    main()
