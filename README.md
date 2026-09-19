# Local 5G SA + IMS voice lab

Local Open5GS/UERANSIM stand with IMS calling, Russian/English speech
translation, recording, and transcription using local STT, LLM, and TTS.

## Repository

```text
app/
  services/        SIP AS, Media Adapter, AI Worker, Voice Agent
  configs/         Open5GS, DNS and UERANSIM templates
  deploy/compose/  Core, access, IMS and AI deployment
  images/          Infrastructure image builds
  vendor/          Third-party IMS sources and license
  scripts/         Runtime and provisioning helpers
  tests/           Unit and live integration tests
  tools/quality/   Offline source checks
  fixtures/        Synthetic conversation scenarios
  research/        Designs, schemas and measurement tooling
  docs/            Configuration, layout and physical-stand guide
  hardening/       Deployment protection and scaling design
  lab.env          Public operator configuration
  secrets/         Credential template; local values ignored
  private/         Local audio and transcripts, ignored
  evidence/        Local experiment runs, ignored
scripts/           Operator commands: start, compose, check
CHANGELOG.md       Implementation history
CONTRIBUTING.md    Development workflow
```

## Run

Requires Docker Desktop with Linux containers/WSL2, Git for Windows, Python
3.12+, and Windows Pavel/Zira voices for synthetic dialogue fixtures.

```powershell
python -m pip install -r app/requirements-dev.txt
.\scripts\check.ps1
.\scripts\start.ps1
.\scripts\compose.ps1 ps
```

First start generates valid random laboratory credentials if `app/secrets/ims.env`
is absent and preserves existing credentials. It generates both dialogue fixtures,
builds images, loads models, provisions subscribers, and runs acceptance gates.
Internet is required for the initial image/model downloads. No sibling repository
or pre-existing audio/model cache is required.

Review `app/lab.env` before starting. Run integration
tests serially from `app/`; commands and service details are in
[app/README.md](app/README.md). Use `scripts/compose.ps1 down` to stop the lab.

See [project layout](app/docs/project-layout.md),
[research workflow](app/research/README.md), and [changelog](CHANGELOG.md).
The two-language interpreter currently supports one pair of participants;
local functional tests do not establish production capacity or physical-radio
performance. Recordings and generated WAVs are excluded from Git.
