"""Запуск стенда одной командой на Windows и Linux с Docker."""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ims_readiness import wait_ims_peers  # noqa: E402

PUBLIC_ENV = ROOT / "app/config/lab.env"
SECRET_ENV = ROOT / "local/secrets/ims.env"
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(PUBLIC_ENV),
    "--env-file",
    str(SECRET_ENV),
    "-f",
    str(ROOT / "docker-compose.yml"),
]
BASE_SERVICES = (
    "oai-db",
    "nrf",
    "udr",
    "udm",
    "ausf",
    "upf",
    "smf",
    "amf",
    "gnb",
    "ue1",
    "ue2",
    "dns",
    "mysql",
    "pyhss",
    "icscf",
    "scscf",
    "rtpengine",
    "pcscf",
    "sipue1",
    "sipue2",
)
BASE_GATES = ("verify.sh", "verify-ims.sh", "verify-ims-registration.sh")
SERVICE_GATES = (
    "verify-ims-call.sh",
    "verify-voice-agent.sh",
    "verify-real-ai-stream.sh",
    "verify-transcription-recording.sh",
    "verify-bilingual-dialogue.sh",
    "verify-security.sh",
)


def run(command, message, **kwargs):
    try:
        return subprocess.run(command, cwd=ROOT, check=True, **kwargs)
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(message) from error


