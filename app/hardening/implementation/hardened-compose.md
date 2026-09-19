# Implementation Plan: Hardened Compose Boundary

## Selected Design And Constraints

Option 1 preserves the local Docker topology while removing unnecessary
ambient authority. It is a transition control, not the production scaling
architecture.

## Source Revision And Drift Check

Implementation began from `3f9853e052befc8200815ab1074ce9a472d03433`.
The evidence collection digest is recorded in `../context.md`. The expected
drift is the hardening implementation itself.

## Affected Components

`docker-compose.yml`, `lab.env`, the four custom Python services, startup and
verification scripts, and operator documentation.

## Ordered Work Packages

- Generate a control token in a private Docker volume and mount it only into
  custom control-plane services.
- Authenticate every non-health internal HTTP endpoint with constant-time
  bearer comparison.
- Require SDP media to be anchored on the configured RTPengine address and
  allocated port range before the agent can emit RTP.
- Minimize analytics events to opaque Call-ID and timing; do not forward SIP
  subscriber identities or persist audio.
- Apply read-only filesystems, no-new-privileges, capability dropping,
  non-root users where compatible, PID/CPU/memory limits, bounded logs and
  bounded in-memory event/call retention.
- Pass only the required subscriber secrets to each legacy component.
- Add an executable security/privacy gate and retain all Phase 4 gates.

## Compatibility And Migration

The public SIP and RTP behavior is unchanged. The control APIs intentionally
become incompatible with unauthenticated callers. Existing named databases
and subscriber identities are unchanged.

## Tactical Protections During Migration

Keep host exposure limited to loopback, keep `secrets/ims.env` ignored, and do
not attach unrelated containers to `lab5g`. Production credentials must never
reuse the laboratory K/OPc or SIP Digest values.

## Tests And Security Validation

`verify-security.sh` proves runtime container restrictions, authentication,
media-destination rejection, and absence of subscriber secrets in custom
service environments. Phase 4B–4E tests prove registration, ordinary calls,
fail-open observation, agent RTP, and BYE cleanup.

## Performance And Resource Benchmarks

No load result is claimed. Before production migration, measure calls per
second, concurrent dialogs, RTP packets per second, p95/p99 setup latency,
worker queue time, memory per call, and recovery time under worker and node
failure. Compare against an explicit service-level objective.

## Rollout And Rollback

Compose recreates only affected custom services plus dependencies. Rollback is
the preceding Git commit and removal of the generated control-token volume if
a fresh token is required; database volumes remain untouched.

## Acceptance Criteria

- All Phase 4A–4E and security gates pass.
- Unauthenticated control requests return 401.
- Non-RTPengine destinations return 400/488.
- Custom services cannot write their root filesystem or gain privileges.
- Analytics receives no From/To subscriber identities and stores no audio.

## Open Decisions

Cluster identity, durable state store, queue, KMS, region count, retention,
tenant model, and compliance jurisdiction remain production design inputs.
