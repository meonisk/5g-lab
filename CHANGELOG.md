# Changelog

All notable changes to the Local 5G SA + IMS + voice-agent lab.
Loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses [Conventional Commits](https://www.conventionalcommits.org/) prefixes.

No versioned release has been published. Dates below group local development
milestones; they are not release tags or scientific benchmark results.

## [Unreleased]

### Removed

- chore: remove unused vendored MySQL/PyHSS image build recipes and the unused
  local MySQL initializer; deployment continues to use the configured images.
  Retain required runtime templates, upstream licenses, and public commands.

### Added

- feat: capture complete phone-side input and received WAV files, all container
  logs, runtime metadata, hashes, latency, and Git provenance for one private
  two-language IMS interpreter experiment.
- docs: script inventory distinguishing public commands from runtime helpers.
- test: HTTP authentication, input bounds, queue overload, duplicate call startup,
  and playback worker shutdown regression tests.
- docs: service reading guide with pipeline, library roles, and in-memory limits.
- docs: chronological changelog derived from Git history.

### Changed

- perf: replace the 145-second interpreter fixture with a naturally paced
  70-second dialogue and reduce dialogue endpointing silence to 700 ms.
- style: count the 300-line module limit by logical lines, allowing whitespace
  and explanatory comments; separate dense media-processing loops into named stages.
- refactor: replace handwritten HTTP handlers with Flask and Waitress; share
  HTTPX clients, authentication, JSON validation, and server settings.
- refactor: separate speech recognition, transcription, reply delivery, and
  voice call lifecycle; use explicit dataclass fields for queued utterances.
- test: validate structured JSON and HTTP codes independently of formatting.
- refactor: simplify app to services, infrastructure, tests, research, and config;
  move operator scripts and documentation to the root and private state to local.

- refactor: consolidate runtime, deployment, tests, and research under `app/`.
- build: retain a stable Compose project name after directory migration.
- build: initialize private credentials and generate both audio fixtures on first start.
- refactor: remove nine redundant verification wrappers; invoke integration
  tests directly. Research gate command paths follow the new entry points.

### Fixed

- fix: duplicate call notifications no longer start extra playback workers;
  closing a full playback queue no longer leaves its worker waiting forever.

## 2026-09-19 — Local language services

### Added

- feat: local STT → LLM → TTS → RTP conversational loop and Russian multi-turn
  calls (`0e2314b`, `e5ab9c9`).
- feat: Russian-to-English translation and opt-in transcription with local LLM
  normalization (`883fdfa`, `5b957ed`).
- feat: synthetic two-subscriber Russian/English dialogue gate (`f613776`).
- feat: bidirectional interpretation through separate language legs, bounded
  inference queues, per-call TTS queues, and stage latency metadata (`dc4548b`).
- test: concurrent call regression and 1 → 2 → 1 recovery probe (`4caee18`).

### Changed

- refactor: split deployment, services, tests, and research tooling for team
  development; enforce the 300-line owned-source limit (`1b9222f`).

### Fixed

- fix: select the normalized transcription event in acceptance checks (`b9dab39`).
- fix: isolate concurrent media by call and subscriber-facing relay port (`ae9820b`).
- fix: queue TTS replies instead of replacing ongoing playback; reset test WAV
  clients between runs; retain source STT when normalization over-shortens text
  (`dc4548b`).

## 2026-09-18 — IMS and research foundation

### Added

- build: local Open5GS/UERANSIM/IMS lab and observed media path (`3eeb2e3`).
- feat: callable IMS voice agent (`3f9853e`).
- research: experiment designs, manifests, schemas, admission gates, and tooling
  provenance (`8401dff`, `1587ec9`, `204e715`).
- feat: process live IMS PCMU audio with local STT (`de8e1c8`).

### Security

- security: isolate AI services, control access, resources, and data boundaries
  (`7615a99`).
- privacy: reject raw correlation identifiers from evidence and keep transcript
  text out of research artifacts (`55c3469`, `1bdb1bf`).
