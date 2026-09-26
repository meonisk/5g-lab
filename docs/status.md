# Implementation and validation status

Updated 2026-09-22 after expired-Contact routing repair and live validation. Runtime claims below are limited
to the explicitly executed gates; this is not standards certification or a scientific result.

| Area | Current state | Evidence boundary |
| --- | --- | --- |
| Source checks | Offline suite checks formatting, syntax, layout, Git hygiene, documentation and 175 unit tests | No Docker calls or audio playback |
| Local 5G/IMS | Connectivity, IMS route/DNS/NAT, two-UE AKA/Cx registration and continuous AKA two-way PCMU call passed | Full lifecycle/restart matrix remains open; receiver WAV evidence is not speaker timing |
| Speech stack | Whisper small, Qwen3 4B Q4_K_M and Piper RU/EN, CPU default | Models/images download on the receiving host; cold start and resources vary |
| Interpreter | One pair of separately terminated Russian/English legs; phrase-based default | Functional gate is additional to startup; no production capacity claim |
| Streaming | Disabled by default; historical trials failed coverage and/or latency | No accepted run satisfying both conditions |
| User latency target | 1–3 seconds from speech start to far-end audible output remains open | Current timestamps end at server RTP send, not receiver playback |
| Recording | Separate service number, audible disclosure, private output | Retention deadline is declared; deletion remains an operator action |
| Research | Admission tooling and candidate designs exist | AI-scale design is not frozen; no main scientific result |
| Physical 5G | Integration contract exists | RF, native UE/ISIM, handover and real speaker timing remain unverified |
| Production | Single-host lab only | Durable call state, multi-tenant isolation and capacity acceptance remain design work |

## Publication checks performed

On 2026-09-21 a clean Git clone passed the full offline suite on Windows with
Python 3.14, including 28 unit tests and 64 local link targets in 23 documents.
Fresh local credential generation and `docker compose ... config --quiet` also
passed. Configuration parsing does not start containers or prove a working call.
The original repository's reachable history was checked against its local
credentials after sanitization. Guard probes rejected an audio file in the index,
a broken document link and a credential literal without printing its value.

## Interpreting test output

`python scripts/quality/check.py` is the offline development check.
`python scripts/quality/check_git.py --history` also scans all reachable Git refs
for prohibited paths, oversized blobs, selected credential signatures and known
local credentials. It is a publication guard, not an exhaustive security audit.

The startup launcher runs nine shell gates. Run the additional interpreter and
parallel-call gates from [running.md](running.md) serially on a working stand.
`--skip-verify` now reports STARTED/UNVERIFIED. `--base-only` always runs its three
base gates and skips AI model/fixture warmup.
Historical PASS/FAIL results remain attached to their original configuration.
Changing source, models, fixture, hardware or timing requires a separate run.

Private WAVs and logs are deliberately not shipped. The historical streaming
figures in [streaming.md](streaming.md) document failed experiments; the source
repository alone cannot independently verify those recordings.

## Remaining acceptance work

The active target is a virtual stand, not physical equipment. The proposed
[5GS/IMS profile](3gpp-profile.md), [requirements matrix](3gpp-requirements.md)
and [acceptance scenarios](3gpp-acceptance.md) define the next implementation
increments. They are design artifacts, not passed tests or a 3GPP compliance claim.

The 2026-09-21 follow-up audit observed a partial restart: DNS and both SIP
clients were stopped while AI was healthy; UE routes to P-CSCF used the Docker
bridge without the client-installed IMS routes. An isolated mock probe also
showed that `verify.sh` can exit successfully after both UE network checks fail.
These observations require recovery and gate repairs before fresh acceptance.
They do not invalidate historical runs, but offline PASS cannot close these gaps.

1. Run startup and all applicable additional live gates from a clean clone.
2. Fix ASR revisions and missing tails before enabling streaming by default.
3. Measure speech-start-to-receiver-audible latency on a common clock and check
   source coverage and translation meaning together.
4. Freeze the corpus, experimental design and analysis before research claims.

## Virtual recovery implementation, 2026-09-21

