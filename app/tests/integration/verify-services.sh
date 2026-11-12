#!/usr/bin/env bash
# Услуги IMS по профилю абонента (iFC из lab.env, scripts/provision.py):
# 1) SIPUE1 (ru, translate+record) -> SIPUE2 (en): B2BUA translate AS, перевод в обе
#    стороны через MRF, уведомление и запись обеих сторон в один transcript.txt;
# 2) SIPUE2 -> *SIPUE1: разовый перевод en-ru без записи;
# 3) SIPUE2 -> SIPUE1: обычный звонок без MRF, только наблюдение;
# 4) SIP AS остановлен: звонок проходит (DefaultHandling SESSION_CONTINUED).
# После изменения услуг: python3 scripts/provision.py --apply && docker restart lab-scscf.
# Печатаются только Call-ID и метаданные, не текст. Без -e: сбой — строка FAIL.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

as_stopped=0
cleanup() {
    hangup_clients
    if ((as_stopped)); then docker start lab-sip-as >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
as_log() { docker logs lab-sip-as --since "$1" 2>&1; }
rtp_info() {
    docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" \
        call "$1" info 2>&1 || true
}
# Ждать строку (grep -E) в журнале контейнера начиная с момента since.
wait_for() {
    local container=$1 pattern=$2 since=$4 deadline=$((SECONDS + $3))
    while ((SECONDS < deadline)); do
        log_has "$container" "$pattern" "$since" && return 0
        sleep 1
    done
    return 1
}
absent() { ! grep -Eq -- "$1" <<<"$2"; }
# Распознанные реплики ноги в AI Worker: "<всего> <с кириллицей>".
leg_languages() {
    service_get lab-ai-worker AI_WORKER_PORT /events | python3 -c '
import json, sys
events = [e for e in json.load(sys.stdin).get("events", [])
          if sys.argv[1] in e.get("call_ids", []) and e.get("processed_at", 0) >= float(sys.argv[2])
          and e.get("transcript_chars", 0) > 0]
print(len(events), sum(1 for e in events if e.get("transcript_cyrillic_chars", 0) > 0))' "$1" "$2"
}
# Проигрыватель WAV диалога -> последний вызов в конференц-мосту PJSUA.
connect_playback() {
    local client=$1 rows player call
    pjsua "$client" 'cl\n'
    sleep 1
    rows=$(docker logs "$client" 2>&1 | grep -E '^ *Port #')
    player=$(grep '\.wav' <<<"$rows" | sed -E 's/^ *Port #0*([0-9]+).*/\1/' | tail -1)
    call=$(grep -E '\] +sip:' <<<"$rows" | sed -E 's/^ *Port #0*([0-9]+).*/\1/' | tail -1)
    [[ -n $player && -n $call ]] && pjsua "$client" "cc\n$player\n$call\n"
}
in_worker() { docker exec lab-ai-worker sh -c "$1"; }

echo "===== 1: SIPUE1 ($SIPUE1_LANGUAGE) -> SIPUE2 ($SIPUE2_LANGUAGE): translate + record ====="
export SIPUE1_PLAYBACK_FILE=$INTERPRETER_DIALOGUE_UE1_FILE
export SIPUE2_PLAYBACK_FILE=$INTERPRETER_DIALOGUE_UE2_FILE SIPUE_AUTO_CONFERENCE=0
check 'тестовые клиенты зарегистрированы (WAV диалога)' fresh_clients
run_since=$(now)
since=$(now)
since_epoch=$(date +%s)
pjsua lab-sipue1 "m\nsip:${SIPUE2_IMSI}@${IMS_DOMAIN}\n"
a=$(wait_call_id '.*AS b2bua leg_b call_id=[^ ]* for call_id=\([^ ]*\).*' "$since")
b=$(wait_call_id '.*AS b2bua leg_b call_id=\([^ ]*\) for call_id=.*' "$since")
printf 'INFO: leg_a=%s leg_b=%s\n' "$a" "$b"
check 'translate AS принял ногу A и создал ногу B' test -n "$a" -a -n "$b"
check 'record AS пометил ногу B (via=translate)' \
    wait_for lab-sip-as "AS record marked call_id=$b via=translate" 15 "$since"
# Call-ID ноги B уникален (b2b-<hex>): достаточно найти его в журнале SIPUE2, без
# привязки к написанию заголовка (Call-ID / Call-Id / i).
check 'SIPUE2 получил INVITE ноги B' wait_for lab-sipue2 "${b:-нет-ноги-B}" 15 "$since"
check 'SIPUE1 получил 200/INVITE' wait_for lab-sipue1 'Response msg 200/INVITE' 30 "$since"
check 'перевод ru-en' wait_for lab-sip-as "AS translate answered call_id=$a leg_b=$b languages=ru-en" \
    10 "$since"
check 'AI Worker: пара ног зарегистрирована' wait_for lab-ai-worker 'AI pair_registered' 10 "$since"
check 'уведомление в ноге A (ru)' \
    wait_for lab-voice-agent "VOICE tts call_id=$a reason=announcement state=sent.*voice=$TTS_VOICE" \
    30 "$since"
check 'уведомление в ноге B (en)' wait_for lab-voice-agent \
    "VOICE tts call_id=$b reason=announcement state=sent.*voice=$TTS_TRANSLATION_VOICE" 30 "$since"
check 'запись обеих ног начата' wait_for lab-sip-as "AS record started call_id=$a legs=2" 30 "$since"

# Диалог: каждая сторона говорит на своём языке; уведомление уже прозвучало.
connect_playback lab-sipue1
connect_playback lab-sipue2
check 'перевод SIPUE1 доставлен в ногу B английским голосом' wait_for lab-voice-agent \
    "VOICE tts call_id=$b reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" 180 "$since"
check 'перевод SIPUE2 доставлен в ногу A русским голосом' wait_for lab-voice-agent \
    "VOICE tts call_id=$a reason=llm_reply state=sent.*voice=$TTS_VOICE" 180 "$since"

leg_a_rtp=$(rtp_info "$a")
leg_b_rtp=$(rtp_info "$b")
check 'RTPengine: нога A — SIPUE1 без SIPUE2' eval \
    'grep -q "$SIPUE1_IP" <<<"$leg_a_rtp" && absent "$SIPUE2_IP" "$leg_a_rtp"'
check 'RTPengine: нога B — SIPUE2 без SIPUE1' eval \
    'grep -q "$SIPUE2_IP" <<<"$leg_b_rtp" && absent "$SIPUE1_IP" "$leg_b_rtp"'
read -r b_total b_cyrillic <<<"$(leg_languages "$b" "$since_epoch")"
printf 'INFO: leg_b utterances=%s cyrillic=%s\n' "${b_total:-0}" "${b_cyrillic:-0}"
check 'нога B: речь SIPUE2 распознана' test "${b_total:-0}" -gt 0
check 'нога B: русская речь SIPUE1 в неё не попала' test "${b_cyrillic:-1}" = 0

pjsua lab-sipue1 'ha\n'
check 'B2BUA закрыл обе ноги по BYE со стороны A' \
    wait_for lab-sip-as "AS b2bua ended call_id=$a by=a" 15 "$since"
check 'SIPUE2: BYE ноги B дошёл' wait_for lab-sipue2 'DISCONNECTED' 15 "$since"
session=$(printf '%s' "$a" | sha256sum | cut -c1-20)
check 'AI Worker: запись закрыта после обеих ног' \
    wait_for lab-ai-worker "AI recording_finalized session=$session" 30 "$since"
check 'transcript.txt: реплики звонящего' \
    in_worker "grep -q '^\[caller/' $RECORDING_ROOT/$session/transcript.txt"
check 'transcript.txt: реплики вызываемого' \
    in_worker "grep -q '^\[callee/' $RECORDING_ROOT/$session/transcript.txt"
printf 'INFO: session=%s\n' "$session"
sleep 2

echo "===== 2: SIPUE2 -> *SIPUE1: разовый перевод en-ru без записи ====="
since=$(now)
pjsua lab-sipue2 "m\nsip:*${SIPUE1_IMSI}@${IMS_DOMAIN}\n"
check 'SIPUE2 получил 200/INVITE' wait_for lab-sipue2 'Response msg 200/INVITE' 30 "$since"
check 'перевод en-ru' wait_for lab-sip-as 'AS translate answered call_id=[^ ]+ leg_b=[^ ]+ languages=en-ru' \
    10 "$since"
check 'без записи: record AS не участвует' absent 'AS record (marked|started)' "$(as_log "$since")"
pjsua lab-sipue2 'ha\n'
check 'SIPUE1: BYE дошёл' wait_for lab-sipue1 'DISCONNECTED' 15 "$since"
sleep 2

echo "===== 3: SIPUE2 -> SIPUE1: обычный звонок без MRF ====="
since=$(now)
pjsua lab-sipue2 "m\nsip:${SIPUE1_IMSI}@${IMS_DOMAIN}\n"
plain=$(wait_call_id '.*AS observed INVITE call_id=\([^ ]*\).*' "$since")
check 'SIPUE2 получил 200/INVITE' wait_for lab-sipue2 'Response msg 200/INVITE' 30 "$since"
check 'numbers AS наблюдает звонок' test -n "$plain"
check 'B2BUA не создавал ногу B' absent 'AS b2bua leg_b' "$(as_log "$since")"
plain_rtp=$(rtp_info "$plain")
check 'RTPengine: медиа обеих сторон в одном звонке' eval \
    'grep -q "$SIPUE1_IP" <<<"$plain_rtp" && grep -q "$SIPUE2_IP" <<<"$plain_rtp"'
pjsua lab-sipue2 'ha\n'
sleep 2

echo "===== 4: SIP AS остановлен: SIPUE1 -> SIPUE2 без услуг ====="
docker stop -t 1 lab-sip-as >/dev/null
as_stopped=1
since=$(now)
pjsua lab-sipue1 "m\nsip:${SIPUE2_IMSI}@${IMS_DOMAIN}\n"
# S-CSCF ждёт каждый AS цепочки до fr_timer и продолжает (DefaultHandling 0).
check 'звонок соединился без SIP AS (SESSION_CONTINUED)' \
    wait_for lab-sipue1 'Response msg 200/INVITE' 60 "$since"
pjsua lab-sipue1 'ha\n'
docker start lab-sip-as >/dev/null
as_stopped=0

((fail)) && sip_diag "$run_since"
finish 'IMS SERVICES: TRANSLATE + RECORD + STAR + PLAIN + AS DOWN'
