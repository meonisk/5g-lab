#!/usr/bin/env bash
# Шаги 4–6 обычного вызова: INVITE lab-sipue1 -> lab-sipue2 через P/S-CSCF,
# S-CSCF вызывает SIP AS по iFC, RTPengine держит медиа обеих сторон, Media
# Adapter передаёт звук в AI Worker. При остановленном AI Worker RTP продолжается
# (fail-open). На время проверки AI Worker останавливается: не запускайте во
# время чужих звонков через AI.
# Без -e: сбой одной команды даёт строку FAIL, а не обрыв без итога.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

worker_stopped=0
cleanup() {
    if ((worker_stopped)); then docker start lab-ai-worker >/dev/null 2>&1 || true; fi
    hangup_clients
}
trap cleanup EXIT

rtp_packets() {
    docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" \
        call "$1" info 2>&1 || true
}
packet_sum() {
    awk '/Port / {for(i=1;i<=NF;i++) if($i=="p,") sum+=$(i-1)} END {print sum+0}'
}

check 'тестовые клиенты зарегистрированы' fresh_clients
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
pjsua lab-sipue1 "m\nsip:${SIPUE2_IMSI}@${IMS_DOMAIN}\n"
call_id=$(wait_call_id '.*AS observed INVITE call_id=\([^ ]*\).*' "$since")
sleep 4

caller_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
callee_logs=$(docker logs lab-sipue2 --since "$since" 2>&1)
check 'вызывающий получил 200/INVITE' grep -q 'Response msg 200/INVITE' <<<"$caller_logs"
check 'вызываемый получил INVITE через IMS' grep -q 'Request msg INVITE' <<<"$callee_logs"
check 'S-CSCF вызвал SIP AS по iFC (ISC)' test -n "$call_id"

call_info=$(rtp_packets "$call_id")
check 'RTPengine: медиа вызывающего' grep -q "$SIPUE1_IP" <<<"$call_info"
check 'RTPengine: медиа вызываемого' grep -q "$SIPUE2_IP" <<<"$call_info"
check 'AI Worker получил окна звука этого вызова' \
    grep -q "AI stream_received .*calls=.*$call_id" <<<"$(docker logs lab-ai-worker --since "$since" 2>&1)"
before=$(packet_sum <<<"$call_info")

# Fail-open: остановка AI не должна прерывать разговор абонентов.
docker stop -t 1 lab-ai-worker >/dev/null
worker_stopped=1
outage_since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sleep 7
after=$(rtp_packets "$call_id" | packet_sum)
printf 'INFO: RTP-пакетов до остановки AI=%s, после=%s\n' "$before" "$after"
check 'счётчики RTP растут при остановленном AI' test "$after" -gt "$before"
check 'Media Adapter сообщает fail-open' grep -q 'AI unavailable (media relay unaffected)' \
    <<<"$(docker logs lab-media-adapter --since "$outage_since" 2>&1)"
docker start lab-ai-worker >/dev/null
worker_stopped=0

finish 'IMS CALL + AS + RTPENGINE + AI FAIL-OPEN'
