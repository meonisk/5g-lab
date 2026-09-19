"""Cross-platform, single-command startup for Windows and Linux Docker hosts."""

import argparse
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def provision_subscribers(bash):
    run(
        ["docker", "cp", str(ROOT / "scripts/subscribers.js"), "lab-mongo:/tmp/subscribers.js"],
        "Open5GS subscriber copy failed",
    )
    run(
        ["docker", "exec", "lab-mongo", "mongosh", "--quiet", "/tmp/subscribers.js"],
        "Open5GS subscriber provisioning failed",
    )
    run(
        [bash, "scripts/provision-ims-subscribers.sh", "--apply"],
        "IMS subscriber provisioning failed",
    )


def restart_registration_chain():
    stages = (
        (["lab-udr", "lab-udm", "lab-ausf", "lab-pcf", "lab-amf"], 5),
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


def run_gates(bash):
    gates = (
        "verify.sh",
        "verify-ims.sh",
        "verify-ims-registration.sh",
        "verify-ims-call.sh",
        "verify-voice-agent.sh",
        "verify-real-ai-stream.sh",
        "verify-transcription-recording.sh",
        "verify-bilingual-dialogue.sh",
        "verify-security.sh",
    )
    for gate in gates:
        run([bash, f"app/tests/integration/{gate}"], f"{gate} failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-verify", action="store_true")
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
    prepare_sctp()
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
    wait_for_pyhss(public_environment())
    provision_subscribers(bash)
    restart_registration_chain()
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
        run_gates(bash)
    print("LOCAL 5G IMS LAB: READY (STT and LLM warmed)")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
