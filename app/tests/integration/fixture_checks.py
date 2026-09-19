"""Integrity checks for ignored synthetic WAV fixtures used by live gates."""

import hashlib
import json
import wave


def verify_interpreter_fixture(root):
    fixture = json.loads((root / "app/tests/fixtures/interpreter-dialogue-v1.json").read_text())
    manifest = json.loads((root / "local/private/interpreter/manifest.json").read_text())
    if manifest.get("fixture_id") != fixture.get("fixture_id"):
        raise RuntimeError("Interpreter WAV manifest does not match its source design")
    for track in manifest.get("tracks", {}).values():
        path = root / "local/private/interpreter" / track["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != track.get("sha256"):
            raise RuntimeError(f"Interpreter WAV hash mismatch: {path.name}")
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 8000
            ):
                raise RuntimeError(f"Interpreter WAV format mismatch: {path.name}")
    return manifest
