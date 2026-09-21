# Security Hardening Proposal: Scalable Private IMS Service Boundary

> Historical design record from 2026-09-18. Evidence IDs, hashes and source
> revisions describe that assessment, not a fresh audit of the publication.
> Paths may have been mapped to the current layout. Credential sanitization
> can change Git commit IDs; retain original IDs as historical provenance.
> Current scope and validation limits: [status.md](../../status.md).

## Decision

We need to decide where call state, permission to emit media, subscriber
identity, and AI processing live as the lab grows beyond one host. The decision
is not simply Docker versus Kubernetes: it is whether a compromised worker can
turn a metadata API into control of a call or disclosure of a subscriber.

## Executive Recommendation

The complete option set is: **Option 1, Hardened Compose**, which preserves the
working lab and adds enforceable local controls; **Option 2, Orchestrated
shared service**, which makes call state durable and scales SIP, RTP and AI by
their different load dimensions; and **Option 3, Tenant-isolated cells**,
which duplicates the service and key boundary per tenant.

I recommend Option 1 immediately and Option 2 as the production target. Option
1 is implemented in this repository. Option 2 should not be coded until call
volume, regions, retention, identity provider and availability targets are
known, because those inputs change both the state-store and media-sharding
design. Option 3 is justified when legal or contractual isolation dominates
cost and utilization.

## Evidence

I inspected the runtime definitions and the four custom service implementations.
The following evidence most influenced the diagnosis:

| Evidence | Finding or document | What it establishes |
| --- | --- | --- |
| `E1` | Compose deployment boundary | Custom services shared one broad network; secrets and container privileges were not minimized; per-call services used fixed instances. |
| `E2` | SIP AS source | SDP selected the Voice Agent RTP destination and internal HTTP calls had no service authentication. |
| `E3` | Voice Agent source | Control requests could create/delete calls and choose a media peer; state and event history were process-local. |
| `E4` | Media Adapter source | Packet observation legitimately needs `NET_RAW`, making containment more important; SIP identity fields were accepted despite not being used. |
| `E5` | AI Worker source | Ingestion and event retrieval were unauthenticated and retained process-local event objects. |
| `E6` | Environment contract | Configuration was centralized, but there was no concurrency, resource, retention or production trust-domain contract. |

These are source observations, not evidence of an external breach. We infer
that a compromised container on the shared bridge could reach control APIs,
that an unanchored SDP destination could be abused as media SSRF/amplification,
and that horizontal replicas would disagree about dialog and call state.

## Current Design And Failure Mode

The current lab correctly separates SIP AS, RTP observation and AI behavior as
processes, but separation without authenticated authority is weak isolation.
SIP AS owns in-memory transaction maps; Voice Agent owns in-memory calls;
Media Adapter associates all observed SSRC windows with its active Call-ID
set. Adding replicas would therefore split related state unless every dialog
is pinned to one replica. At the same time, an internal caller could previously
create a Voice Agent session pointing at an arbitrary address.

Personal-data exposure is smaller than a recorder because the agent does not
persist audio, but IMSIs are direct identifiers and call metadata is still
personal data. Sending From/To values to an analytics service that does not use
them only increases breach impact. We should preserve a narrow mapping:
subscriber identity remains in IMS/HSS; service analytics sees an opaque call
reference; raw audio stays in the live RTP path unless a separately consented
feature explicitly records it.

## Desired Invariants

- Only the authenticated SIP service may create or delete an agent call.
- Voice Agent sends RTP only to the configured RTPengine address and allocated
  port range; SDP alone never grants arbitrary network authority.
- Ki/OPc/Digest values are visible only to components that need each value.
- Audio is transient by default; logs and analytics contain no SIP From/To,
  transcript or synthesized prompt content unless a documented policy enables it.
- Every retained metadata class has an owner, purpose, TTL and deletion path.
- A worker failure cannot interrupt RTP relay; overload is bounded and fails
  closed for new work rather than consuming unbounded memory.
- Horizontal routing keeps all messages for a SIP dialog and agent call on a
  consistent state owner, or retrieves state from a durable control service.
- Tenant and region boundaries are explicit; media and keys do not cross them
  accidentally.

## Constraints And Non-Goals

We retain Docker Compose as the executable local environment and avoid changing
the verified IMS subscriber-to-subscriber path. This proposal does not select
a cloud, Kubernetes distribution, database, queue, STT/LLM provider, lawful
intercept design or regulatory jurisdiction. TLS/SRTP and production identity
remain required cluster work; a shared lab bearer token is not their substitute.

## Before Architecture

