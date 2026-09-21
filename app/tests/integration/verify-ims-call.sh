#!/usr/bin/env bash
# Phase 4C/4D acceptance: IMS call, RTPengine media, iFC-triggered AS,
# normalized media delivery, AI inference, and fail-open behavior.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../scripts" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

fail=0
check() {
    local label=$1; shift
    if "$@"; then printf 'PASS: %s\n' "$label"; else printf 'FAIL: %s\n' "$label"; fail=1; fi
}

worker_stopped=0
cleanup() {
    if ((worker_stopped)); then docker start lab-ai-worker >/dev/null 2>&1 || true; fi
    docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
}
trap cleanup EXIT

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-sipue2 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" terminate all >/dev/null 2>&1 || true
sleep 1
docker exec lab-sipue1 sh -lc 'printf "m\nsip:${UE2_IMSI}@${IMS_DOMAIN}\n" > /tmp/pjsua-control'

deadline=$((SECONDS + 25))
call_id=''
while ((SECONDS < deadline)); do
    as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
    call_id=$(sed -n 's/.*AS observed INVITE call_id=\([^ ]*\).*/\1/p' <<<"$as_logs" | tail -1)
    ue1_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
    [[ -n "$call_id" && "$ue1_logs" == *'Response msg 200/INVITE'* ]] && break
    sleep 1
done

ue2_logs=$(docker logs lab-sipue2 --since "$since" 2>&1)
check 'caller received 200/INVITE' grep -q 'Response msg 200/INVITE' <<<"${ue1_logs:-}"
check 'callee received INVITE over IMS path' grep -q 'Request msg INVITE' <<<"$ue2_logs"
check 'S-CSCF triggered SIP AS through iFC/ISC' test -n "$call_id"

sleep 4
call_info=$(docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" call "$call_id" info 2>&1 || true)
ue1_ip=$(docker exec lab-ue1 ip route get "$PCSCF_IP" | sed -n 's/.* src \([^ ]*\).*/\1/p')
ue2_ip=$(docker exec lab-ue2 ip route get "$PCSCF_IP" | sed -n 's/.* src \([^ ]*\).*/\1/p')
check 'RTPengine has caller IMS-PDU stream' grep -q "$ue1_ip" <<<"$call_info"
check 'RTPengine has callee IMS-PDU stream' grep -q "$ue2_ip" <<<"$call_info"
before=$(awk '/Port / {for(i=1;i<=NF;i++) if($i=="p,") sum+=$(i-1)} END {print sum+0}' <<<"$call_info")

ai_logs=$(docker logs lab-ai-worker --since "$since" 2>&1)
check 'AI Worker accepted an RTP observation window for this IMS call' \
    grep -q "AI stream_received .*calls=.*$call_id" <<<"$ai_logs"

docker stop -t 1 lab-ai-worker >/dev/null
worker_stopped=1
outage_since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sleep 7
after_info=$(docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" call "$call_id" info 2>&1 || true)
after=$(awk '/Port / {for(i=1;i<=NF;i++) if($i=="p,") sum+=$(i-1)} END {print sum+0}' <<<"$after_info")
adapter_logs=$(docker logs lab-media-adapter --since "$outage_since" 2>&1)
printf 'INFO: RTP packets before AI outage=%s after=%s\n' "$before" "$after"
check 'RTP packet counters advance while AI is stopped' test "$after" -gt "$before"
check 'Media Adapter reports fail-open AI outage' grep -q 'AI unavailable (media relay unaffected)' <<<"$adapter_logs"

docker start lab-ai-worker >/dev/null
worker_stopped=0
printf 'PHASE 4C/4D (DOCKER): %s\n' "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
