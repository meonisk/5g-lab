# AI backend measurement contract v1

Status: minimal implemented control contract; semantic audio contract remains
blocked on the fixed-corpus pilot.

The IMS and media layers must not depend on a model vendor. The current
`POST /observe` path establishes the first replaceable boundary. An event has:

- opaque `call_ids` used only for within-run correlation;
- `observed_at`, the adapter wall-clock timestamp;
- RTP-window counts and codec metadata, but no subscriber SIP identity;
- `backend_id`, `received_at`, `processed_at`, `processing_ms`, and
  `adapter_to_worker_ms` added by the worker.

`processing_ms` uses the worker monotonic clock and is the valid control-service
time. `adapter_to_worker_ms` uses synchronized wall clocks and is diagnostic;
it must not be used across hosts until clock offset/uncertainty is recorded.

The next semantic version must add a versioned audio-frame envelope, explicit
codec/rate/channels, end-of-turn events, backpressure, deadlines, cancellation,
and error taxonomy. It must not add subscriber identities. Model artifact ID,
quantization, decoding parameters, warm/cold state and device placement belong
in run metadata and metric provenance, not in IMS routing configuration.