[Before diagram](../diagrams/scalable-private-service-boundary-before.mmd)
shows one broad trust boundary. The security-relevant fact is that network
reachability and authority were nearly equivalent: a container that could
reach HTTP could request control, and a media address supplied through SDP
could become an RTP destination.

## Options

### Option 1: Hardened Compose

This option keeps the existing fast path and topology. We generate a
high-entropy control token into a private Docker volume, mount it only into the
four custom services, authenticate every non-health API, and validate that an
agent media peer is the configured RTPengine and its port is inside the
allocated range. We also bound calls/events/logs/resources, minimize analytics
payloads, and remove ambient Linux capabilities.

The attractive part is reversibility: the call protocol remains unchanged and
the controls are directly testable. The residual risk is one host and one
shared token. A compromised authorized custom service can impersonate another,
Docker root controls every volume, and in-memory state still prevents arbitrary
replica placement. This option improves the lab and supplies a safe migration
base; it is not production multi-tenancy.

[Option 1 diagram](../diagrams/scalable-private-service-boundary-hardened-compose-after.mmd)

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Control API | Network reachability | Bearer-authenticated requests | Unrelated containers lose call-control authority | Shared-token rotation procedure |
| RTP destination | SDP-derived | Exact RTPengine IP plus bounded port | Removes arbitrary media destination | Couples AS to anchoring invariant |
| Runtime | Writable/root/ambient capabilities | Read-only, non-root where possible, minimal capabilities | Narrows post-compromise actions | Some debugging requires explicit override |
| Analytics | Unneeded SIP identity accepted | Opaque Call-ID and timing only | Reduces personal-data propagation | Less ad-hoc debugging context |
| State | Unbounded process memory | TTL/count/resource bounds | Predictable overload behavior | Still not horizontally shared |

### Option 2: Orchestrated Shared Service

Here we separate signalling ingress, durable call control, RTP relay shards and
AI workers. A SIP-aware load balancer or Kamailio dispatcher keeps a dialog
affine while AS replicas store authoritative call transitions in a durable
service. RTPengine nodes are selected consistently and advertised through the
same state record. AI work moves through a bounded queue carrying opaque call
references, with per-stage deadlines and idempotency keys. Workload identity
and mTLS replace the shared token; a KMS or HSM owns key material.

This option scales along real bottlenecks: SIP transactions, RTP packets and AI
inference can grow independently. It also improves node-failure recovery and
key rotation. What gives me pause is added coordination in the setup path: a
state store or queue outage can reject new agent calls, and careless retries
can duplicate TTS or call transitions. The design therefore needs an explicit
state machine, idempotent commands, backpressure and tested regional failure
behavior. Existing RTP must remain fail-open even when AI is unavailable.

[Option 2 diagram](../diagrams/scalable-private-service-boundary-orchestrated-shards-after.mmd)

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Identity | Shared bearer | Workload identity + mTLS | Per-service revocation and policy | PKI/service-mesh operations |
| Call state | Process-local dicts | Durable state machine | Consistent replicas and audit | Network hop, database capacity |
| Media | One RTPengine | Region/shard pool | Smaller failure domains | Affinity and capacity management |
| AI | Synchronous local worker | Bounded queue + autoscaling | Backpressure and least data | Queue latency and duplicate handling |
| Secrets | Compose env/volume | KMS/HSM scoped credentials | Rotation and reduced extraction | Provider integration |

### Option 3: Tenant-Isolated Cells

Each tenant receives a dedicated AS/RTP/agent/data/key cell behind a shared
tenant-aware IMS edge. This makes cross-tenant compromise structurally harder
and gives independent retention, region and key-destruction policy. It is the
strongest fit for regulated tenants and data residency.

The price is underutilized capacity, more deployments, more upgrade surfaces
and harder fleet-wide incident response. Small tenants still need a full media
failure domain, and shared ingress remains a critical policy point. I would
choose this only when isolation requirements explicitly prohibit shared
compute or shared encryption domains; otherwise namespaces and per-tenant keys
inside Option 2 are usually proportionate.

[Option 3 diagram](../diagrams/scalable-private-service-boundary-tenant-cells-after.mmd)

| Change | Before | After | Security consequence | Cost |
| --- | --- | --- | --- | --- |
| Tenancy | Shared service | Dedicated service/key/data cell | Strong breach containment | Higher idle capacity and fleet count |
| Data residency | Implicit host | Explicit tenant region | Enforceable locality | Placement and migration complexity |
| Deletion | Shared lifecycle | Per-tenant destruction | Stronger offboarding evidence | Backup/key lifecycle coordination |

