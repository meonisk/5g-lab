# Local 5G SA + IMS + voice-agent lab

This directory starts the complete local stand on Docker Desktop/WSL2:

- Open5GS 5GC, one UERANSIM gNB, and two UEs;
- `internet` and `ims` PDU sessions for each UE;
- IMS DNS, PyHSS, Kamailio P/I/S-CSCF, and two PJSUA subscribers;
- RTPengine media anchoring;
- an iFC/ISC-triggered SIP Application Server, RTP Media Adapter, and local
  OBSERVE-mode faster-whisper STT worker;
- a native IMS TERMINATE Voice Agent reachable at the service number defined
  by `VOICE_AGENT_MSISDN` in `lab.env`.

The OBSERVE path copies real PCMU payloads from RTPengine, keeps bounded audio
windows in memory, and transcribes them with a revision-pinned local
faster-whisper model. It is outside the critical call path: stopping it does
not stop SIP or RTP. The separate TERMINATE agent answers a real IMS call,
plays a locally synthesized greeting, detects a completed speech segment, and
synthesizes a deterministic reply. The transcript does not yet drive an LLM or
the reply path.

## Configuration rule

All mutable topology, ports, pools, subscriber identities, and service timing
live in `lab.env`. Credentials and key material live only in the ignored
`secrets/ims.env`, created from `secrets/ims.env.example`.

Do not call bare `docker compose`: interpolation requires both env files. Use:

```powershell
.\scripts\compose.ps1 ps
.\scripts\compose.ps1 logs -f sip-as voice-agent media-adapter ai-worker
```

or from Git Bash:

```bash
./scripts/compose.sh ps
```

`scripts/check-no-hardcoded-topology.py` rejects topology or subscriber
literals outside the two canonical env files.

## Start everything

Prerequisites: Docker Desktop with Linux containers and Git for Windows.

```powershell
Copy-Item secrets\ims.env.example secrets\ims.env  # first run only; review values
.\scripts\start-lab.ps1
```

The start script loads SCTP in Docker Desktop, builds/starts the full stack,
idempotently provisions Open5GS and PyHSS subscribers, restarts the UE clients,
and runs all acceptance gates. Use `-SkipVerify` only for development.

## Acceptance gates

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify-ims.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify-ims-registration.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify-ims-call.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify-voice-agent.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify-real-ai-stream.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/verify-security.sh
python scripts/check-no-hardcoded-topology.py
python research/tools/research_run.py verify --root .
```

Research designs, the local/physical-stand validity boundary, metrics, privacy
rules, and the evidence-capture workflow are documented in
[`research/README.md`](research/README.md). A passing research-tooling check is
an instrumentation admission result, not an AI-performance result.

The Phase 4C/4D gate proves all of the following from live evidence:

1. UE1 receives `200 OK` and UE2 receives the INVITE through IMS.
2. S-CSCF triggers the SIP AS through PyHSS iFC/ISC.
3. RTPengine has two streams whose endpoints are current IMS PDU addresses.
4. Media Adapter observes RTP packets and AI Worker emits an inference tied to
   the SIP Call-ID.
5. RTP counters continue increasing while AI Worker is stopped.

The real-stream gate additionally proves that live PCMU from an IMS call is
decoded, resampled, processed by the local STT model, and produces an
authenticated in-memory transcript tied to the SIP Call-ID.

The Phase 4E gate calls the configured service number from UE1 and proves that
the caller receives `200 OK`, PCMU is negotiated, the ACK reaches SIP AS, both
IMS-PDU and Voice Agent endpoints exist in RTPengine, RTP reaches the agent,
and BYE releases the SIP and media session.

To place the same call manually after registration:

```powershell
$number = (Select-String '^VOICE_AGENT_MSISDN=' lab.env).Line.Split('=', 2)[1]
$domain = (Select-String '^IMS_DOMAIN=' lab.env).Line.Split('=', 2)[1]
docker exec lab-sipue1 sh -lc "printf 'm\nsip:${number}@${domain}\n' > /tmp/pjsua-control"
```

## Implementation notes

- The IMS DNN is non-NATed; P-CSCF, S-CSCF, RTPengine, and DNS install routes
  to the env-defined UE pool through the env-defined UPF address.
- PJSUA discovers its IMS TUN by CIDR, so no `uesimtun0/1` index is assumed.
- Kamailio/PyHSS/MySQL upstream images are pinned by digest. Locally built
  Python service images use a versioned base image pinned by digest.
- Media Adapter shares RTPengine's network namespace only to observe a copy of
  relayed RTP. The original relay remains independent of AS/AI availability.
- The Voice Agent terminates only its env-defined service number; ordinary
  subscriber-to-subscriber calls remain proxied through P/I/S-CSCF.
- Voice prompts, VAD threshold, silence interval, RTP/HTTP ports, service
  identity, address, and stale-call timeout are all configured in `lab.env`.
- Custom service control uses a randomly generated token stored in a private
  Docker volume. It is not placed in Git, `lab.env`, container command lines,
  or ordinary service logs.
- Voice Agent accepts media only from the env-defined RTPengine address and
  port allocation. Audio is processed in memory and is not recorded; the
  analytics path receives no SIP `From`/`To` subscriber identities.
- STT audio windows and transcripts are bounded and memory-only. Model files
  use a separate persistent cache volume; the model revision and Python
  dependencies are pinned. Operational logs record sizes and timings, not
  transcript text.
- Custom services use read-only root filesystems, no-new-privileges, bounded
  resources/logs/state, and minimal Linux capabilities. The Media Adapter is
  the only custom service retaining `NET_RAW` for RTP observation.
- IMS/UE service stdout logs are size/rotation bounded, while PyHSS file logs
  use a non-persistent tmpfs. Mongo subscriber data remains persistent; for a
  production deployment its storage must be encrypted with managed keys and a
  tested deletion/backup policy.

## Scaling and data protection

The implemented profile is the secure single-host development baseline. It is
not presented as a production multi-tenant deployment. The compared production
options, trust boundaries, data-retention rules, migration order, and remaining
decisions are in [the security hardening review](hardening/hardening.md) and
[the full proposal](hardening/proposals/scalable-private-service-boundary.md).

The recommended production direction is dialog-affine SIP AS replicas, a
durable call-state owner, an RTPengine shard pool, workload identity with mTLS,
KMS/HSM-backed secrets, bounded metadata queues, and independently autoscaled
AI workers. Dedicated per-tenant cells are reserved for tenants whose legal or
contractual isolation requirements justify separate compute, keys, and data.
- `../ims` remains the architecture/deployment repository; this directory is
  the runnable Docker implementation.

## Stop

```powershell
.\scripts\compose.ps1 down
```

Named database volumes are preserved. Add `-v` only when you intentionally
want to erase lab databases and reprovision from scratch.