The stopped stand was recovered with cold Mongo/MySQL backups and SCTP loading.
MySQL data was migrated from its writable container layer to `mysql-data`, with
fresh cold backup, local rollback image and a migration receipt kept private.
HSS API retained two IMS subscribers and three regular/AuC rows. The first
post-migration registration attempt failed during startup; later fresh attempts
passed after IMS readiness and the SIP route watcher were corrected.

Live `verify.sh`, updated `verify-ims.sh`, and `verify-ims-registration.sh` passed.
A controlled removal of UE1's P-CSCF route caused automatic SIP restart and route
recovery; fresh two-UE registration and IMS network checks passed afterwards.
This covers one recovery fault, not the complete T01 matrix. AI services remain
stopped in this base-only runtime. No audio/AKA/3GPP acceptance follows from it.

Offline changes also reject malformed evidence inventories and preserve partial
failed collection attempts. Provisioning preserves existing records and AuC SQN;
independent subscriber credentials and explicit profile migrations were added
after this recovery; live key rotation remains pending.

## Plain-call acceptance increment, 2026-09-21

The new `verify_plain_call.py` gate temporarily installs an iFC without AS
triggers, restarts S-CSCF to invalidate cached profiles, waits for negotiated Cx
peers, and performs fresh two-UE registration. It checks INVITE/ACK/BYE/200,
call-specific S-CSCF participation, no AS forwarding, two active PCMU relay legs,
relay deletion after BYE, and opposite-source audio in both receiver WAVs.
The original iFC and ordinary SIP clients are restored after each attempt.

Attempt `plain-call-20260921T204551662086Z` passed with AS/AI stopped. Both
eight-second continuous markers exceeded 0.9998 minimum block correlation.
Reverse caller attempt `plain-call-20260921T204919697108Z` also passed.
Negative attempt `plain-call-20260921T205259872828Z` passed the stricter fault
predicate: UE1 source disconnected, UE2 recorder quiet for at least eight seconds
(RMS <=160 and peak <=512 PCM16), while UE1 still received UE2's marker.
All three attempts passed profile/client cleanup and fresh registration.
Earlier negative attempt `plain-call-20260921T205110749830Z` used a weaker
predicate and is superseded for acceptance by this separate stricter run.
Earlier failures remain unchanged: cached iFC, peer startup race, comparator
alignment, buffered diagnostics, shell CRLF and audio clock conversion were
investigated separately. PJSUA now uses 8000 Hz throughout its conference path.
This is Digest/PCMU regression evidence, not AKA, protected Gm, policy/QoS,
translation coverage, latency acceptance or full T05–T07 acceptance.

New installations generate independent credentials per UE and per 5GS/IMS
domain. Existing legacy credentials remain supported and untouched. The explicit
key migration tool has backup, SQN preservation, source rechecks and rollback,
with additional rollback and ownership tests. The 2026-09-22 migration below
replaced this stand's legacy shared keys.
Shareable research logs now remove protocol dumps into metadata-only markers;
raw diagnostics and recordings remain private.

## Independent keys and AKA client preparation, 2026-09-22

Private session `key-migration-20260921T210227Z` contains the dry-run/apply
receipt, pre-migration database/secret backups, postcheck and launcher logs.
Four distinct UE/domain K/OPc profiles were applied with both UE and SIP clients
stopped. Immediate readback required unchanged AuC SQN and all non-key Open5GS
security fields. The extra AuC row and Digest password remained unchanged.

REST omits PyHSS ki/opc; migration and repeated provisioning now verify keys
through read-only local SQL, checking AuC identity and subscriber ownership.
The first full base launcher failed because this mongosh build mishandles
optional method calls. A synthetic string reproduced the TypeError; explicit
type checking fixes the provisioner. The failed startup log remains retained.
The next launcher reached registration but failed because Digest clients still
used the old shared password. This PyHSS returns AuC ki for Digest; Compose now
binds each client's password to its own IMS key. The legacy secret value itself
remains unchanged and is only a fallback for installations without per-UE keys.
The next full `start_lab.py --base-only` run completed successfully:
`startup-digest-profile.log` records all three base gates passing, both current
IMS routes/registrar contacts and fresh Digest registrations. The DNS restart
policy and changed service environments were applied by this launcher.
This covers this full startup/restart sequence, not every T01 recovery fault.
Post-migration call `plain-call-20260921T210914112480Z` passed both receiver
waveform checks, SIP/relay checks and cleanup. Original iFC was restored and
both clients registered again. AS/AI remain stopped in the 24-container base.