## Comparison

| Dimension | Option 1: Hardened Compose | Option 2: Orchestrated shared | Option 3: Tenant cells |
| --- | --- | --- | --- |
| Security | Strong local improvement; shared host/token remain | Strong service identity and bounded blast radius | Strongest tenant isolation |
| Performance | No new call-path hop | State/queue hops; independently scalable | Similar per-cell, lower utilization |
| Memory | Hard limits, still per-process state | Shared state plus queues/caches | State duplicated per cell |
| Reliability | Single-host failure remains | Node/worker failure isolation and regional HA | Tenant failures isolated; fleet complexity rises |
| Operability | Low incremental burden | Significant PKI, state, queue and autoscaling burden | Highest deployment and upgrade burden |
| Migration | Implemented incrementally | Requires state-machine and routing migration | Requires tenant partition/move tooling |
| Best fit | Development and controlled lab | General multi-user production | Contractual hard isolation |

All performance/resource directions are source-derived or hypothetical. We
must load-test representative call setup, RTP PPS and AI latency before setting
replica counts or claiming capacity.

## Recommendation

I recommend keeping Option 1 as the mandatory developer baseline and planning
Option 2 for production. The decisive reason is not Kubernetes itself; it is
the move from ambient, process-local authority to workload identity plus one
auditable call-state owner. Option 3 should replace Option 2 if a customer or
regulator requires dedicated compute/key/data boundaries or if a shared-cell
threat model is unacceptable.

## Evidence Coverage And Residual Risk

| Evidence | Option 1 | Option 2 | Option 3 |
| --- | --- | --- | --- |
| E1 — deployment authority | Addresses custom-service privileges; host remains shared | Addresses with workload policy | Addresses with cell isolation |
| E2 — SIP/SDP authority | Addresses media anchoring and API auth | Addresses with policy/state owner | Addresses within each cell |
| E3 — agent control/state | Mitigates with auth and bounds | Addresses replica consistency | Addresses per-tenant consistency |
| E4 — raw observation | Mitigates with NET_RAW-only container | Mitigates with isolated capture workers | Mitigates within tenant cell |
| E5 — AI ingestion/retention | Addresses local auth and bounds | Addresses via queue policy/TTL | Addresses per-tenant TTL |
| E6 — missing production contract | Unaffected | Unknown until SLOs are supplied | Unknown until tenant obligations are supplied |

Residual risks across all options include endpoint compromise, abuse by a
legitimate subscriber, model/provider data handling, metadata inference,
backup lifecycle and operator access. Tactical validation and rate limiting
remain necessary even after migration.

## Migration And Rollout

Option 1 is already staged as a reversible Compose change. For Option 2, first
define a call-state schema and idempotent transition API while keeping one AS;
then mirror state writes, test replay and failover, enable dialog-affine AS
replicas, introduce RTPengine shard selection, and finally move AI events to a
bounded queue. Roll back each stage by routing new calls to the previous owner
while allowing existing dialogs to drain. Never move live RTP across regions
without measuring packet loss and latency.

## Validation Plan

- Run the existing Phase 4A–4E and security gates on every change.
- Add abuse cases for oversized JSON/SIP, invalid Call-ID, unauthorized API,
  unanchored SDP, port-range escape, replay and duplicate control commands.
- Load-test calls/s, concurrent calls, RTP PPS, p95/p99 setup and AI latency;
  record CPU, RSS, queue depth and drop/rejection rates.
- Kill AS, state, queue, RTP and AI nodes independently and verify documented
  recovery plus fail-open RTP behavior.
- Inspect logs, traces, metrics, backups and crash dumps for IMSI, Ki/OPc,
  Digest, raw audio, transcripts and prompts.
- Test key rotation, tenant deletion and restore without resurrecting expired
  personal data.

## Implementation Work Packages

The implemented Option 1 work packages and acceptance criteria are in
[the implementation plan](../implementation/hardened-compose.md). Option 2
requires a separate design freeze after production requirements are supplied:
state machine, workload identity, routing/sharding, data classification/TTL,
backpressure, observability redaction and regional disaster recovery.

## Open Questions

- Peak calls/s, concurrent calls and media bitrate/codec mix?
- Required availability and recovery objectives by region?
- Are transcripts or recordings permitted, and with what consent and TTL?
- Which identifiers must support erasure, export or legal hold?
- Single organization or mutually untrusted tenants?
- Must any tenant have dedicated keys, compute, database or region?
- Which STT/LLM/TTS providers may receive audio or text, if any?
