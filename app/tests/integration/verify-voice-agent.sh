#!/usr/bin/env bash
# Голосовой сервис на номере VOICE_AGENT_MSISDN (по умолчанию совпадает с 1003):
# SIP AS сам завершает диалог (200/ACK), Voice Agent синтезирует приветствие и
# обменивается RTP с абонентом через RTPengine в PCMU/8000, BYE освобождает
# сессии AS и Voice Agent. Перевод речи здесь не проверяется.
# Без -e: сбой одной команды даёт строку FAIL, а не обрыв без итога.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
trap hangup_clients EXIT

check 'тестовые клиенты зарегистрированы' fresh_clients
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
pjsua lab-sipue1 "m\nsip:${VOICE_AGENT_MSISDN}@${IMS_DOMAIN}\n"
call_id=$(wait_call_id '.*AS terminated INVITE for voice agent call_id=\([^ ]*\).*' "$since")

deadline=$((SECONDS + 20))
while ((SECONDS < deadline)); do
    docker logs lab-voice-agent --since "$since" 2>&1 |
        grep -q "VOICE tts call_id=$call_id reason=greeting" && break
    sleep 1
done
# PJSUA может держать вывод в буфере до следующей команды; d — безопасный дамп.
pjsua lab-sipue1 'd\n'
sleep 1
caller_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)

check 'SIP AS завершил диалог на номере услуги' test -n "$call_id"
check 'вызывающий получил 200/INVITE' grep -q 'Response msg 200/INVITE' <<<"$caller_logs"
check 'согласован PCMU' grep -q 'Audio updated, stream #0: PCMU (sendrecv)' <<<"$caller_logs"
check 'ACK дошёл через IMS до SIP AS' grep -q "AS received ACK for voice agent call_id=$call_id" <<<"$as_logs"
check 'Voice Agent синтезировал приветствие' grep -q "VOICE tts call_id=$call_id reason=greeting" <<<"$voice_logs"

call_info=$(docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" \
    call "$call_id" info 2>&1 || true)
check 'RTPengine: медиа абонента' grep -q "$SIPUE1_IP" <<<"$call_info"
check 'RTPengine: медиа Voice Agent' grep -q "$VOICE_AGENT_IP" <<<"$call_info"

received=0
deadline=$((SECONDS + 12))
while ((SECONDS < deadline)); do
    received=$(service_get lab-voice-agent VOICE_AGENT_HTTP_PORT /status | python3 -c '
import json, sys
print(json.load(sys.stdin)["calls"].get(sys.argv[1], {}).get("received_packets", 0))' "$call_id")
    ((received > 0)) && break
    sleep 1
done
printf 'INFO: Voice Agent получил RTP-пакетов: %s\n' "$received"
check 'Voice Agent получает RTP абонента' test "$received" -gt 0

pjsua lab-sipue1 'ha\n'
deadline=$((SECONDS + 10))
while ((SECONDS < deadline)); do
    # Call-ID уникален: читаем с запасом, чтобы BYE в ту же секунду не потерялся.
    as_end=$(docker logs lab-sip-as --since 10m 2>&1)
    voice_end=$(docker logs lab-voice-agent --since 10m 2>&1)
    [[ "$as_end" == *"AS ended voice agent call_id=$call_id method=BYE"* &&
        "$voice_end" == *"VOICE call_ended call_id=$call_id"* ]] && break
    sleep 1
done
check 'BYE завершил диалог SIP AS' grep -q "AS ended voice agent call_id=$call_id method=BYE" <<<"$as_end"
check 'BYE освободил сессию Voice Agent' grep -q "VOICE call_ended call_id=$call_id" <<<"$voice_end"

finish 'VOICE AGENT SERVICE NUMBER'
