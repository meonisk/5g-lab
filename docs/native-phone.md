# Native Android phone: active integration target

The target is automatic registration after inserting a provisioned test SIM and
normal calling from the phone's built-in dialer. A separately installed SIP app
does not satisfy this target. This work is active; physical acceptance is pending.

## Device and SIM selection

Manufacturer or a “5G” label is insufficient. Choose an unlocked Android device
with a documented firmware build supporting **5G SA and VoNR on the partner's
NR bands**, IMS on the selected test PLMN, and AMR/AMR-WB. Get the exact model,
regional variant, modem/firmware and band from the partner before purchasing.
5G NSA/VoLTE alone is not sufficient for a standalone OAI 5GC with no LTE/EPC.
No particular Xiaomi, OnePlus or other model has been validated on this stand.

Use a programmable lab USIM/ISIM with known administration credentials and an
agreed IMS identity profile. An ordinary operator SIM cannot simply be copied
into our HSS. Configure matching subscriber credentials in the partner core and
our IMS HSS; whether IMS uses the same credentials depends on the selected card.
Keep key material in the private provisioning workflow, never in this document.
Do not overwrite an operator SIM or assume factory-created lab keys match a card.

Automatic operation may require an initial carrier/IMS profile configuration on
the selected firmware. Record that setup; a manually launched SIP client is not
an acceptable substitute. Android's IMS behavior also depends on carrier policy:
[Android IMS entitlement](https://source.android.com/docs/core/connect/ims-service-entitlement).

## Current evidence and remaining implementation

| Area | Current state | Required acceptance |
| --- | --- | --- |
| OAI + IMS AKA | Local synthetic AKA registration/call passed | Native UE identity and resynchronization |
| P-CSCF IPsec | WITH_IPSEC already enabled | Negotiation, protected REGISTER/INVITE, XFRM SAs, re-registration |
| P-CSCF discovery | OAI configured with P-CSCF address | Capture UE PCO/EPCO and automatic IMS session |
| AMR/AMR-WB | Encoders installed; synthetic bidirectional RTP passed, octet-align 0 and 1 | Native codec modes, DTX, RTCP and audio quality |
| AI media boundary | AI destinations add PCMU through RTPengine; incompatible offers rejected | Full AMR SIP call through IMS and AI, then native phone |
| Phone SIP behavior | Required 100rel/precondition offers rejected | Implement/test PRACK, UPDATE and negotiated QoS behavior |
| Normal calls | Synthetic bidirectional PCMU passed | Native outgoing/incoming calls, hangup, idle/reattach |
| AI services | Local PCMU AI path passed previously | Native dialer service call and far-end intelligible audio |

The original RTPengine inspected on 2026-09-29 was 26.0.1.23 and reported AMR
and AMR-WB decoding only. The rebuilt image includes `libavcodec-extra59` and
reports both fully supported; EVS remains unsupported.
Installing an AMR library by itself is not evidence of an encoder in FFmpeg or
of working call negotiation. Use the runtime capability report and actual media
tests. [RTPengine transcoding documentation](https://rtpengine.readthedocs.io/en/master/transcoding.html)
describes this dependence and the need to explicitly enable transcoding.

`python app/tests/integration/verify_phone_codecs.py` passed against the rebuilt
running relay: AMR returned 24 encoded / 24 decoded frames, AMR-WB 23 / 22,
for both octet-align modes. The finite wideband test leaves resampler lookahead
buffered; it is not a packet-loss or end-to-end latency measurement. It verifies
NG offer/answer and nonconstant RTP payload after a round trip, not intelligible
speech, a complete SIP call or handset playback. Each synthetic call is deleted.
After the image and P-CSCF changes, the PCMU IMS Voice Agent gate passed,
including ACK, RTP and BYE cleanup. The multi-turn Russian-to-English AI gate
also passed. These PCMU gates do not replace an AMR SIP/AI end-to-end test.

An initial ordinary two-UE call regression failed after component/client
restarts despite successful registration; retain `local/phone-ims-call.log`
as failed evidence. Recreating both SIP clients and waiting for registration
restored the call: `local/phone-ims-call-retry.log` passed both RTP legs and
fail-open operation with AI stopped. The restart failure's root cause remains
unresolved; this recovery is not full lifecycle acceptance. Offline quality
checks and all 185 unit tests passed. Evidence logs remain private/untracked.

Run `python scripts/phone_readiness.py` for a read-only capability report.
Exit code 1 / `NOT_READY` is intentional until physical acceptance is complete;
configuration checks cannot certify a phone. No credentials are read or printed.

## Partner handoff and test sequence

Use [partner-integration.md](partner-integration.md) for our IMS + AI deployment.
Partners retain OAI/RAN/subscriber policy ownership. Agree PLMN, NR band, SA/VoNR,
IMS DNN, UE pool, P-CSCF/DNS delivery, return routes, authentication identities,
and QoS/policy support. Their existing core must advertise voice support as
appropriate to the actual deployed capabilities; our containers cannot supply
missing radio or core policy behavior.

1. Provision the chosen test card and both core/IMS subscriber records privately.
2. Reboot the phone: observe radio and 5GS registration without a softphone.
3. Observe automatic IMS PDU session, DNS and P-CSCF discovery.
4. Observe IMS AKA, any AUTS recovery, negotiated IPsec and successful protected registration.
5. Make incoming and outgoing native calls; verify ringing, answer, both audio
   directions, codec negotiation and BYE cleanup.
6. Call each AI service number; verify speech recognition, translation/response
   and playback at the phone. Retain codec and timing evidence, not just SIP 200.
7. Repeat after airplane mode, idle, IMS re-registration and service restart.

Do not mark a stage passed using UERANSIM/PJSUA evidence. Emergency calling,
SMS, public telephone interconnect and mobility require separately scoped tests;
“all features” here means the project's IMS calls and AI services.
