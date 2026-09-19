# Hardening evidence context

Analysis date: 2026-09-18. Source repository revision before implementation:
`3f9853e052befc8200815ab1074ce9a472d03433`. The implementation was performed
in the working tree, so source drift is intentionally recorded as present.
The hashes below are the exact blobs from that pre-implementation revision,
not the subsequently hardened working-tree files.

Evidence collection digest (SHA-256 over the ordered path/hash inventory):
`0564e6afa5c7d1e93ccfb3bd87242fedfcfa330238d67181004b95f12d8c3ff5`.

| ID | Source | SHA-256 | What was inspected |
| --- | --- | --- | --- |
| E1 | `docker-compose.yml` | `dfb29d79f7609c296e9e44f0667b3fc45d3c3df5a30f7cb74ad27306e2daa999` | Deployment boundaries, capabilities, secret propagation, networks and resource controls |
| E2 | `services/sip-as/server.py` | `78934a3b852bb2064c975a72130421a027adbc181d73ba2ff7523b7bc29e8834` | SIP/SDP trust boundary and service-to-service calls |
| E3 | `services/voice-agent/agent.py` | `0c7d3cab0922167e89bfff7b69f7169d1a17630dfdfe26165e2ab9f208440661` | Control API, RTP destination authority, transient call state and audio handling |
| E4 | `services/media-adapter/adapter.py` | `dae13f90854e63b2ddfcff39269ee4f55dd94cdf411478c993ff86354d9bd5d1` | Raw-packet capability and analytics data flow |
| E5 | `services/ai-worker/worker.py` | `10f882d036edb8efc7b360f84f9ceddac0d88b82325848da21b8c4fbf98a7d53` | Event retention and unauthenticated ingestion |
| E6 | `lab.env` | `285d6c4012900a7aba37830565c3f4439e09d8b47f60041ace714d6c9da66dfe` | Central configuration and absence of production sizing parameters |

No production traffic capture, load benchmark, external identity provider,
or regulatory classification was supplied. Performance and production-scale
claims are therefore source-derived or hypothetical, never measured.