def public_environment():
    values = {}
    for line in PUBLIC_ENV.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def guard_mysql_storage():
    """Не позволяем Compose заменить старое хранилище MySQL до переноса данных."""
    inspection = subprocess.run(
        [
            "docker",
            "inspect",
            "lab-mysql",
            "--format",
            "{{.Id}}|{{.State.Status}}|{{json .Mounts}}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if inspection.returncode:
        return
    try:
        container_id, state, mount_json = inspection.stdout.strip().split("|", 2)
        mounts = json.loads(mount_json)
    except (ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Не удалось проверить подключённое хранилище MySQL") from error
    if any(
        mount.get("Type") == "volume"
        and mount.get("Destination") == "/var/lib/mysql"
        and mount.get("Name") == "lab-docker_mysql-data"
        for mount in mounts
    ):
        return
    receipt_path = ROOT / "local/private/mysql-storage-migration.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        backup = Path(receipt["backup_dir"])
        matching = (
            state == "exited"
            and receipt["source_container_id"] == container_id
            and receipt["volume"] == "lab-docker_mysql-data"
            and backup.resolve().is_relative_to((ROOT / "local/private").resolve())
            and (backup / "ibdata1").is_file()
            and (backup / "ims_hss_db").is_dir()
        )
    except (OSError, ValueError, KeyError, TypeError):
        matching = False
    if matching:
        volume = subprocess.run(
            ["docker", "volume", "inspect", "lab-docker_mysql-data"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        image = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                receipt["rollback_image"],
                "--format",
                "{{.Id}}",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            volume.returncode == 0
            and image.returncode == 0
            and image.stdout.strip() == receipt["rollback_image_id"]
        ):
            return
    raise RuntimeError(
        "У lab-mysql не подключён постоянный том mysql-data; перенесите данные остановленной "
        "базы и проверьте подтверждение отката перед пересозданием контейнера"
    )


def bash_command():
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if sys.platform == "win32" and git_bash.exists():
        return str(git_bash)
    executable = shutil.which("bash")
    if not executable:
        raise RuntimeError("Установите Git for Windows или Bash на Linux")
    return executable


def prepare_sctp():
    if sys.platform == "win32":
        run(
            ["powershell.exe", "-NoProfile", "-File", "scripts/prepare-host.ps1"],
            "Не удалось загрузить SCTP в Docker Desktop",
        )
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Подготовка SCTP поддерживается на Windows/WSL2 и Linux")

    command = ["docker", "run", "--rm", "--privileged"]
    if Path("/lib/modules").exists():
        command += ["--mount", "type=bind,src=/lib/modules,dst=/lib/modules,readonly"]
    command += [
        "alpine:3.20",
        "sh",
        "-c",
        "modprobe sctp 2>/dev/null || true; grep -q SCTP /proc/net/protocols",
    ]
    run(command, "SCTP недоступен; загрузите модуль sctp в ядро хоста")
    print("SCTP: loaded — модуль загружен")


def generate_dialogues():
    run(COMPOSE + ["build", "voice-agent"], "Не удалось собрать Voice Agent")
    for design, output in (
        ("app/tests/fixtures/bilingual-dialogue-v1.json", "local/private/dialogue"),
        ("app/tests/fixtures/interpreter-dialogue-v2.json", "local/private/interpreter"),
    ):
        run(
            [
                sys.executable,
                "scripts/generate_dialogue.py",
                "--design",
                design,
                "--output",
                output,
            ],
            "Не удалось создать тестовый диалог с помощью Piper",
        )


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
    """Перед перезапуском узлов Diameter дожидаемся готовности Cx."""
    probe = (
        "import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 2).close()"
    )
    for _ in range(30):
        result = subprocess.run(
            [
                "docker",
                "exec",
                "lab-pyhss",
                "python3",
                "-c",
                probe,
                settings["PYHSS_IP"],
                settings["PYHSS_BIND_PORT"],
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("Слушатель Diameter Cx в PyHSS не стал доступен")


def provision_subscribers(bash):
    run(
        [sys.executable, "scripts/oai_subscribers.py"],
        "Не удалось настроить абонентов OAI",
    )
    run(
        [bash, "scripts/provision-ims-subscribers.sh", "--apply"],
        "Не удалось настроить абонентов IMS",
    )


def restart_registration_chain():
    stages = (
        (["lab-udr", "lab-udm", "lab-ausf", "lab-amf"], 5),
        (["lab-gnb"], 5),
        (["lab-ue1", "lab-ue2"], 15),
        (["lab-sipue1", "lab-sipue2"], 12),
    )
    for containers, delay in stages:
        run(
            ["docker", "restart", *containers],
            "Не удалось перезапустить компоненты регистрации",
            stdout=subprocess.DEVNULL,
        )
        time.sleep(delay)


def restart_ims_chain():
    # Compose мог запустить CSCF до готовности PyHSS/Cx.
    run(
        ["docker", "restart", "lab-icscf", "lab-scscf"],
        "Не удалось перезапустить узлы Diameter в IMS",
        stdout=subprocess.DEVNULL,
    )
    run(
        ["docker", "restart", "lab-pcscf"],
        "Не удалось перезапустить P-CSCF",
        stdout=subprocess.DEVNULL,
    )


def run_gates(bash, gates):
    for gate in gates:
        run([bash, f"app/tests/integration/{gate}"], f"Проверка {gate} не пройдена")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Пропустить полные проверки; готовность звонков не подтверждается",
    )
    parser.add_argument(
        "--base-only", action="store_true", help="Запустить и проверить сеть и IMS без AI"
    )
    arguments = parser.parse_args()
    if not shutil.which("docker"):
        raise RuntimeError("Требуется Docker с Linux-контейнерами")
    run(
        ["docker", "info", "--format", "{{.OSType}}"],
        "Сначала запустите Docker",
        stdout=subprocess.DEVNULL,
    )
    bash = bash_command()

    run(
        [sys.executable, "scripts/initialize_local.py"],
        "Не удалось подготовить локальное окружение",
    )
    guard_mysql_storage()
    prepare_sctp()
    # Схема БД нужна до настройки абонентов и аутентификации UE.
    run(COMPOSE + ["up", "-d", "--wait", "oai-db"], "Не удалось запустить базу OAI")
    run([sys.executable, "scripts/oai_subscribers.py"], "Не удалось настроить OAI")
    if arguments.base_only:
        # Базовые сервисы не зависят от AI; соблюдаем порядок готовности компонентов ядра.
        run(
            COMPOSE + ["up", "-d", "--build", *BASE_SERVICES],
            "Не удалось запустить базовые сервисы Compose",
        )
    else:
        generate_dialogues()
        run(COMPOSE + ["up", "-d", "--build"], "Не удалось запустить сервисы Compose")
        run(
            ["docker", "wait", "lab-llm-model-init"],
            "Ошибка ожидания инициализации LLM",
            stdout=subprocess.DEVNULL,
        )
        result = run(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", "lab-llm-model-init"],
            "Не удалось проверить результат инициализации LLM",
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != "0":
            raise RuntimeError("Не удалось подготовить закреплённую версию LLM")
    settings = public_environment()
    wait_for_pyhss(settings)
    provision_subscribers(bash)
    wait_for_pyhss_cx(settings)
    restart_ims_chain()
    wait_ims_peers(settings)
    restart_registration_chain()
    if arguments.base_only:
        # Базовые проверки обязательны даже при --skip-verify.
        run_gates(bash, BASE_GATES)
        print("LOCAL 5G IMS BASE: READY — базовый стенд готов, сеть и регистрация проверены")
        return
    # Даже при --skip-verify сначала дожидаемся прогрева моделей.
    deadline = time.monotonic() + float(public_environment()["LLM_WARMUP_TIMEOUT_SECONDS"]) + 60
    while time.monotonic() < deadline:
        health = run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", "lab-ai-worker"],
            "Не удалось проверить готовность AI",
            capture_output=True,
            text=True,
        )
        if health.stdout.strip() == "healthy":
            break
        time.sleep(2)
    else:
        raise RuntimeError("Не удалось прогреть STT/LLM; проверьте журналы lab-ai-worker")
    if not arguments.skip_verify:
        run_gates(bash, BASE_GATES + SERVICE_GATES)
        print("LOCAL 5G IMS LAB: READY — стенд готов, все проверки запуска пройдены")
    else:
        print(
            "LOCAL 5G IMS LAB: STARTED/UNVERIFIED — сервисы запущены, STT/LLM прогреты; проверки пропущены"
        )


if __name__ == "__main__":
    from script_console import configure_output

    configure_output()
    try:
        main()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
