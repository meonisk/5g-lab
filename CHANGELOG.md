# История изменений

Изменения стенда 5G, IMS и голосовых сервисов. Формат основан на
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); типы изменений
соответствуют [Conventional Commits](https://www.conventionalcommits.org/).

Нумерованные выпуски ещё не опубликованы. Даты ниже группируют этапы разработки
и не обозначают выпуски или результаты научных измерений.

## [Unreleased]

- docs: добавлен маршрут для первого знакомства со стендом: установка инструментов,
  подготовка CPU-моделей, первый вызов, работа с транскрипцией и остановка;
  убраны организационные роли из технической документации.

- docs: добавлены полный справочник 246 параметров lab.env, инструкции запуска
  CPU-профилей и контракт внешней интеграции IMS + AI; актуализированы master,
  границы поставки, диагностика и критерии совместной приёмки.

- feat: добавлены переключаемые CPU-профили с локальным OPUS-MT int8 вместо
  Qwen, raw-транскрипцией и Whisper small/base/tiny; исходный режим сохранён.
- perf: добавлено отключение ONNX memory arena для Piper в CPU-профилях;
  измерения STT, перевода и озвучки оформлены отдельно от телефонного SLA.

- docs: сокращён и переведён README, добавлены первый запуск, навигация и словарь
  обозначений; актуальный статус отделён от истории проверок, переведены
  инструкции по телефону, исследованиям, публикации и сторонним компонентам.
- refactor: переведены пояснения и ошибки основных команд запуска, настройки
  OAI и проверки телефона; добавлен UTF-8 вывод и сохранены служебные маркеры.

- docs: add an app navigation map and infrastructure/config/test guides;
  name the active core Compose file `core-oai.yml` and distinguish the Open5GS rollback.

- fix: reject AI service offers without usable PCMU before allocating media;
  do not silently accept AMR-only offers or required unsupported preconditions.
- docs: activate native-phone integration with measured codec blockers, device/SIM
  requirements and a read-only phone readiness command.
- feat: include AMR/AMR-WB encoders in RTPengine and offer PCMU interworking for
  configured AI destinations, retaining the internal PCMU/8000 media contract.

- feat: replace the local Open5GS core with pinned OAI CN5G v2.2.1, dedicated UDR
  SQL storage, SQN-preserving provisioning and internet/IMS DNN routing.
- feat: add an independent IMS + AI partner deployment and integration contract
  for an existing external OAI; local core and emulators are excluded.
- test: adapt network gates to OAI and cover subscriber and deployment boundaries.

- fix: recover nr-cli discovery after reused UE PIDs by quarantining only stale
  registry records verified against the current process and its UDP socket.
- test: add real IMS PDU release/address-change recovery with TUN/source-route,
  SIP restart and unaffected-peer checks; validate exact IMS Contact inventories.

- fix: reject an exhausted S-CSCF contact scan instead of routing to the last
  expired Contact; package the minimal registrar patch in a pinned derived image.

- feat: add deregistered/expired AKA callee scenarios and strict rejected-call
  checks, with per-UE challenge binding and restoration of the no-AS profile.

- fix: bind SIPp authentication URI to the IMS REGISTER domain and reject
  mismatched Digest realm, URI or algorithm in AKA registration evidence.

- feat: add AKA registration refresh/deregistration scenarios, strict lifecycle
  trace checks, read-only registrar snapshots and multi-challenge Cx binding.

- feat: add one-process AKA registration/call scenarios and a serial two-UE gate
  with Cx binding, SIP dialog checks, negotiated RTP routes, receiver PCMU audio
  and restoration of the normal subscriber profile.
- test: add UDP receiver filtering, distinct-SSRC exchange and SIP dialog tests.

- feat: add explicit SIPp OPc support while preserving OP, with Milenage test-set
  vectors and rejection of ambiguous OP/OPc inputs; no subscriber key adaptation.
- feat: add an isolated two-UE AKA registration probe, bad-response scenario,
  transaction-bound SIP trace checks and bounded private Cx packet capture.

- feat: add a pinned source-built SIPp AKA client image, binary-parameter selftest
  and vendor provenance; continuous AKA registration/call acceptance remains open.
- fix: validate redacted PyHSS API credentials against read-only local SQL rows;
  reject shared AuC ownership and changed SQN during explicit key migration.
  Repeated provisioning also supports an existing UE with its peer not yet created.

- feat: add a serial plain Digest call gate with temporary no-AS iFC, fresh Cx
  readiness, opposite-source receiver audio, call-specific relay and cleanup checks.
- fix: keep PJSUA conference clocks at PCMU's 8000 Hz and flush live SIP diagnostics;
  reject CRLF in owned shell scripts before deployment.
- feat: generate separate UE/domain credentials and add an explicit backed-up,
  SQN-preserving legacy-key migration with rollback; live rotation is pending.
- fix: reduce shareable protocol-heavy logs to metadata-only removal markers.

- fix: restart SIP clients on IMS TUN/address/owned-route changes; preserve FIFO
  control and stop their media process before re-registration.
- feat: persist MySQL in a named volume with a cold-copy migration, local rollback
  image and guarded recreation; wait for HSS Cx before restarting IMS.

- fix: verify current IMS TUN/source routes and propagate NAT inspection errors;
  bind registration diagnostics to the new client start and registration epoch.
- feat: add base-only startup without AI warmup and preserve existing subscriber
  records and PyHSS authentication state during repeated provisioning.
- feat: define a separate virtual base connectivity admission design.

- fix: fail connectivity checks on missing TUN/log events and failed commands;
  reject missing, substituted, duplicate or malformed research gate results.
- feat: serialize evidence collectors with an OS lock, persist per-gate journal
  and atomic snapshots, preserve failed attempts and reject recollection;
  record pre/post container identities and bounded logs including stderr.
  Protocol cleanup, crash reconciliation and standards acceptance remain pending.

- docs: detail virtual core, IMS authentication/dialogs, media/policy and
  evidence-runner contracts; consolidate dependencies into twelve delivery
  packages with separate base, AKA and protected-policy acceptance milestones.

- docs: define a virtual 5GS/IMS candidate profile, 40 traceable requirements
  and 12 acceptance scenarios; separate emulator limits, engineering gates,
  standards applicability and deferred physical-device work.
- docs: record recovery/acceptance gaps and clarify that physical migration
  requires discovery, access-security, policy and codec verification.

- docs: use the canonical 5g-lab repository name and GitLab URL in setup,
  publication and source archive instructions; document the stable internal
  Compose identifier separately.

- chore: prepare Git publication, preserve a private history backup, remove
  credential literals from reachable history, and set shell executable modes.
- build: add Git hygiene and local Markdown link checks to offline validation.
- docs: align README, operations, model provenance, research and configuration
  with the Qwen3/Piper CPU baseline; document separate live gates and open limits.


- feat: experimental cumulative-audio streaming with two-hypothesis prefix
  agreement, bounded pending snapshots, explicit revision/coverage failures,
  and a speech-start-to-audible-RTP acceptance metric (not handset playback).

- perf: 100 ms audio windows and 600 ms dialogue endpoint silence; enforce a
  configurable 5-second speech-end-to-audible-RTP gate with exactly four turns.

- feat: offline four-track experiment transcription with word timestamps, audio
  statistics, paired dialogue and service timeline; explicitly distinguish
  reconstructed ASR from unavailable historical STT/LLM text.

- feat: pinned Unsloth Qwen3 4B Q4_K_M GGUF import, optional NVIDIA runtime,
  resident LLM and STT/LLM warmup before readiness; Gemma configuration guide.
- fix: publish audio every 250 ms and finalize DTX speech without waiting for
  another sentence; record speech-end-to-first-translated-RTP latency.

### Removed

- chore: remove unused vendored MySQL/PyHSS image build recipes and the unused
  local MySQL initializer; deployment continues to use the configured images.
  Retain required runtime templates, upstream licenses, and public commands.

### Added

- feat: local bilingual Piper speech with pinned Denis and LJ Speech models, build-time
  checksums, resident CPU inference, and unchanged PCMU/8000 media transport.
- fix: generate private dialogue fixtures with pinned containerized Piper
  models and use one Python startup path on Windows and Linux.
- fix: select Git Bash explicitly on Windows instead of the optional WSL launcher.
- test: query the Debian-based Voice Agent with its Python runtime instead of
  assuming the Alpine-only `wget` utility is installed.
- fix: keep natural Piper pauses inside a research utterance while preserving
  the lower-latency 700 ms threshold for ordinary calls.
- fix: connect synthetic WAV players to their own call explicitly, preventing
  remote speech from being mixed back as a fifth echo turn.
- fix: preserve the invoking Linux user's ownership on generated private WAV files.
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
