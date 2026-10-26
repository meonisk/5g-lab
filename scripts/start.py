"""Запуск IMS + AI рядом с работающим ядром OAI: проверка, сборка, абоненты, готовность."""

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

from provision import LAB_ENV, ROOT, provision, read_env

COMPOSE = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(LAB_ENV)]
IMS_SERVICES = ("dns", "mysql", "pyhss", "icscf", "scscf", "rtpengine", "pcscf")
STATIC_ADDRESSES = (
    "DNS_IP",
    "RTPENGINE_IP",
    "MYSQL_IP",
    "PYHSS_IP",
    "ICSCF_IP",
    "SCSCF_IP",
    "PCSCF_IP",
    "SIP_AS_IP",
    "AI_WORKER_IP",
    "VOICE_AGENT_IP",
    "SIPUE1_IP",
    "SIPUE2_IP",
    "LLM_INIT_IP",
)
# CPU-режимы не должны случайно унаследовать GPU или потоковый перевод из lab.env.
CPU_SETTINGS = {
    "AI_DEVICE": "cpu",
    "AI_ENABLE_CUDA": "0",
    "AI_COMPUTE_TYPE": "int8",
    "AI_CONTAINER_RUNTIME": "runc",
    "AI_GPU_DEVICES": "void",
    "LLM_CONTAINER_RUNTIME": "runc",
    "LLM_GPU_DEVICES": "void",
    "AI_STREAMING_ENABLED": "0",
}
CX_APP = "16777216:10415"


def run(command, message, **kwargs):
    try:
        return subprocess.run(command, cwd=ROOT, check=True, **kwargs)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(message) from error


def profiles():
    return json.loads((ROOT / "app/config/ai-profiles.json").read_text(encoding="utf-8"))


def validate(settings):
    # Kamailio и PyHSS сами выводят realm из MCC/MNC; расхождение ломает Cx.
    expected = f"ims.mnc{settings['MNC'].zfill(3)}.mcc{settings['MCC']}.3gppnetwork.org"
    if settings["IMS_DOMAIN"] != expected:
        raise ValueError(f"IMS_DOMAIN должен быть {expected} (выводится из MCC/MNC)")

    network = ipaddress.ip_network(settings["LAB_NETWORK_CIDR"])
    upf = ipaddress.ip_address(settings["UPF_IP"])
    pools = [ipaddress.ip_network(settings[key]) for key in ("IMS_UE_CIDR", "INTERNET_UE_CIDR")]
    if upf not in network or any(network.overlaps(pool) for pool in pools):
        raise ValueError("UPF_IP должен быть в LAB_NETWORK_CIDR, а пулы UE — вне её")
    addresses = [ipaddress.ip_address(settings[key]) for key in STATIC_ADDRESSES]
    if len(set(addresses)) != len(addresses) or upf in addresses:
        raise ValueError("Адреса IMS и AI должны быть уникальными и не совпадать с UPF_IP")
    if any(address not in network for address in addresses):
        raise ValueError("Все адреса IMS и AI должны входить в LAB_NETWORK_CIDR")


def check_core_network(settings):
    """Сеть создаёт ядро; занятый чужим контейнером адрес иначе всплывёт только при up."""
    name = settings["CORE_NETWORK_NAME"]
    result = subprocess.run(
        ["docker", "network", "inspect", name], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"Docker-сеть ядра {name} не найдена: сначала запустите ядро OAI")
    network = json.loads(result.stdout)[0]
    subnets = {item.get("Subnet") for item in network["IPAM"]["Config"]}
    if settings["LAB_NETWORK_CIDR"] not in subnets:
        raise RuntimeError(f"Подсеть сети {name}: {', '.join(sorted(subnets))}; поправьте lab.env")
    ours = {settings[key]: key for key in STATIC_ADDRESSES}
    for container in network.get("Containers", {}).values():
        address = container["IPv4Address"].split("/")[0]
        if address in ours and not container["Name"].startswith("lab-"):
            raise RuntimeError(
                f"{ours[address]}={address} уже занят контейнером {container['Name']}"
            )


def compose_command(mode):
    """baseline — это lab.env как есть; CPU-режим добавляет env и overlay в local/."""
    if mode == "baseline":
        return COMPOSE + ["-f", str(ROOT / "docker-compose.yml")], None
    values = {**profiles()[mode], **CPU_SETTINGS}
    folder = ROOT / "local/ai-profiles" / mode
    folder.mkdir(parents=True, exist_ok=True)
    env_path = folder / "profile.env"
    env_path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    env_yaml = json.dumps(str(env_path))
    # Overlay заменяет env_file сервиса: lab.env первым, режим поверх него.
    lab_yaml = json.dumps(str(LAB_ENV))
    models = json.dumps(
        {
            "type": "bind",
            "source": str(ROOT / "local/models/opus-mt"),
            "target": "/translation-models",
            "read_only": True,
            "bind": {"create_host_path": False},
        }
    )
    # OPUS-MT заменяет Qwen: Ollama и его загрузчик выводятся в неиспользуемый профиль.
    overlay = (
        "services:\n"
        "  ai-worker:\n"
        "    image: lab-ai-worker-cpu\n"
        f"    env_file: [{lab_yaml}, {env_yaml}]\n"
        "    depends_on: !override\n"
        "      stand-init: {condition: service_completed_successfully}\n"
        f"    volumes:\n      - {models}\n"
        "  voice-agent:\n"
        "    image: lab-voice-agent-cpu\n"
        f"    env_file: [{lab_yaml}, {env_yaml}]\n"
        "  llm-worker:\n    profiles: [unused-llm]\n"
        "  llm-model-init:\n    profiles: [unused-llm]\n"
    )
    overlay_path = folder / "compose.yml"
    overlay_path.write_text(overlay, encoding="utf-8")
    command = COMPOSE + ["--env-file", str(env_path), "-f", str(ROOT / "docker-compose.yml")]
    return command + ["-f", str(overlay_path)], values


