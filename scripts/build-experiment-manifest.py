"""Describe one private end-to-end interpreter experiment and its WAV files."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wav_record(path: Path, role: str, description: str) -> dict:
    record = {
        "path": path.as_posix(),
        "role": role,
        "description": description,
        "bytes": path.stat().st_size,
        "sha256": file_digest(path),
    }
    try:
        with wave.open(str(path), "rb") as audio:
            frame_count = audio.getnframes()
            sample_rate = audio.getframerate()
            record.update(
                {
                    "valid_wav": True,
                    "duration_seconds": round(frame_count / sample_rate, 3),
                    "sample_rate_hz": sample_rate,
                    "channels": audio.getnchannels(),
                    "sample_width_bytes": audio.getsampwidth(),
                    "frames": frame_count,
                }
            )
    except (EOFError, wave.Error) as error:
        record.update({"valid_wav": False, "format_error": str(error)})
    return record


def load_test_result(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as error:
        return {
            "pass": False,
            "parse_error": str(error),
            "raw_output_path": path.as_posix(),
        }


def git_revision(repository: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_changes(repository: Path) -> list[str]:
    output = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in output.splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_directory", type=Path)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--finished-at", required=True)
    parser.add_argument("--test-exit-code", type=int, required=True)
    arguments = parser.parse_args()

    experiment_directory = arguments.experiment_directory.resolve()
    relative = lambda name: experiment_directory / name
    test_result_path = relative("metadata/test-result.json")
    test_result = load_test_result(test_result_path)

    audio_files = [
        wav_record(
            relative("input/russian-user-speaks.wav"),
            "phone_microphone_input",
            "Complete synthetic Russian speech injected into the Russian phone.",
        ),
        wav_record(
            relative("input/english-user-speaks.wav"),
            "phone_microphone_input",
            "Complete synthetic English speech injected into the English phone.",
        ),
        wav_record(
            relative("output/russian-user-hears.wav"),
            "phone_received_audio",
            "Complete remote audio recorded by the Russian phone call leg.",
        ),
        wav_record(
            relative("output/english-user-hears.wav"),
            "phone_received_audio",
            "Complete remote audio recorded by the English phone call leg.",
        ),
    ]
    for record in audio_files:
        record["path"] = Path(record["path"]).relative_to(experiment_directory).as_posix()

    log_files = sorted(
        path.relative_to(experiment_directory).as_posix() for path in relative("logs").glob("*.log")
    )
    worktree_changes = git_changes(arguments.repository)
    audio_is_valid = all(record.get("valid_wav") for record in audio_files)
    experiment_passed = (
        arguments.test_exit_code == 0
        and test_result.get("pass")
        and audio_is_valid
        and not worktree_changes
    )
    manifest = {
        "schema_version": "1.0",
        "experiment_id": experiment_directory.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": arguments.started_at,
        "finished_at": arguments.finished_at,
        "git_revision": git_revision(arguments.repository),
        "git_worktree_clean": not worktree_changes,
        "git_worktree_changes": worktree_changes,
        "status": "PASS" if experiment_passed else "FAIL",
        "test_exit_code": arguments.test_exit_code,
        "purpose": (
            "Observe a complete two-user Russian/English IMS interpreter call "
            "from phone-side source WAV through STT, LLM translation, TTS and "
            "phone-side received WAV."
        ),
        "boundary": (
            "The source and received WAV files are captured at the two pjsua "
            "subscriber endpoints. Service logs cover the same wall-clock run."
        ),
        "audio_files": audio_files,
        "test_result": test_result,
        "logs": log_files,
        "privacy": "PRIVATE: contains complete speech audio and must not be committed.",
    }
    relative("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
