# AI backend measurement contract v1

Status: live PCMU-to-STT-to-LLM-to-TTS contract implemented; scientific quality
comparison remains blocked on the fixed-corpus pilot.

The IMS and media layers do not depend on a model vendor. The current
`POST /observe` path carries bounded PCMU audio to the first replaceable local
backend. An event has:

- opaque `call_ids` used only for within-run correlation;
- `observed_at`, the adapter wall-clock timestamp;
- RTP-window counts, codec metadata, an audio hash, and a base64 in-memory audio
  window, but no subscriber SIP identity;
- `backend_id`, immutable model revisions, audio duration/RMS, character counts,
  STT/LLM processing times, delivery status, and adapter timing. Raw transcript,
  prompt, and generated reply are deliberately absent from the event API.

`processing_ms` uses the worker monotonic clock and is the valid control-service
time. `adapter_to_worker_ms` uses synchronized wall clocks and is diagnostic;
it must not be used across hosts until clock offset/uncertainty is recorded.

The implementation has a bounded queue, body limit, authenticated API and two
explicit persistence modes. Translation/observe audio remains memory-only.
Only `service_mode=transcribe`, selected by the separate IMS number after an
audible disclosure, writes private WAV/transcript files outside the evidence
tree with a per-call byte limit and declared retention deadline. Raw STT text
is transient; a pinned local LLM removes disfluencies and repairs written-form
punctuation before persistence while being instructed to preserve meaning,
facts, names, numbers, and order. Only lengths, latency and success metadata
enter the event API. The next
version must add automated retention enforcement plus sequence-aware
RTP reassembly, an explicit frame-envelope version, end-of-turn events,
deadlines, cancellation, and error taxonomy. It must not add subscriber
identities. Model artifact ID, quantization, decoding parameters, warm/cold
state and device placement belong in run metadata and metric provenance, not
in IMS routing configuration.