The [dedicated SIPp image](sipp-aka-provenance.md) builds from checked source,
patch and license hashes and passes its binary-parameter selftest and version
smoke. It is preparation for a continuous AKA client, not live AKA acceptance.

## Live AKA registration and correlated Cx, 2026-09-22

SIPp now accepts explicit OPc without deriving OPc from it again. Its image
preserves the OP path, rejects simultaneous OP/OPc, and tests Milenage outputs
against TS 35.208 set 1. No subscriber keys were changed to accommodate SIPp.

Attempt `aka-register-20260921T212450046883Z` passed both independent UE
registrations using AKAv1-MD5, with matching Contact and nonzero expiry. Its
private Cx PCAP contains six paired UAR/MAR/SAR transactions. The verifier
reassembles TCP, checks Diameter transaction/session/user identity and result
namespaces, and matches each SIP 401 nonce to its own MAA RAND/AUTN using keyed
fingerprints. Raw credentials, generated scenarios, vectors and captures stay
private. Original Digest clients were restored and freshly registered afterwards.

Negative attempt `aka-register-20260921T212549492023Z` also passed: UE1's
deliberately invalid response received 403, while UE2 received 200. Correlated
Cx contains UAR/MAR for UE1 and UAR/MAR/SAR for UE2 (five pairs), with both
SIP challenges bound to their own MAA. Cleanup and fresh Digest registration
passed. This tests bad-response isolation, not wrong-K AUTN checking or resync.

The first attempt `aka-register-20260921T211733411658Z` remains FAIL because its
then-current verifier rejected valid provisional 100 responses. Later gates
accept 100 only within the correct outstanding REGISTER transaction. Earlier
positive and bad-response probes without integrated Cx correlation are retained
separately; they are not relabeled as the stronger gate.

This is a registration capability increment. SIPp exits after REGISTER here;
a continuous AKA-authenticated call with the same endpoint is still open, as
are persistent UE SQN/replay/resync, expiry/refresh/deregistration, protected Gm,
policy/QoS and translation acceptance. It does not close all of T03.

## Continuous AKA call increment, 2026-09-22

`aka-call-20260921T213917277478Z` passed with UE1 as caller, including cleanup.
Each UE kept one SIPp process and UDP socket from its own AKA registration to
the completed call; REGISTER and INVITE used different Call-IDs. Cx/SIP nonce
binding passed for both UEs. INVITE/200/ACK/BYE/200, IMS PDU media routing,
PCMU/8000 relay activation/removal and the no-AS path were checked.

Each receiver accepted approximately 20 seconds of the other UE's RTP without
sequence gaps. Both eight-second waveform checks passed. Media is generated
and decoded by a separate helper in each UE's network namespace: this is UDP
receiver audio evidence, not a SIPp decoder, handset playback or latency SLA.
Temporary iFC changes were restored and both normal Digest clients registered.

The first attempt `aka-call-20260921T213538181631Z` remains FAIL: its AKA, Cx
and receiver audio passed, but the verifier incorrectly compared entire Via
strings across IMS proxy chains. The subsequent gate binds the request branch
within the response Via chain. This closes the basic continuous positive call
slice only; it does not close the complete T03/T05-T07 matrices, persistent UE
SQN/replay/resync, protected Gm, policy/QoS or translation acceptance.


Reverse attempt `aka-call-20260921T214202102438Z` passed its AKA, Cx, dialog,
receiver audio and relay checks, but remains overall FAIL/cleanup FAIL. During
restoration UE2 received 504 and retried after 62 seconds, outside the gate's
60-second wait. Its later fresh 200 REGISTER was observed separately; that does
not retroactively change the failed attempt.


