# Implementation and validation status

Publication preparation review: 2026-09-21. This describes the source snapshot,
not a newly certified runtime or a scientific result.

| Area | Current state | Evidence boundary |
| --- | --- | --- |
| Source checks | Offline suite checks formatting, syntax, layout, Git hygiene, documentation and 28 unit tests | No Docker calls or audio playback |
| Local 5G/IMS | Startup and serial registration/call/media gates are implemented | Docker Engine was unavailable during publication preparation; live gates were not rerun |
| Speech stack | Whisper small, Qwen3 4B Q4_K_M and Piper RU/EN, CPU default | Models/images download on the receiving host; cold start and resources vary |
| Interpreter | One pair of separately terminated Russian/English legs; phrase-based default | Functional gate is additional to startup; no production capacity claim |
| Streaming | Disabled by default; historical trials failed coverage and/or latency | No accepted run satisfying both conditions |
| User latency target | 1–3 seconds from speech start to far-end audible output remains open | Current timestamps end at server RTP send, not receiver playback |
| Recording | Separate service number, audible disclosure, private output | Retention deadline is declared; deletion remains an operator action |
| Research | Admission tooling and candidate designs exist | AI-scale design is not frozen; no main scientific result |
| Physical 5G | Integration contract exists | RF, native UE/ISIM, handover and real speaker timing remain unverified |
| Production | Single-host lab only | Durable call state, multi-tenant isolation and capacity acceptance remain design work |

## Publication checks performed

On 2026-09-21 a clean Git clone passed the full offline suite on Windows with
Python 3.14, including 28 unit tests and 64 local link targets in 23 documents.
Fresh local credential generation and `docker compose ... config --quiet` also
passed. Configuration parsing does not start containers or prove a working call.
The original repository's reachable history was checked against its local
credentials after sanitization. Guard probes rejected an audio file in the index,
a broken document link and a credential literal without printing its value.

## Interpreting test output

`python scripts/quality/check.py` is the offline development check.
`python scripts/quality/check_git.py --history` also scans all reachable Git refs
for prohibited paths, oversized blobs, selected credential signatures and known
local credentials. It is a publication guard, not an exhaustive security audit.

The startup launcher runs nine shell gates. Run the additional interpreter and
parallel-call gates from [running.md](running.md) serially on a working stand.
`READY` after `--skip-verify` means startup and warmup completed, not acceptance.
Historical PASS/FAIL results remain attached to their original configuration.
Changing source, models, fixture, hardware or timing requires a separate run.

Private WAVs and logs are deliberately not shipped. The historical streaming
figures in [streaming.md](streaming.md) document failed experiments; the source
repository alone cannot independently verify those recordings.

## Remaining acceptance work

1. Run startup and all applicable additional live gates from a clean clone.
2. Fix ASR revisions and missing tails before enabling streaming by default.
3. Measure speech-start-to-receiver-audible latency on a common clock and check
   source coverage and translation meaning together.
4. Freeze the corpus, experimental design and analysis before research claims.
