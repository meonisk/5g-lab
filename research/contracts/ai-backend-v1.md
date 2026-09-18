# AI backend measurement contract v1

Status: live PCMU-to-STT contract implemented; scientific quality comparison
remains blocked on the fixed-corpus pilot.

The IMS and media layers do not depend on a model vendor. The current
`POST /observe` path carries bounded PCMU audio to the first replaceable local
backend. An event has:

- opaque `call_ids` used only for within-run correlation;
- `observed_at`, the adapter wall-clock timestamp;
- RTP-window counts, codec metadata, an audio hash, and a base64 in-memory audio
  window, but no subscriber SIP identity;
- `backend_id`, immutable `model_revision`, transcript, audio duration/RMS,
  `received_at`, `processed_at`, `processing_ms`, and `adapter_to_worker_ms`.

`processing_ms` uses the worker monotonic clock and is the valid control-service
time. `adapter_to_worker_ms` uses synchronized wall clocks and is diagnostic;
it must not be used across hosts until clock offset/uncertainty is recorded.

The implementation has a bounded queue, body limit, authenticated API, bounded
retention, and no audio persistence. The next version must add sequence-aware
RTP reassembly, an explicit frame-envelope version, end-of-turn events,
deadlines, cancellation, and error taxonomy. It must not add subscriber
identities. Model artifact ID, quantization, decoding parameters, warm/cold
state and device placement belong in run metadata and metric provenance, not
in IMS routing configuration.
