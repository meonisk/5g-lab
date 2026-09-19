#!/usr/bin/env bash
# Phase 4E acceptance: a registered IMS UE calls the env-defined service
# number, the SIP AS terminates the dialog, and the Voice Agent exchanges RTP
# through RTPengine.  The test uses only app/config/lab.env topology and identities.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../scripts" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

fail=0
check() {
    local label=$1; shift
    if "$@"; then printf 'PASS: %s\n' "$label"; else printf 'FAIL: %s\n' "$label"; fail=1; fi
}

cleanup() {
    docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
}
trap cleanup EXIT

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" terminate all >/dev/null 2>&1 || true
sleep 1
docker exec lab-sipue1 sh -lc "printf 'm\\nsip:${VOICE_AGENT_MSISDN}@${IMS_DOMAIN}\\n' > /tmp/pjsua-control"

deadline=$((SECONDS + 25))
call_id=''
while ((SECONDS < deadline)); do
    as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
    call_id=$(sed -n 's/.*AS terminated INVITE for voice agent call_id=\([^ ]*\).*/\1/p' <<<"$as_logs" | tail -1)
    ue_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
    voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)
    [[ -n "$call_id" && "$as_logs" == *"AS received ACK for voice agent call_id=$call_id"* &&
       "$voice_logs" == *"VOICE tts call_id=$call_id reason=greeting"* ]] && break
    sleep 1
done

# PJSUA can retain console output until its FIFO receives another command.
# A read-only state dump flushes the 200/SDP evidence without changing the call.
docker exec lab-sipue1 sh -lc 'printf "d\n" > /tmp/pjsua-control' >/dev/null
sleep 1
ue_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)

check 'caller received 200/INVITE from service number' grep -q 'Response msg 200/INVITE' <<<"${ue_logs:-}"
check 'caller negotiated PCMU media' grep -q 'Audio updated, stream #0: PCMU (sendrecv)' <<<"${ue_logs:-}"
check 'SIP AS terminated the IMS dialog' test -n "$call_id"
check 'ACK traversed IMS back to SIP AS' grep -q "AS received ACK for voice agent call_id=$call_id" <<<"${as_logs:-}"
check 'Voice Agent synthesized the greeting' grep -q "VOICE tts call_id=$call_id reason=greeting" <<<"${voice_logs:-}"

call_info=$(docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" call "$call_id" info 2>&1 || true)
ue_ip=$(docker exec lab-ue1 ip route get "$PCSCF_IP" | sed -n 's/.* src \([^ ]*\).*/\1/p')
check 'RTPengine has caller IMS-PDU endpoint' grep -q "$ue_ip" <<<"$call_info"
check 'RTPengine has Voice Agent endpoint' grep -q "$VOICE_AGENT_IP" <<<"$call_info"

deadline=$((SECONDS + 12))
received=0
while ((SECONDS < deadline)); do
    # The Voice Agent image is Debian for Piper/ONNX and intentionally does not
    # add a second HTTP client. Python is already its runtime dependency.
    status=$(docker exec lab-voice-agent python -c '
import os, sys, urllib.request
token = open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii").read().strip()
request = urllib.request.Request(
    f"http://127.0.0.1:{sys.argv[1]}/status",
    headers={"Authorization": f"Bearer {token}"},
)
print(urllib.request.urlopen(request, timeout=2).read().decode())
' "$VOICE_AGENT_HTTP_PORT")
    received=$(python -c 'import json,sys; d=json.load(sys.stdin); print(d["calls"].get(sys.argv[1],{}).get("received_packets",0))' "$call_id" <<<"$status")
    ((received > 0)) && break
    sleep 1
done
printf 'INFO: Voice Agent received RTP packets=%s\n' "$received"
check 'Voice Agent receives caller RTP through IMS/RTPengine' test "$received" -gt 0

docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control'
deadline=$((SECONDS + 10))
while ((SECONDS < deadline)); do
    # The Call-ID is unique, so avoid Docker's second-resolution --since edge
    # where a BYE emitted in the same second as the timestamp can be excluded.
    as_end=$(docker logs lab-sip-as --since 10m 2>&1)
    voice_end=$(docker logs lab-voice-agent --since 10m 2>&1)
    [[ "$as_end" == *"AS ended voice agent call_id=$call_id method=BYE"* &&
       "$voice_end" == *"VOICE call_ended call_id=$call_id"* ]] && break
    sleep 1
done
check 'BYE ended SIP AS dialog' grep -q "AS ended voice agent call_id=$call_id method=BYE" <<<"${as_end:-}"
check 'BYE released Voice Agent session' grep -q "VOICE call_ended call_id=$call_id" <<<"${voice_end:-}"

printf 'PHASE 4E VOICE AGENT (DOCKER): %s\n' "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
