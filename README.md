# Local 5G SA + IMS voice lab

A local Open5GS/UERANSIM stand with IMS calls, Russian/English speech
translation, and opt-in recording/transcription. Speech processing runs locally:
faster-whisper small → Unsloth Qwen3 4B Q4_K_M through Ollama → Piper RU/EN.
The telephone media contract is PCMU/8000.

**Status: laboratory implementation, not a production release.** The default
profile is CPU and phrase-based translation. Streaming is experimental and off;
the 1–3 second speech-start-to-far-end-audio target is not met. Offline checks
and live acceptance are separate; see [validation status](docs/status.md).

## Requirements

- Git and Python 3.12+; install the pinned development dependencies below.
- Docker with Linux containers and Compose v2 supporting `include`.
- Windows: Docker Desktop/WSL2 and Git for Windows. Linux: Bash and an
  SCTP-capable kernel. macOS is not supported by the current launcher.
- Internet for the first image/model downloads; model caches persist in Docker
  volumes. GGUF alone is about 2.5 GB; total disk/RAM demand is higher.
- CPU is the portable default. NVIDIA acceleration is optional and requires
  host configuration; see [models and GPU](docs/local-models.md).

## Start from a clone

Clone this repository and change to its root. No sibling repositories, private
WAV files, pre-existing model cache or operating-system TTS voices are required.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
.\scripts\check.ps1
.\scripts\start.ps1
.\scripts\compose.ps1 ps
```

Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/quality/check.py
./scripts/start.sh
./scripts/compose.sh ps
```

Start Docker before running the launcher. First start generates random lab
credentials in ignored `local/secrets/ims.env`, preserves existing credentials,
generates both synthetic dialogue fixtures, builds images, loads models,
provisions subscribers and runs nine shell acceptance gates. Two additional
Python call checks are documented in the [running guide](docs/running.md).
Startup changes the local stand and places test calls; run gates serially.

Review public settings in `app/config/lab.env`. Use the Compose wrappers so both
env files are loaded. Stop with `scripts/compose.ps1 down` on Windows or
`./scripts/compose.sh down` on Linux; named volumes are retained.

## Services and boundaries

The stand includes Open5GS, one simulated gNB, two UEs, PyHSS, Kamailio
P/I/S-CSCF, RTPengine and four custom services: SIP AS, Media Adapter, AI Worker
and Voice Agent. It supports ordinary IMS calls, a translation service,
a disclosed recording/transcription service and one two-participant interpreter
room. Service numbers and identities are configured in `app/config/lab.env`.

Calls and inference queues are process-local. A passing local call test does
not establish capacity, translation accuracy, physical-radio performance or
production readiness. Recordings, transcripts, secrets and run evidence remain
under ignored `local/` and are not part of the source distribution.

## Documentation

| Topic | Guide |
| --- | --- |
| Run, verify, stop and troubleshoot | [Running](docs/running.md) |
| Current capabilities and unverified work | [Status](docs/status.md) |
| Settings, voices and fixtures | [Configuration](docs/configuration.md) |
| Model pins, CPU/GPU and latency | [Local models](docs/local-models.md) |
| Experimental streaming and failed trials | [Streaming](docs/streaming.md) |
| Repository structure and code | [Layout](docs/project-layout.md), [services](app/services/README.md) |
| Development and command inventory | [Contributing](CONTRIBUTING.md), [scripts](scripts/README.md) |
| Research stages and evidence | [Research](app/research/README.md) |
| Physical RAN/UE migration | [Physical stand](docs/physical-5g-stand.md) |
| Historical protection design | [Hardening review](docs/hardening/hardening.md) |
| Git publication and distribution scope | [Publication](docs/publication.md) |
| Third-party material and license scope | [Third-party notices](THIRD_PARTY.md) |
| Implementation history | [Changelog](CHANGELOG.md) |
