# Research environment

This directory turns the runnable IMS lab into an experiment-preparation and
evidence-capture environment. It does **not** turn a successful lab check into
a scientific result.

The current executable design, `local-russian-conversation-smoke-v1.json`, is
an instrumentation admission test. The earlier admission designs remain
immutable for their existing evidence. The current design executes and records
the 5GS, IMS call, two-turn Russian STT/LLM/TTS loop, voice-agent,
security/privacy, and topology gates; it also records revisions,
immutable input hashes, hardware, container images, bounded resource snapshots,
and pseudonymized logs. Its result can prove that the measurement path works;
it cannot support a conclusion about AI quality or scalability.

## Stages

1. `ADMISSION`: platform gates, clock check, evidence capture, privacy check.
2. `PILOT`: estimate variance, runtime, storage, failures, and feasible load.
3. `FREEZE`: lock models, fixtures, factors, metrics, exclusions, repetitions,
   seeds, and analysis before the main run.
4. `MAIN`: execute the frozen design without tuning on outcomes.
5. `CLOSED_ANALYSIS`: validate the ledger and exclusions, then analyse.

Only stages 4 and 5 may produce primary study evidence. Admission and pilot
artifacts must retain their stage labels.

## Commands

From PowerShell:

```powershell
./scripts/research.ps1 prepare
./scripts/research.ps1 collect -RunId <run-id>
./scripts/research.ps1 validate -RunId <run-id>
./scripts/research.ps1 verify
```

Generated runs live under ignored `evidence/runs/<run-id>/`. Share only the
`shareable/` directory and the manifest/checksums after review. The per-run
pseudonymization key stays under ignored `evidence/private/`; it is never
written into a shareable artifact.

The proposed AI-scale campaign, local/real-stand boundary, demonstration
scenarios, and data-protection rules are in
[`protocols/ai-scale-v1.md`](protocols/ai-scale-v1.md). The machine-readable
candidate design is deliberately marked `DRAFT`: named model artifacts and a
pilot-derived repetition count must be frozen before a main campaign.
