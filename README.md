# Local 5G SA + IMS + OBSERVE agent lab

This directory starts the complete local stand on Docker Desktop/WSL2:

- Open5GS 5GC, one UERANSIM gNB, and two UEs;
- `internet` and `ims` PDU sessions for each UE;
- IMS DNS, PyHSS, Kamailio P/I/S-CSCF, and two PJSUA subscribers;
- RTPengine media anchoring;
- an iFC/ISC-triggered SIP Application Server, RTP Media Adapter, and minimal
  OBSERVE-mode AI Worker.

The first AI MVP classifies normalized RTP windows as audio activity. It is
outside the critical call path: stopping it does not stop SIP or RTP. This is
the Phase 4D OBSERVE stage, not yet a TRANSFORM or conversational TERMINATE bot.

## Configuration rule

All mutable topology, ports, pools, subscriber identities, and service timing
live in `lab.env`. Credentials and key material live only in the ignored
`secrets/ims.env`, created from `secrets/ims.env.example`.

Do not call bare `docker compose`: interpolation requires both env files. Use:

```powershell
.\scripts\compose.ps1 ps
.\scripts\compose.ps1 logs -f sip-as media-adapter ai-worker
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
python scripts/check-no-hardcoded-topology.py
```

The final gate proves all of the following from live evidence:

1. UE1 receives `200 OK` and UE2 receives the INVITE through IMS.
2. S-CSCF triggers the SIP AS through PyHSS iFC/ISC.
3. RTPengine has two streams whose endpoints are current IMS PDU addresses.
4. Media Adapter observes RTP packets and AI Worker emits an inference tied to
   the SIP Call-ID.
5. RTP counters continue increasing while AI Worker is stopped.

## Implementation notes

- The IMS DNN is non-NATed; P-CSCF, S-CSCF, RTPengine, and DNS install routes
  to the env-defined UE pool through the env-defined UPF address.
- PJSUA discovers its IMS TUN by CIDR, so no `uesimtun0/1` index is assumed.
- Kamailio/PyHSS/MySQL upstream images are pinned by digest. Locally built
  Python service images use a versioned base image pinned by digest.
- Media Adapter shares RTPengine's network namespace only to observe a copy of
  relayed RTP. The original relay remains independent of AS/AI availability.
- `../ims` remains the architecture/deployment repository; this directory is
  the runnable Docker implementation.

## Stop

```powershell
.\scripts\compose.ps1 down
```

Named database volumes are preserved. Add `-v` only when you intentionally
want to erase lab databases and reprovision from scratch.