Reverse repeat `aka-call-20260921T214530534792Z` passed all checks and cleanup
with exact Via branch-token matching and repeated Via-header preservation.
Both caller directions now have independent passing attempts. Restoration now
has a dedicated 90-second bound to accommodate a native retry, and records
REGISTER response codes. This is bounded recovery, not a fix for the transient
504 or acceptance of the full restart/fault matrix.


Final direct regression `aka-call-20260921T214732091373Z` passed with cleanup
on the bounded-restoration implementation. The complete offline quality suite
passed with 135 unit tests. All historical FAIL records remain unchanged.


## AKA lifecycle validation work, 2026-09-22

The initial lifecycle attempt `aka-lifecycle-20260921T215533508336Z` remains
FAIL/cleanup PASS. The strict trace validator rejected SIPp's default Digest
URI (P-CSCF transport destination), which differed from the REGISTER URI.
All three AKA runners now supply `-auth_uri` with the bare IMS domain; pinned
[SIPp 3.7.7 auth.cpp](https://github.com/SIPp/sipp/blob/v3.7.7/src/auth.cpp)
adds the `sip:` scheme. Base registration validation also checks realm,
algorithm and Digest URI. Older accepted runs retain their original scope;
they were not verified by this newer URI assertion.

Attempt `aka-lifecycle-20260921T215850668900Z` remains FAIL/cleanup PASS.
Initial registration and refresh reached current Contact readbacks, but the
10-second deregistration absence window was too short. Saved S-CSCF logs show
explicit deregistration and `Contact deleted`; the RPC still serialized the
tombstone with the prior expiry. Live module parameters were deletion delay
30 seconds and timer interval 90 seconds. The new bound allows 210 seconds
for physical deletion without background re-registration; it does not count
SIP 200 or a tombstone as proof of absence.


Lifecycle attempt `aka-lifecycle-20260921T220158073228Z` passed all gates and
cleanup. For each UE, S-CSCF readback showed expiry 299 seconds initially,
294 in the aged sample, then 299 after refresh. After explicit deregistration,
each IMPU readback returned absent with zero contacts. The same SIPp process
performed all three challenged exchanges; all six SIP 401s were uniquely bound
to their own user's MAA vectors and sessions. The final Cx summary passed.
Registrar timer parameters (90-second timer, 30-second delayed delete) are
retained with the private evidence. Both ordinary Digest clients were restored.

This accepts the challenged refresh/explicit-deregistration slice of I05/T03.
Passive expiry, a call to the old Contact after deregistration, UE IP change,
replay, persistent UE SQN/AUTS, protected Gm and exact SAR assignment subtypes
remain open. Full offline quality passed with 150 unit tests.


After the Digest URI correction, continuous call regressions passed in both
directions with cleanup: `aka-call-20260921T220559719229Z` (UE1 caller) and
`aka-call-20260921T220751656741Z` (UE2 caller). These fresh traces passed the
stricter registration verifier as well as dialog, Cx and receiver-audio checks.

Negative regression `aka-register-20260921T220949585531Z` also passed with Cx
and cleanup: the deliberately invalid UE1 response was rejected while UE2
registered successfully under the corrected Digest URI configuration.


## Calls after registration removal, 2026-09-22

Initial attempt `aka-inactive-deregister-20260921T221535154233Z` remains FAIL
with cleanup PASS. Contact removal, caller AKA, Cx authentication, SIP 404/ACK,
no delivered callee INVITE and relay cleanup passed. The harness passed the
30-second passive-expiry limit to a callee initially registered for 300 seconds
in explicit-deregistration mode; the strict callee trace check rejected that
mismatch. The parameter is now mode-specific. The next gate also verifies one
exact UDP bind at the old SIP Contact before and after the rejected call.


Explicit-deregistration attempt `aka-inactive-deregister-20260921T221955392251Z`
passed with cleanup. UE1's Contact disappeared after 86.296 seconds; its exact
IMS-IP/SIP-port UDP bind remained present before and after UE2's call. Caller
AKA/Cx passed, S-CSCF returned 404, the caller ACK matched that transaction,
the old callee received no INVITE, and no relay session remained.

First passive attempt `aka-inactive-expire-20260921T222216552237Z` remains
FAIL/cleanup PASS. Registrar parsing rejected the negative remaining expiry
returned by `ulscscf.showimpu`; no rejected-call acceptance was reached. The
parser now accepts signed remaining seconds while still rejecting malformed
records. Positive registration checks reject zero/negative expiry. Passive
call rejection and eventual physical deletion are now separate observations.
Pinned Kamailio's passive cleanup can take four 90-second timer passes; the
physical deletion wait has a separate 390-second bound, with a live old socket.


Passive attempt `aka-inactive-expire-20260921T222602591300Z` remains
FAIL/cleanup PASS and exposed a real stale-route defect. UE2 had no positive
remaining registration lifetime, yet its old listener received the INVITE.
S-CSCF `lookup()` reused the last invalid Contact after exhausting its scan.
The unanswered branch produced 408; I-CSCF then returned 500 after exhausting
its alternative S-CSCF list. This is not accepted unregistered-call behavior.
The exact failure and private CSCF/HSS logs are retained. A derived S-CSCF
image fixes the exhausted-iterator guard; its accepted scope is recorded below.


Passive-expiry attempt `aka-inactive-expire-20260921T223528557343Z` passed
with cleanup on the derived S-CSCF image. UE2 Contact lifetime fell from 29
to zero seconds while the record remained present. UE1 completed fresh AKA,
then received 404 and sent a matching ACK. The old UE2 listener retained its
exact UDP bind and received no INVITE. Physical removal was observed later,
264.708 seconds after the initial observation; it is not immediate deletion.
Both ordinary clients were restored. The before/after runtime fingerprints
match the deployed image and patched registrar module.

This closes the tested passive-expiry rejection slice, alongside the earlier
explicit-deregistration refusal. It does not close IP change, replay/SQN/AUTS,
protected Gm, policy/QoS or the complete lifecycle matrix. The preceding failed
runs remain FAIL. Build and deployment provenance is in
[kamailio-scscf-provenance.md](kamailio-scscf-provenance.md).


Post-patch continuous AKA call regressions passed with cleanup in both directions:
`aka-call-20260921T224222548781Z` (UE1 caller) and
`aka-call-20260921T224428323334Z` (UE2 caller). The gates checked fresh AKA/Cx,
SIP dialog, opposite-source audio in both receiver WAVs, relay deletion and
restoration of ordinary clients. Full offline quality passed with 164 tests.


## Real PDU address recovery, 2026-09-22

Stale UERANSIM CLI records reused PID 13 after earlier container restarts but
pointed to dead UDP ports. Repair `ue-cli-repair-20260921T225322Z` matched each
current nr-ue process/start time and owned loopback socket, quarantined two stale
records per UE without restarting either UE, then successfully read and parsed
both live PDU lists. Originals remain in in-container quarantine directories;
receipts are private. CLI discovery behavior was checked against the
[upstream v3.2.6 source](https://github.com/aligungr/UERANSIM/blob/v3.2.6/src/cli.cpp).

`pdu-recovery-20260921T225423229625Z` passed with cleanup: UE1 released its IMS
PSI 2 and automatically established it with IPv4 10.46.0.30 instead of
10.46.0.28. UE logs contain the release request, received release command,
local release and successful new establishment. TUN ifindex and normal SIP
process start changed; source routes and fresh REGISTER 200 recovered.
UE1 internet PDU and the sampled UE2 PDU/routes/SIP process stayed unchanged.
Full offline checks passed with 175 tests.

The accepted scope is access recovery and fresh REGISTER 200. It is not full
Digest/AKA proof, a PFCP wire verdict, or old-Contact replacement. The latter
requires explicit removal or expiry and call evidence in the same IMS epoch;
a later call gate's S-CSCF restart cannot prove that property.


After PDU recovery, fresh continuous AKA call `aka-call-20260921T225453936104Z`
(UE2 caller, UE1 callee on its changed address) passed with cleanup. It checked
AKA/Cx, SIP dialog and opposite-source receiver audio on both legs. This was a
separate run with a restarted S-CSCF; it confirms the new PDU path can carry
a fresh AKA voice call, not continuity or stale-Contact removal across release.
