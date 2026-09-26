# Continuous SIPp AKA and call gate

Status: UE1→UE2 AKA registration, SIP call, two-way PCMU transport, and cleanup
passed in `local/private/aka-call-20260921T213917277478Z`. The earlier
`aka-call-20260921T213538181631Z` run failed its dialog Via verifier despite
passing both endpoint audio checks and Cx; its cleanup passed. UE2→UE1 passed
in `aka-call-20260921T214530534792Z`, including cleanup. These are virtual-stand results, not native handset playback or ISIM
security evidence. The source archive is SHA-256 pinned in
`sipp-aka-provenance.md`.

`app/tests/integration/aka_call_scenarios.py::render_pair(private_dir, settings)`
produces caller main XML, callee main XML, and callee OOC XML. It reuses the
existing AKA registration template, captures Service-Route from its 200, and
keeps K/OPc/AMF only in the private rendered main files. The caller's second
call waits `SIP_AKA_INVITE_DELAY_MS` (default 5000), then INVITEs with a new
Call-ID, PCMU/8000 SDP, learned Service-Route, and fixed
`SIP_AKA_MEDIA_PORT` (default 4000); it waits `SIP_AKA_CALL_SECONDS` (default
20) before BYE. The callee's second main call pauses for call duration plus
40 seconds while OOC handles INVITE/ACK/BYE. These values are bounded at
render time. `verify_aka_call.py` starts a separate RTP sender/receiver helper
in each UE's network namespace, reads the negotiated remote SDP before opening
media, and writes received UDP RTP as decoded PCM16 WAV. The SIPp XML contains
no external media execution.

## Call-ID and socket decision

Use one SIPp process **per UE**, `-t u1 -users 1 -m 2`, bound to that UE's SIP
address and port. Main-scenario call 1 performs AKA REGISTER. On its 200 OK it
sets a `<User variables="registered" />` value and ends. SIPp then frees user 1
and creates main-scenario call 2 with a new generated Call-ID. The user variable
persists, so the same XML branches into the post-registration path. This avoids
reusing REGISTER's Call-ID for INVITE or choosing the peer's Call-ID artificially.

Source evidence in the [pinned SIPp source](https://github.com/SIPp/sipp/tree/v3.7.7):

- `src/call_generation_task.cpp` computes `users - current_calls`, caps at
  `stop_after` (`-m`), reuses the freed user, and calls `call::add_call`.
- `src/call.cpp` generates a fresh Call-ID per `add_call`, returns the user to
  the free pool on completion, and obtains `userVarMap[userId]` for the next
  call. [SIPp user-variable documentation](https://sipp.readthedocs.io/en/latest/scenarios/variables.html)
  explicitly describes registration state across calls.
- `src/sipp.cpp` documents `-t u1` as one UDP socket. SIPp's
  [conditional branching](https://sipp.readthedocs.io/en/latest/scenarios/cond_branching.html)
  supports a `next`/`test` jump on a user variable.

The caller's second call sends INVITE, then handles provisional/final response,
ACK, a bounded media window, BYE, and final 200. The callee's second main call stays alive
on a finite pause (for example 120 seconds). It loads `-oocsf callee-uas.xml`:
`src/socket.cpp::process_message` finds no listener for the incoming INVITE's
new Call-ID and constructs an automatic out-of-call call with the **same SIPp
socket**. Subsequent ACK/BYE map to that call. `-rxsf` also creates calls for
unknown IDs, but its mixed-mode branch is broader; `-oocsf` is specific to
unexpected requests in client mode. The callee scenario must have been loaded
before REGISTER so there is no rebind interval.

`src/call.cpp` rejects injection-file access from automatic (`-oocsf`) calls.
Keep UAS XML identity-independent: use incoming Via/From/To/Call-ID/CSeq and
SIPp local media keywords, or render any UE-specific fixed values into a
private scenario before starting the process. Keep K/OPc/AMF only in the
private REGISTER scenario; do not pass them on the command line or include
them in traces. The contact in REGISTER must be the listening socket's address
and port, with registration expiry exceeding the bounded call window.

## Implemented scenario control flow

Both rendered main scenarios use the branch below. The complete XML passed
offline SIPp parsing with `-sf ... -m 0` before the live gate.

```xml
<User variables="registered" />
<nop next="2" test="registered" />
<!-- First call: REGISTER; receive 401, send Digest AKAv1-MD5 with
     [authentication ... aka_K=0x... aka_OPc=0x... aka_AMF=0x...]; receive 200. -->
<nop next="19"><action><assignstr assign_to="registered" value="yes" /></action></nop>
<label id="2" />
<!-- Caller: INVITE/ACK/BYE; callee: finite pause while -oocsf handles INVITE. -->
<label id="19" />
```

This excerpt is the branch skeleton; the generated XML contains full SIP
messages. With `-users 1`, the scheduler reuses the user after REGISTER call
completion and generates a fresh Call-ID for INVITE. `-m 2` prevents an
unplanned third main call. The callee's second main call pauses until the
out-of-call dialog completes.

Offline parser invocation used for the rendered files (with synthetic keys):

```text
sipp -sf /scenarios/ue1-caller-main.xml -users 1 -m 0 -t u1 127.0.0.1
sipp -sf /scenarios/ue2-callee-main.xml -oocsf /scenarios/ue2-callee-ooc.xml -users 1 -m 0 -t u1 127.0.0.1
```

The callee `-oocsf` scenario receives INVITE; returns 200 with PCMU/8000 SDP
at its configured media port; receives ACK and BYE; then returns 200. It does
not send 180 in the current gate. SIPp handles signalling; the separate
`aka_media_endpoint.py` helper sends and receives RTP on the negotiated ports.

## Measured acceptance and boundary

`verify_aka_call.py` generates private XML and distinct synthetic PCMU markers,
starts one SIPp process plus one RTP helper in each UE namespace, and checks:

1. Each UE's REGISTER challenge/response reaches 200 on its own process/socket.
2. Caller INVITE Call-ID differs from its REGISTER Call-ID; callee INVITE
   Call-ID differs from its REGISTER Call-ID, and the Contact address/port
   equals the still-listening SIPp socket.
3. Callee `-oocsf` receives INVITE, ACK, and BYE under the INVITE Call-ID;
   both final SIP transactions complete without a new SIPp process.
4. Receive UDP RTP payload 0 at each endpoint, decode it to PCM16/8 kHz WAV,
   and match each received waveform to the *other* UE's marker. Relay counters
   alone cannot establish that result.

The passing UE1→UE2 run reports registration, dialog, endpoint WAV checks, Cx,
and cleanup as PASS. The receiver is a test-owned UDP endpoint and WAV
decoder; there is no audio-device playback, native IMS handset, ISIM, or
IPsec-protected Gm claim. Reverse UE2→UE1 passed independently; see
[status](status.md) for the earlier restoration failure and retry boundary.
