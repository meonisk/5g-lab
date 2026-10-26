#!/usr/bin/env bash
# Услуга 1003, режим baseline: русская речь абонента -> RTPengine -> Media
# Adapter -> AI Worker (Whisper STT -> Qwen перевод) -> Voice Agent (английский
# Piper TTS) -> RTP обратно абоненту, несколько реплик в одном вызове.
# В отчёт попадают только метаданные, не текст и не звук.
# Без -e: сбой одной команды даёт строку FAIL, а не обрыв без итога.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cleanup() {
    pjsua lab-sipue1 'cd\n1\n4\n' >/dev/null 2>&1 || true
    hangup_clients
}
trap cleanup EXIT

events=$(service_get lab-ai-worker AI_WORKER_PORT /events)
check 'AI Worker готов (STT загружен)' test "$(json_field status <<<"$events")" = ok
check 'распознавание: faster-whisper' test "$(json_field backend <<<"$events")" = faster-whisper
check 'Ollama содержит закреплённый GGUF' grep -q "sha256-${LLM_GGUF_SHA256}" \
    <<<"$(docker exec lab-llm-worker ollama show "$LLM_MODEL" --modelfile 2>/dev/null)"
check 'тестовые клиенты зарегистрированы' fresh_clients

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
since_epoch=$(date +%s)
pjsua lab-sipue1 "m\nsip:${VOICE_TRANSLATOR_MSISDN}@${IMS_DOMAIN}\n"
call_id=$(wait_call_id '.*AS terminated INVITE for voice agent call_id=\([^ ]*\).*' "$since")
check 'диалог с услугой перевода установлен' test -n "$call_id"

sent_count() {
    docker logs lab-voice-agent --since "$since" 2>&1 |
        grep -c "VOICE tts call_id=$call_id reason=$1 state=sent.*voice=$2" || true
}
deadline=$((SECONDS + 15))
until (($(sent_count greeting "$TTS_VOICE") > 0)) || ((SECONDS > deadline)); do sleep 1; done
check 'русское приветствие прозвучало до речи абонента' test "$(sent_count greeting "$TTS_VOICE")" -gt 0

# В PJSUA порт 1 — проигрыватель WAV, порт 4 — активный вызов. Речь подаётся
# ограниченной репликой и отключается, чтобы ответ агента не перебивался.
for turn in $(seq 1 "$AI_MIN_REPLIES_FOR_SMOKE"); do
    pjsua lab-sipue1 'cc\n1\n4\n'
    sleep "$((AI_UTTERANCE_MAX_SECONDS + 1))"
    pjsua lab-sipue1 'cd\n1\n4\n'
    deadline=$((SECONDS + 30))
    until (($(sent_count llm_reply "$TTS_TRANSLATION_VOICE") >= turn)) || ((SECONDS > deadline)); do
        sleep 1
    done
    check "реплика $turn: перевод вернулся по RTP" \
        test "$(sent_count llm_reply "$TTS_TRANSLATION_VOICE")" -ge "$turn"
done

# Лучшее событие этого вызова: самые длинные звук и текст среди доставленных.
summary=$(service_get lab-ai-worker AI_WORKER_PORT /events | python3 -c '
import json, sys
call_id, since, voice, min_latin, max_cyrillic = sys.argv[1:]
events = [e for e in json.load(sys.stdin).get("events", [])
          if call_id in e.get("call_ids", []) and e.get("processed_at", 0) >= float(since)]
delivered = [e for e in events if e.get("reply_delivered")]
english = [e for e in delivered if e.get("reply_voice") == voice
           and e.get("llm_response_latin_chars", 0) >= int(min_latin)
           and e.get("llm_response_cyrillic_chars", 0) <= int(max_cyrillic)]
best = max(english or delivered or events, default={},
           key=lambda e: (e.get("audio_duration_seconds", 0), e.get("transcript_chars", 0)))
best.update(delivered_replies=len(delivered), english_replies=len(english))
print(json.dumps(best))' "$call_id" "$since_epoch" "$TTS_TRANSLATION_VOICE" \
    "$TRANSLATION_MIN_LATIN_CHARS" "$TRANSLATION_MAX_CYRILLIC_CHARS")
field() { json_field "$1" <<<"$summary"; }

check 'звук PCMU декодирован (>= 3 с)' python3 -c "assert float('$(field audio_duration_seconds)' or 0) >= 3"
check 'STT распознал русский текст' test "$(field transcript_cyrillic_chars)" -gt 0
check 'язык определён как ru' test "$(field detected_language)" = ru
check 'в AI попал только звук абонента' grep -Eq '^caller_to_(core|agent)$' <<<"$(field direction)"
check 'выбран режим translate' test "$(field service_mode)" = translate
check 'ответ доставлен английским голосом' test "$(field reply_voice)" = "$TTS_TRANSLATION_VOICE"
check "доставлено реплик >= $AI_MIN_REPLIES_FOR_SMOKE" test "$(field delivered_replies)" -ge "$AI_MIN_REPLIES_FOR_SMOKE"
check 'все реплики прошли проверку языка (EN)' test "$(field english_replies)" -ge "$AI_MIN_REPLIES_FOR_SMOKE"
printf 'INFO: backend=%s stt_ms=%s llm_ms=%s audio_s=%s replies=%s\n' "$(field backend_id)" \
    "$(field processing_ms)" "$(field llm_processing_ms)" "$(field audio_duration_seconds)" \
    "$(field delivered_replies)"

finish 'RU SPEECH -> STT -> EN TRANSLATION -> TTS -> RTP'
