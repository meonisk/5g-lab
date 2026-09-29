"""Cross-platform, single-command startup for Windows and Linux Docker hosts."""

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
    """Never let Compose replace a legacy MySQL writable layer before migration."""
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
        raise RuntimeError("Could not inspect MySQL storage mounts") from error
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
        "lab-mysql has no persistent mysql-data mount; migrate its stopped "
        "datadir and verify the rollback receipt before Compose can recreate it"
    )


def bash_command():
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if sys.platform == "win32" and git_bash.exists():
        return str(git_bash)
    executable = shutil.which("bash")
    if not executable:
        raise RuntimeError("Install Git for Windows or bash on Linux")
    return executable


def prepare_sctp():
    if sys.platform == "win32":
        run(
            ["powershell.exe", "-NoProfile", "-File", "scripts/prepare-host.ps1"],
            "Could not load SCTP in Docker Desktop",
        )
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError("The SCTP path currently supports Windows/WSL2 and Linux")

    command = ["docker", "run", "--rm", "--privileged"]
    if Path("/lib/modules").exists():
        command += ["--mount", "type=bind,src=/lib/modules,dst=/lib/modules,readonly"]
    command += [
        "alpine:3.20",
        "sh",
        "-c",
        "modprobe sctp 2>/dev/null || true; grep -q SCTP /proc/net/protocols",
    ]
    run(command, "SCTP is unavailable; load the host sctp kernel module")
    print("SCTP: loaded")


def generate_dialogues():
    run(COMPOSE + ["build", "voice-agent"], "Voice Agent build failed")
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
            "Piper dialogue generation failed",
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
    raise RuntimeError("PyHSS REST API did not become ready")


def wait_for_pyhss_cx(settings):
    """Require the Cx listener before restarting Diameter peers."""
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
    raise RuntimeError("PyHSS Diameter Cx listener did not become ready")


def provision_subscribers(bash):
    run(
        [sys.executable, "scripts/oai_subscribers.py"],
        "OAI subscriber provisioning failed",
    )
    run(
        [bash, "scripts/provision-ims-subscribers.sh", "--apply"],
        "IMS subscriber provisioning failed",
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
            "Registration-chain restart failed",
            stdout=subprocess.DEVNULL,
        )
        time.sleep(delay)


def restart_ims_chain():
    # CSCFs started by Compose may have initialized before PyHSS/Cx was ready.
    run(
        ["docker", "restart", "lab-icscf", "lab-scscf"],
        "IMS Diameter peer restart failed",
        stdout=subprocess.DEVNULL,
    )
    run(
        ["docker", "restart", "lab-pcscf"],
        "IMS P-CSCF restart failed",
        stdout=subprocess.DEVNULL,
    )


def run_gates(bash, gates):
    for gate in gates:
        run([bash, f"app/tests/integration/{gate}"], f"{gate} failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--base-only", action="store_true")
    arguments = parser.parse_args()
    if not shutil.which("docker"):
        raise RuntimeError("Docker with Linux containers is required")
    run(
        ["docker", "info", "--format", "{{.OSType}}"],
        "Start Docker first",
        stdout=subprocess.DEVNULL,
    )
    bash = bash_command()

    run([sys.executable, "scripts/initialize_local.py"], "Local initialization failed")
    guard_mysql_storage()
    prepare_sctp()
    # Database schema must exist before provisioning and before UE authentication.
    run(COMPOSE + ["up", "-d", "--wait", "oai-db"], "OAI database startup failed")
    run([sys.executable, "scripts/oai_subscribers.py"], "OAI provisioning failed")
    if arguments.base_only:
        # Base services have no AI dependencies; honor core health dependency ordering.
        run(
            COMPOSE + ["up", "-d", "--build", *BASE_SERVICES],
            "Base Docker Compose startup failed",
        )
    else:
        generate_dialogues()
        run(COMPOSE + ["up", "-d", "--build"], "Docker Compose startup failed")
        run(
            ["docker", "wait", "lab-llm-model-init"],
            "LLM initialization wait failed",
            stdout=subprocess.DEVNULL,
        )
        result = run(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", "lab-llm-model-init"],
            "LLM initialization inspection failed",
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != "0":
            raise RuntimeError("Pinned LLM initialization failed")
    settings = public_environment()
    wait_for_pyhss(settings)
    provision_subscribers(bash)
    wait_for_pyhss_cx(settings)
    restart_ims_chain()
    wait_ims_peers(settings)
    restart_registration_chain()
    if arguments.base_only:
        # Base readiness is mandatory even for --skip-verify.
        run_gates(bash, BASE_GATES)
        print("LOCAL 5G IMS BASE: READY (network and registration gates passed)")
        return
    # Even --skip-verify must not advertise readiness while models are cold.
    deadline = time.monotonic() + float(public_environment()["LLM_WARMUP_TIMEOUT_SECONDS"]) + 60
    while time.monotonic() < deadline:
        health = run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", "lab-ai-worker"],
            "Could not inspect AI readiness",
            capture_output=True,
            text=True,
        )
        if health.stdout.strip() == "healthy":
            break
        time.sleep(2)
    else:
        raise RuntimeError("STT/LLM warmup failed; inspect lab-ai-worker logs")
    if not arguments.skip_verify:
        run_gates(bash, BASE_GATES + SERVICE_GATES)
        print("LOCAL 5G IMS LAB: READY (all startup gates passed)")
    else:
        print("LOCAL 5G IMS LAB: STARTED/UNVERIFIED (STT and LLM warmed)")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
