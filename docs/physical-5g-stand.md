# Physical 5G stand integration contract

Current implementation limits: [status.md](status.md). This is a migration
contract; it is not a report of completed physical-stand acceptance.

Native-phone integration is now active; see [native-phone.md](native-phone.md)
for device requirements, measured blockers and physical acceptance. The virtual
[5GS/IMS profile](3gpp-profile.md) remains the regression baseline.

## Scope

The Docker profile is the executable integration baseline. A physical stand
replaces UERANSIM gNB/UE and host-specific transport, and also requires verified
discovery, authentication, access security, policy and codec interoperability.
This is not just a container replacement. OAI CN5G, IMS DNS,
PyHSS, P/I/S-CSCF, SIP AS, RTPengine, Media Adapter, STT, LLM, and Voice Agent
retain the same service contracts. Passing the Docker gates is necessary but
is not evidence of RF, mobility, QoS, or physical-device behavior.

## Preserved service path

```text
physical UE/USIM -> NR-Uu -> physical gNB -> N2/N3 -> OAI/UPF
  -> IMS DNN -> P-CSCF -> I-CSCF -> S-CSCF -> iFC/ISC -> SIP AS
  -> RTPengine -> Voice Agent / Media Adapter -> sentence VAD
  -> bounded inference queue -> STT -> translation LLM -> language-specific TTS
  -> RTPengine -> IMS DNN -> Russian or English physical UE
```

The AI service remains outside the 5GC control plane. It receives media only
after IMS call control and RTP anchoring have admitted the dialog.

## Physical integration inputs

Freeze these values before deployment; do not insert them into scripts:

- PLMN, TAC, S-NSSAI and gNB identity;
- AMF N2 address and UPF N3 address;
- `internet` and `ims` DNNs and their UE pools;
- DNS and P-CSCF discovery delivered to the UE;
- IMS home domain, public/private identities, authentication profile and iFC;
- routed return path from IMS/RTPengine to the IMS UE pool;
- supported codec, packetization interval, RTP port policy and MTU;
- clock source and maximum clock uncertainty for RAN/core/service hosts.

Site-specific values belong in a deployment env/secrets layer. The checked-in
Docker `app/config/lab.env` remains a synthetic profile and must not contain production
subscriber material.

## Required differences from the Docker profile

1. Replace `gnb`, `ue1`, `ue2`, `sipue1`, and `sipue2` with the physical RAN,
   USIM/ISIM-backed UE, and its native IMS client.
2. Bind N2/SCTP and N3/GTP-U to dedicated stand interfaces or VLANs. Do not
   expose SBI, Diameter, service-control HTTP, Ollama, or database ports to the
   RAN network.
3. Advertise the IMS DNN through subscriber policy and deliver DNS/P-CSCF using
   the mechanism supported by the UE. Static PJSUA routes are a Docker-only
   proof boundary.
4. Preserve a routed, non-NATed return path for the IMS UE pool. RTPengine must
   observe the real UE PDU address, not a management address.
5. Replace laboratory SIP Digest handling with the authentication and
   P-CSCF-access security profile supported by the selected UE/ISIM. TLS,
   IPsec/SRTP, lawful-intercept requirements, and emergency services require a
   separate approved design; they are not implied by the Docker result.
6. Place model cache, subscriber databases, restricted evidence, and backups on
   encrypted storage with managed keys and an explicit retention/deletion
   policy.

## Acceptance sequence

Advance only when every preceding stage is retained as evidence:

1. **RAN:** NG Setup, physical UE registration, stable N2/N3 and declared clock
   uncertainty.
2. **5GC:** both DNN sessions, expected UE addresses, UPF counters, DNS reachability
   and no unintended IMS NAT.
3. **IMS:** `REGISTER -> challenge -> authenticated REGISTER -> 200 OK`, Cx
   success and a current registrar contact sourced from the IMS PDU address.
4. **Subscriber call:** applicable originating/terminating IMS routing,
   INVITE/SDP/200/ACK/BYE, RTP streams tied to physical UE addresses and audible
   bidirectional media using the accepted UE codec profile. PCMU/8000 remains
   the current internal AI contract; required media interworking is separate.
5. **Translation call:** translator-number iFC/ISC trigger, Russian greeting,
   at least two Russian-to-English spoken turns under one Call-ID, and clean BYE.
6. **Interpreted call:** separate Russian and English service legs, no raw-media
   bridge, at least two complete translations in each direction, target-language
   validation, completed TTS/RTP on both legs, and per-stage latency records.
7. **Transcription call:** separate recorder-number trigger, audible recording
   disclosure, private WAV creation, local-LLM text normalization without
   content in operational logs, transcript persistence, and finalization on BYE.
8. **Failure containment:** ordinary RTP remains usable when AI is stopped;
   terminate-service failure is bounded and visible.
9. **Privacy:** inspect logs, packet captures, traces, crash dumps and backups;
   no Ki/OPc, Digest secret, raw audio, transcript or prompt may enter the
   shareable evidence set.
10. **Radio study:** only after stages 1–9, freeze mobility, RF, QFI/QoS, load,
   model, repetitions and outcome definitions before collecting results.

## Physical-only claims

Handover, RF impairment, real microphone/speaker acoustics, native UE IMS
behavior, P-CSCF access security, QFI enforcement and multi-host timing remain
unverified until measured on the physical stand. Docker acceptance results must
not be relabeled as evidence for those properties.
