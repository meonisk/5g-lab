"""Запуск передаваемой части IMS + AI без изменения ядра OAI партнёров."""

import argparse
import ipaddress
import subprocess
import sys
import time

from start_lab import (
    COMPOSE,
    ROOT,
    bash_command,
    guard_mysql_storage,
    public_environment,
    restart_ims_chain,
    run,
    wait_for_pyhss,
    wait_for_pyhss_cx,
    wait_ims_peers,
)

PARTNER_COMPOSE = [*COMPOSE[:-1], str(ROOT / "compose.partner.yml")]
IMS_SERVICES = ("dns", "mysql", "pyhss", "icscf", "scscf", "rtpengine", "pcscf")


def validate(settings):
    if not settings.get("IMS_PARENT_INTERFACE"):
        raise ValueError(
            "Укажите в IMS_PARENT_INTERFACE интерфейс Linux, подключённый к локальной сети IMS"
        )
    if not settings.get("IMS_ROUTE_GATEWAY"):
        raise ValueError("Укажите в IMS_ROUTE_GATEWAY адрес UPF или маршрутизатора к пулу UE")

    # Kamailio and PyHSS init scripts derive the realm from MCC/MNC themselves.
    mnc = settings["MNC"].zfill(3)
    expected = f"ims.mnc{mnc}.mcc{settings['MCC']}.3gppnetwork.org"
    if settings["IMS_DOMAIN"] != expected:
        raise ValueError(f"IMS_DOMAIN должен быть {expected} (выводится из MCC/MNC)")

    network = ipaddress.ip_network(settings["LAB_NETWORK_CIDR"])
    pool = ipaddress.ip_network(settings["IMS_UE_CIDR"])
    gateway = ipaddress.ip_address(settings["IMS_ROUTE_GATEWAY"])
    if gateway not in network or network.overlaps(pool):
        raise ValueError(
            "Шлюз IMS должен находиться в локальной сети; пул UE не должен с ней пересекаться"
        )
    keys = (
        "DNS_IP",
        "MYSQL_IP",
        "PYHSS_IP",
        "ICSCF_IP",
        "SCSCF_IP",
        "PCSCF_IP",
        "RTPENGINE_IP",
        "SIP_AS_IP",
        "AI_WORKER_IP",
        "VOICE_AGENT_IP",
    )
    addresses = [ipaddress.ip_address(settings[key]) for key in keys]
    if len(set(addresses)) != len(addresses) or gateway in addresses:
        raise ValueError("Адреса IMS-сервисов должны быть уникальными и отличаться от адреса шлюза")
    if any(address not in network for address in addresses):
        raise ValueError("Все адреса IMS-сервисов должны входить в LAB_NETWORK_CIDR")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ims-only", action="store_true", help="Запустить только IMS без загрузки AI-моделей"
    )
    parser.add_argument(
        "--check", action="store_true", help="Проверить конфигурацию без запуска контейнеров"
    )
    args = parser.parse_args()
    settings = public_environment()
    validate(settings)
    run(
        [sys.executable, "scripts/initialize_local.py", "--ims-only"],
        "Не удалось подготовить ключи IMS",
    )
    run(
        PARTNER_COMPOSE + ["config", "--quiet"],
        "Конфигурация Compose для партнёров не прошла проверку",
    )
    if args.check:
        print(
            "PARTNER CONFIG: VALID — конфигурация корректна; доступность сети и звонки не проверены"
        )
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError(
            "Для развёртывания macvlan нужен Linux-хост или виртуальная машина с Linux"
        )
    guard_mysql_storage()
    services = list(IMS_SERVICES) if args.ims_only else []
    run(PARTNER_COMPOSE + ["up", "-d", "--build", *services], "Не удалось запустить IMS + AI")
    wait_for_pyhss(settings)
    run(
        [bash_command(), "scripts/provision-ims-subscribers.sh", "--apply"],
        "Не удалось настроить IMS",
    )
    wait_for_pyhss_cx(settings)
    restart_ims_chain()
    wait_ims_peers(settings)
    if not args.ims_only:
        deadline = time.monotonic() + float(settings["LLM_WARMUP_TIMEOUT_SECONDS"]) + 60
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", "lab-ai-worker"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "healthy":
                break
            time.sleep(2)
        else:
            raise RuntimeError("AI-модели не стали готовы за отведённое время")
    print(
        "PARTNER SERVICES: STARTED — сервисы запущены; регистрация внешних UE, SIP/RTP и вызов AI: UNVERIFIED"
    )


if __name__ == "__main__":
    from script_console import configure_output

    configure_output()
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
