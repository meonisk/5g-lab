"""Проверка серверных предпосылок; Docker-тесты не подтверждают работу телефона."""

import json
import subprocess


def run(container, *arguments):
    try:
        result = subprocess.run(
            ["docker", "exec", container, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def research_sims_check():
    """Только чтение: заведены ли исследовательские SIM в PyHSS и локальном UDR."""
    import research_sims

    try:
        env = research_sims.environment()
        sims = research_sims.load(env)
        # Без контейнера локального OAI ядро у партнёров: проверяем только PyHSS.
        ims_only = not run("lab-oai-db", "echo", "ok")
        report = research_sims.status(env, sims, ims_only=ims_only)
    except (OSError, RuntimeError, ValueError) as error:
        return {"check": "research_sims_provisioned", "status": "FAIL", "detail": str(error)}
    found = {key: len(report[key]) for key in ("pyhss", "oai_udr") if key in report}
    complete = all(count == len(sims) for count in found.values())
    return {
        "check": "research_sims_provisioned",
        "status": "PASS" if complete else "FAIL",
        "detail": {"sims": len(sims), **found},
        "scope": "Записи в базах; совпадение ключей с картой проверяет только телефон",
    }


def inspect():
    codecs = run("lab-rtpengine", "rtpengine", "--codecs")
    supported = dict(line.strip().split(":", 1) for line in codecs.splitlines() if ":" in line)
    # Читаем только признак функции, не всю конфигурацию с ключами БД.
    ipsec = run("lab-pcscf", "grep", "-x", "#!define WITH_IPSEC", "/etc/kamailio_pcscf/pcscf.cfg")
    checks = [
        {"check": "rtpengine_reachable", "status": "PASS" if codecs else "FAIL"},
        {
            "check": "pcscf_ipsec_configured",
            "status": "PASS" if ipsec else "FAIL",
            "scope": "Проверена только настройка; Security-Verify от UE и XFRM SA не подтверждены",
        },
    ]
    for codec in ("PCMU", "AMR", "AMR-WB"):
        value = supported.get(codec, "unavailable").strip()
        checks.append(
            {
                "check": f"codec_{codec}_bidirectional",
                "status": "PASS" if value == "fully supported" else "FAIL",
                "detail": value,
            }
        )
    checks.append(research_sims_check())
    for name in (
        "native_phone_and_sim_profile",
        "radio_and_5gs_registration",
        "automatic_pcscf_discovery",
        "ims_aka_ipsec_registration",
        "amr_ai_sdp_and_bidirectional_audio",
        "prack_update_preconditions_qos",
        "incoming_outgoing_calls",
        "ai_translation_native_dialer",
        "reattach_recovery",
    ):
        checks.append({"check": name, "status": "UNVERIFIED"})
    return {
        "status": "NOT_READY",
        "checks": checks,
        "scope": "Проверка сервера; приёмка настоящего телефона выполняется отдельно",
    }


def main():
    print(json.dumps(inspect(), indent=2, ensure_ascii=False))
    return 1  # Серверные возможности не подтверждают работу физического устройства.


if __name__ == "__main__":
    from script_console import configure_output

    configure_output()
    raise SystemExit(main())
