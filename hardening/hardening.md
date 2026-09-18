# Security Hardening Review: Local IMS Voice Agent

## Evidence Basis

I inspected the Compose deployment and the SIP AS, Voice Agent, Media Adapter,
and AI Worker boundaries at revision `3f9853e`. The strongest evidence is the
combination of a flat service network, unauthenticated internal HTTP endpoints,
an SDP-derived RTP destination, broadly propagated subscriber secrets, and
in-memory per-call state. These are acceptable shortcuts for an isolated lab,
but together they create a large blast radius and prevent safe horizontal
scaling. The complete inventory is in [context.md](context.md).

## Constraints

We preserve the working two-UE Docker lab, the fail-open OBSERVE path, the
env-only topology rule, and the current P/I/S-CSCF plus RTPengine call flow.
No production latency, concurrency, jurisdiction, identity-provider, or
retention requirement was supplied, so we use a balanced profile and do not
pretend the local implementation is a production cluster.

## Opportunity Portfolio

| Opportunity | Evidence | Options | Recommendation | Proposal |
| --- | --- | --- | --- | --- |
| Separate media authority, personal data, and scalable call state | Flat deployment and secret propagation (E1/E6); SDP and control authority (E2/E3); analytics retention (E4/E5) | 1. hardened Compose; 2. orchestrated shared service; 3. tenant-isolated cells | Implement Option 1 now; use Option 2 before multi-user production | [Full proposal](proposals/scalable-private-service-boundary.md) |

## Recommendation Summary

Under the current local-lab constraints, I recommend the hardened Compose
boundary because it removes ambient control authority without introducing a
database or cluster into the working call path. That option has now been
implemented and covered by `scripts/verify-security.sh`.

For production scale, Option 2 is the target: stateless SIP AS workers behind
dialog-affine routing, a durable call-state/control service, an RTPengine pool,
and independently autoscaled AI workers. Option 3 becomes preferable only when
contractual or regulatory isolation requires a separate key, database, and
media cell per tenant; its operational cost is otherwise disproportionate.

## Next Decisions

Before implementing the cluster target we still need peak concurrent calls,
regional latency, failure-domain, retention, lawful-intercept, jurisdiction,
and tenant-isolation requirements. Those values determine sharding, queue and
database technology, key ownership, and whether media may cross regions.
