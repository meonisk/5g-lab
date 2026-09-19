# Local 5G SA + IMS voice lab

Local Open5GS/UERANSIM stand with IMS calling, Russian/English speech
translation, recording, and transcription using local STT, LLM, and TTS.

## Repository

```text
app/
  services/        SIP AS, Media Adapter, AI Worker, Voice Agent
  infrastructure/  Docker, 5G/IMS templates, images, third-party sources
  tests/           Unit tests, live gates and conversation fixtures
  research/        Designs, schemas and measurement tooling
  config/          Public lab.env and credential template
scripts/           Start, compose, checks and runtime helpers
docs/              Operation, architecture and protection design
local/             Private credentials, audio and results; ignored by Git
docker-compose.yml Single deployment entry point
CHANGELOG.md       Implementation history
CONTRIBUTING.md    Development workflow
```

## Run

Requires Docker Desktop with Linux containers/WSL2, Git for Windows, Python
3.12+, and Windows Pavel/Zira voices for synthetic dialogue fixtures.

```powershell
python -m pip install -r requirements-dev.txt
.\scripts\check.ps1
.\scripts\start.ps1
.\scripts\compose.ps1 ps
```

First start generates valid random laboratory credentials if `local/secrets/ims.env`
is absent and preserves existing credentials. It generates both dialogue fixtures,
builds images, loads models, provisions subscribers, and runs acceptance gates.
Internet is required for the initial image/model downloads. No sibling repository
or pre-existing audio/model cache is required.

Review `app/config/lab.env` before starting. Run integration
tests serially from the repository root; commands and service details are in
[running guide](docs/running.md). Use `scripts/compose.ps1 down` to stop the lab.

See [project layout](docs/project-layout.md),
[service code guide](app/services/README.md),
[research workflow](app/research/README.md), and [changelog](CHANGELOG.md).
The two-language interpreter currently supports one pair of participants;
local functional tests do not establish production capacity or physical-radio
performance. Recordings and generated WAVs are excluded from Git.