def wait_for_pyhss(settings):
    url = (
        f"http://{settings['PYHSS_API_BIND']}:{settings['PYHSS_API_PORT']}"
        "/ims_subscriber/list?page=0&page_size=1"
    )
    for _ in range(36):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(5)
    raise RuntimeError("REST API PyHSS не стал доступен за отведённое время")


def wait_for_pyhss_cx(settings):
    """Перед перезапуском узлов Diameter дожидаемся слушателя Cx в PyHSS."""
    probe = "import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 2)"
    for _ in range(30):
        command = ["docker", "exec", "lab-pyhss", "python3", "-c", probe]
        result = subprocess.run(
            command + [settings["PYHSS_IP"], settings["PYHSS_BIND_PORT"]],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("Слушатель Diameter Cx в PyHSS не стал доступен")


def connected_hss_peer(output, domain):
    """Cx-соединение готово, когда cdp.list_peers показывает hss в I_Open/R_Open."""
    match = re.search(
        rf"(?m)^\s*FQDN:\s*{re.escape(f'hss.{domain}')}\s*\n"
        r"\s*Details:\s*\{\s*\n\s*State:\s*(I_Open|R_Open)\b",
        output,
    )
    if not match:
        return False
    next_peer = output.find("\n\t\tFQDN:", match.end())
    block = output[match.start() : next_peer if next_peer >= 0 else None]
    return CX_APP in block and "Disabled: False" in block


def ims_peers_ready(settings):
    """Одна проверка: у I-CSCF и S-CSCF открыто Cx-соединение с HSS."""
    for container in ("lab-icscf", "lab-scscf"):
        try:
            result = subprocess.run(
                ["docker", "exec", container, "kamcmd", "cdp.list_peers"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode or not connected_hss_peer(result.stdout, settings["IMS_DOMAIN"]):
            return False
    return True


def wait_ims_peers(settings, timeout_seconds=60):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ims_peers_ready(settings):
            return
        time.sleep(2)
    raise RuntimeError("Соединения I/S-CSCF с HSS Cx не достигли состояния I_Open/R_Open")


def restart_ims_chain():
    # Compose мог поднять CSCF раньше, чем PyHSS начал принимать Cx.
    for containers in (["lab-icscf", "lab-scscf"], ["lab-pcscf"]):
        run(
            ["docker", "restart", *containers], "Не удалось перезапустить CSCF", capture_output=True
        )


def wait_ai_healthy(settings):
    deadline = time.monotonic() + float(settings["LLM_WARMUP_TIMEOUT_SECONDS"]) + 60
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", "lab-ai-worker"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip() == "healthy":
            return
        time.sleep(2)
    raise RuntimeError("AI Worker не стал healthy: docker logs lab-ai-worker")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=profiles(), default="baseline", help="Режим AI")
    parser.add_argument("--ims-only", action="store_true", help="Только IMS, без AI-моделей")
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию и выйти")
    args = parser.parse_args()

    settings = read_env()
    validate(settings)
    compose, mode_values = compose_command(args.mode)
    # Shell-переменные приоритетнее --env-file; режим не должен от них зависеть.
    environment = None if mode_values is None else {**os.environ, **mode_values}
    run(compose + ["config", "--quiet"], "Конфигурация Compose не прошла проверку", env=environment)
    check_core_network(settings)
    if args.check:
        print("CONFIG: VALID — lab.env, Compose и сеть ядра согласованы; вызовы не проверены")
        return

    for folder in ("recordings", "interpreter"):
        (ROOT / "local/private" / folder).mkdir(parents=True, exist_ok=True)
    if mode_values is not None and not args.ims_only:
        for direction in ("ru-en", "en-ru"):
            if not (ROOT / "local/models/opus-mt" / direction / "manifest.json").is_file():
                raise RuntimeError("Сначала выполните scripts/prepare_translation_models.py")
        # Контейнеры Ollama не нужны в CPU-режиме: удаляем, а не оставляем висеть.
        run(
            compose + ["rm", "-sf", "llm-worker", "llm-model-init"],
            "Не удалось удалить контейнеры LLM",
            env=environment,
        )

    services = list(IMS_SERVICES) if args.ims_only else []
    run(
        compose + ["up", "-d", "--build", *services],
        "Не удалось запустить IMS + AI",
        env=environment,
    )
    wait_for_pyhss(settings)
    provision(settings)
    # Работающую IMS не трогаем: перезапуск CSCF сбросил бы регистрации телефонов.
    # Перезапуск нужен, только если CSCF поднялись раньше, чем HSS принял Cx.
    if not ims_peers_ready(settings):
        wait_for_pyhss_cx(settings)
        restart_ims_chain()
        wait_ims_peers(settings)
    if not args.ims_only:
        wait_ai_healthy(settings)
    scope = "IMS" if args.ims_only else f"IMS + AI ({args.mode})"
    print(f"STARTED: {scope} — сервисы готовы; вызовы проверяются тестами app/tests/integration")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
