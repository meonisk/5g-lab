"""Generate private bilingual call tracks with the pinned Piper image."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "app/tests/fixtures/render_dialogue.py"
PUBLIC_ENV = ROOT / "app/config/lab.env"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    design = (
        (ROOT / arguments.design).resolve()
        if not arguments.design.is_absolute()
        else arguments.design
    )
    output = (
        (ROOT / arguments.output).resolve()
        if not arguments.output.is_absolute()
        else arguments.output
    )
    output.mkdir(parents=True, exist_ok=True)

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "1",
        "--memory",
        "512m",
    ]
    # Native Linux bind mounts otherwise receive root-owned generated files.
    if os.name != "nt":
        command += ["--user", f"{os.getuid()}:{os.getgid()}"]
    command += [
        "--env-file",
        str(PUBLIC_ENV),
        "--mount",
        f"type=bind,src={design},dst=/fixture/design.json,readonly",
        "--mount",
        f"type=bind,src={output},dst=/fixture/output",
        "--mount",
        f"type=bind,src={GENERATOR},dst=/fixture/render_dialogue.py,readonly",
        "--entrypoint",
        "python",
        "lab-voice-agent",
        "/fixture/render_dialogue.py",
        "/fixture/design.json",
        "/fixture/output",
    ]
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
