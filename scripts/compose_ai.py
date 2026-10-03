"""Запуск Compose с явным CPU-профилем, без изменения lab.env и ключей стенда."""

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def profiles():
    return json.loads((ROOT / "app/config/ai-profiles.json").read_text(encoding="utf-8"))


def prepare(mode, partner=False):
    values = {**profiles()[mode], **CPU_SETTINGS}
    folder = ROOT / "local/ai-profiles" / mode
    folder.mkdir(parents=True, exist_ok=True)
    env_path = folder / "profile.env"
    env_path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )
    overlay_path = folder / "compose.yml"
    # JSON-кавычки допустимы в YAML и сохраняют пути Windows с пробелами.
    env_yaml = json.dumps(str(env_path))
    overlay = (
        "services:\n"
        "  ai-worker:\n"
        "    image: lab-ai-worker-cpu\n"
        f"    env_file: [{env_yaml}]\n"
        "  voice-agent:\n"
        "    image: lab-voice-agent-cpu\n"
        f"    env_file: [{env_yaml}]\n"
    )
    if mode != "baseline":
        mount = {
            "type": "bind",
            "source": str(ROOT / "local/models/opus-mt"),
            "target": "/translation-models",
            "read_only": True,
            "bind": {"create_host_path": False},
        }
        overlay = (
            "services:\n"
            "  ai-worker:\n"
            "    image: lab-ai-worker-cpu\n"
            f"    env_file: [{env_yaml}]\n"
            "    depends_on: !override\n"
            "      control-secret-init: {condition: service_completed_successfully}\n"
            f"    volumes:\n      - {json.dumps(mount)}\n"
            "  voice-agent:\n"
            "    image: lab-voice-agent-cpu\n"
            f"    env_file: [{env_yaml}]\n"
            "  llm-worker:\n    profiles: [unused-llm]\n"
            "  llm-model-init:\n    profiles: [unused-llm]\n"
        )
    overlay_path.write_text(overlay, encoding="utf-8")
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(ROOT / "app/config/lab.env"),
        "--env-file",
        str(ROOT / "local/secrets/ims.env"),
        "--env-file",
        str(env_path),
        "-f",
        str(ROOT / ("compose.partner.yml" if partner else "docker-compose.yml")),
        "-f",
        str(overlay_path),
    ]
    # Переменные shell приоритетнее --env-file; CPU-профиль должен оставаться CPU.
    environment = {**os.environ, **values}
    environment.pop("COMPOSE_PROFILES", None)
    return command, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=profiles())
    parser.add_argument("--partner", action="store_true")
    parser.add_argument("compose_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.compose_args:
        parser.error("Укажите команду Compose: config, build, up, ps, logs или stop")
    command, environment = prepare(args.mode, args.partner)
    if args.mode != "baseline" and args.compose_args[0] in {"up", "run"}:
        for direction in ("ru-en", "en-ru"):
            if not (ROOT / "local/models/opus-mt" / direction / "manifest.json").is_file():
                parser.error("Сначала выполните scripts/prepare_translation_models.py")
        subprocess.run(command + ["config", "--quiet"], env=environment, cwd=ROOT, check=True)
        # Старый Ollama иначе продолжит занимать RAM после переключения профиля.
        subprocess.run(
            command + ["stop", "llm-worker", "llm-model-init"],
            env=environment,
            cwd=ROOT,
            check=True,
        )
    completed = subprocess.run(command + args.compose_args, env=environment, cwd=ROOT)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
