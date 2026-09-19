"""Compare identical texts before/after PCMU; run in the voice-agent image.

Use a separate Compose run container with a writable output mount, this script
mounted read-only, VOICE_AGENT_IP=0.0.0.0 and VOICE_AGENT_RTP_PORT=0.
This is a listening fixture, not an automated naturalness score.
"""

import argparse
import json
import subprocess
import time
import wave
from pathlib import Path

from ims_voice import runtime
from ims_voice.audio import synthesize_espeak
from ims_voice.neural_voice import load_voice, synthesize_neural


def compare(output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    phrases = (
        (
            "russian",
            runtime.tts_voice,
            "Здравствуйте! Я хорошо слышу перевод. Давайте продолжим разговор и запишем результат проверки.",
        ),
        (
            "english",
            runtime.tts_translation_voice,
            "Hello! I can hear the translation clearly. Let us continue our conversation and record the test results.",
        ),
    )
    for language, voice, text in phrases:
        load_voice(voice)
        for backend in ("espeak", "piper"):
            native = output / f"{language}-{backend}-native.wav"
            telephone = output / f"{language}-{backend}-telephone.wav"
            started = time.monotonic()
            if backend == "piper":
                synthesize_neural(text, voice, str(native))
            else:
                synthesize_espeak(text, voice, str(native))
            elapsed = time.monotonic() - started

            # Encode and decode the same G.711 mu-law used by the live IMS call.
            encoded = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(native),
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-f",
                    "mulaw",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "mulaw",
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-i",
                    "pipe:0",
                    str(telephone),
                ],
                input=encoded,
                check=True,
                timeout=30,
            )
            with wave.open(str(native)) as audio:
                duration = audio.getnframes() / audio.getframerate()
            results.append(
                dict(
                    language=language,
                    backend=backend,
                    text=text,
                    synthesis_seconds=elapsed,
                    audio_seconds=duration,
                    real_time_factor=elapsed / duration,
                )
            )
    (output / "comparison.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    compare(parser.parse_args().output)
