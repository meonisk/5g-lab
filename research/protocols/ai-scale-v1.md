# AI scale over IMS: research map v1

Status: **research design candidate**, not experimental evidence.

## 1. What “scale” means

“Large AI” is not one independent variable. The study separates four axes:

| Axis | Controlled levels | What it answers |
|---|---|---|
| Model tier | deterministic control, small, medium, large | quality/latency/resource trade-off |
| Placement | local CPU, local GPU, service/edge VM, remote backend | effect of compute and transport placement |
| Load | offered concurrent sessions and arrival rate | capacity, queues, deadlines, failure onset |
| Network condition | baseline, delay, jitter, loss | robustness of media and the AI service path |

Do not change all four in the first campaign. First screen each axis while the
others are fixed; use the pilot to choose a small factorial design only where
interactions matter.

The current `ai-worker` processes live PCMU with a revision-pinned local
faster-whisper `tiny.en` model on CPU. It is now a small semantic STT backend.
The `voice-agent` reply remains deterministic VAD plus synthesized prompts; the
transcript does not yet control an LLM or response.

## 2. Questions that the platform can support

### RQ1: quality/cost frontier

At fixed audio, prompts, decoding and hardware, how do model tiers change task
success, WER/CER, response latency, real-time factor, CPU/GPU time, peak memory,
and energy per completed request?

### RQ2: placement

How much latency and failure probability is introduced when the same immutable
model moves from local GPU to a service VM or remote backend? Model and
placement must not change in the same comparison.

### RQ3: service capacity

At a declared arrival process, where do queueing, deadline misses, RTP loss, or
call failures begin? Report offered load and completed load separately; a
surviving container is not evidence that calls succeeded.

### RQ4: network robustness

How do controlled delay, jitter, and packet loss affect transcription quality,
turn latency, call survival, and recovery? Impairment must be measured at the
actual media/service boundary, not only configured in a script.

### RQ5: failure containment and privacy

Does an OBSERVE service fail open without interrupting the call? Does a
TERMINATE service fail in a bounded and visible way? What identifiers, audio,
transcripts, prompts, and model-provider metadata cross each trust boundary?

## 3. Where each experiment is valid

| Environment | Valid work | Invalid inference |
|---|---|---|
| This PC, offline | fixed-corpus STT/LLM/TTS microbenchmarks; CPU/GPU comparison; deterministic replay; privacy/redaction tests | RF, mobility, real UE acoustics, carrier QoS |
| This PC, Docker IMS | 1–2 UE end-to-end procedures; service latency; fail-open; RTP path; controlled software impairment; instrumentation admission | population-scale concurrency; independent-host clock behavior; radio conclusions |
| Multi-VM lab | placement, clock synchronization, VM-SERVICE separation, controlled load, edge-vs-core transport | RF/handover unless a real RAN is present |
| Physical 5G stand | SDR/gNB/UE radio effects, mobility/handover, real microphones/speakers, QoS/QFI behavior, edge placement | Internet-scale or production multi-tenant capacity without representative infrastructure |

The present PC has a 6-core/12-thread CPU, 32 GB RAM, and an RTX 4060 Ti with
8 GB VRAM. It is suitable for small/medium local inference and bounded
end-to-end trials. Models that do not fit in 8 GB must be quantized/offloaded
with that fact treated as a different execution condition, or run on a
separate host. Hardware is captured again for every run; this paragraph is not
the source of truth.

## 4. Measurement contract

### Primary quality outcomes

- STT: WER and CER against a licensed, versioned reference transcript.
- Intent/agent: exact task success against an explicit rubric; no subjective
  “good answer” primary endpoint.
- Translation: a predeclared automatic metric plus blinded human review for a
  fixed subset.
- Speech output: intelligibility/task completion; MOS only with an appropriate
  protocol and enough independent raters.

### Timing and capacity outcomes

- speech-end to final transcript;
- speech-end to first response audio and to response completion;
- real-time factor for each stage;
- call setup, call survival, completed requests, deadline misses;
- queue wait and service time separately;
- CPU/GPU time, peak RAM/VRAM, and measured energy where the measurement method
  is calibrated and recorded.

All metrics must name their observed endpoints, source artifact, clock,
derivation method, and confidence. Missing timing remains unavailable; it is
not reconstructed from log-line order. Diagrams and metrics should eventually
use the same normalized event model from
[`ims/tools/sigdiag`](../../../ims/tools/sigdiag/).

## 5. Experimental sequence and blockers

### A. Admission (implemented now)

- all existing IMS/voice/security gates pass;
- run manifest records design hash, Git state, hardware and image IDs;
- bounded Docker state/stats/log collection works;
- identifiers are consistently pseudonymized and secrets are absent;
- the deterministic scenario can be repeated without changing configuration.

### B. Pilot (next implementation milestone)

- add at least one more materially different replaceable inference backend;
- bind immutable model IDs and a fixed audio corpus;
- add a traffic/media replayer independent of live microphone input;
- add measured network impairment and stage timestamps;
- estimate variance, warm-up, repetitions, storage, and safe load ceiling.

### C. Freeze

Freeze model artifacts, corpus hashes, prompt/decoding parameters, hardware,
load process, impairment profiles, random seeds, repetition count, exclusion
rules, primary outcomes, and analysis code. Changes after this point create a
new design version.

### D. Main and closed analysis

Use a persistent job ledger and resume the same case after interruption.
Validate cardinality, hashes, failures and exclusions before analysis. Separate
pre-run factors, observed outcomes, diagnostics, and provenance. Admission,
pilot and failed-debug runs never enter the main sample.

Current blockers for a scientific AI-scale result are therefore explicit:
semantic backends, fixed licensed fixtures, a load/replay generator, calibrated
energy/network measurement, pilot-derived repetitions, and frozen analysis.

## 6. Data protection contract

Data classes:

1. **Public synthetic**: generated audio, artificial identities, configs and
   derived metrics; preferred for reproducible publication.
2. **Pseudonymized research**: consented audio/transcripts with direct
   identifiers removed; restricted access and a documented retention date.
3. **Directly identifying/sensitive**: voice recordings, phone identities,
   prompts or transcripts containing personal data; never collected by the
   default harness and never sent to a remote model without a separate legal
   basis, processor agreement and explicit design.

Default rules:

- collect the minimum needed for the declared question;
- raw audio and payload capture are off by default;
- pseudonyms are consistent only within a run; the key is stored separately;
- share sanitized artifacts only; never share the private key or secret env;
- encrypt restricted storage and backups with managed, rotated keys on a real
  stand; log and review access;
- declare deletion and backup-retention periods before collection;
- record model/provider region, retention, training opt-out and sub-processors
  for every remote backend;
- test deletion, restoration, incident response and tenant separation rather
  than treating configuration as proof.

## 7. What to demonstrate

### Demo A — available now

Show two registered IMS users, a subscriber call through P/I/S-CSCF and
RTPengine, the OBSERVE path, a call to the deterministic voice-agent service,
and call continuity while `ai-worker` is stopped. Label it “IMS service and
measurement baseline”, not “LLM agent”.

### Demo B — after the pilot backend milestone

Replay the same utterance through small and medium local backends, show the
same task result plus stage latency/resource evidence, and switch backends
without changing IMS. This demonstrates replaceability, not statistical
superiority.

### Demo C — physical stand

Place a real UE call, show synchronized RAN/core/service events, then move the
AI backend between core and service/edge host. A predeclared impairment or AI
failure should produce a visible, expected degradation/fallback. Keep a
recorded deterministic replay as the fallback if live radio is unstable.
