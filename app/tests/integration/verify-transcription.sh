#!/usr/bin/env bash
# Услуга 1004, режим baseline: уведомление о записи, русская речь -> Whisper ->
# Qwen-нормализация (без междометий и повторов) -> приватные WAV и transcript.txt
# в local/private/recordings. Выводятся только метаданные, не текст.
# Без -e: сбой одной команды даёт строку FAIL, а не обрыв без итога.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cleanup() {
    pjsua lab-sipue1 'cd\n1\n4\n' >/dev/null 2>&1 || true
    hangup_clients
}
trap cleanup EXIT

check 'запись включена (RECORDING_ENABLED=1)' test "$RECORDING_ENABLED" = 1

# Синтетическая фраза с заиканиями: промпт обязан убрать мусор и сохранить факты.
probe=$(docker exec lab-ai-worker python -c '
import json, os, re, urllib.request
source = "А... ну... я, я хотел, хотел сказать, что, э-э, встреча будет в пять часов. Но... а... лучше в шесть."
body = json.dumps({"model": os.environ["LLM_MODEL"], "stream": False, "messages": [
    {"role": "system", "content": os.environ["LLM_TRANSCRIPTION_PROMPT"]},
    {"role": "user", "content": f"Вход: «{source}»\nВыход:"}],
    "options": {"temperature": 0, "num_predict": int(os.environ["LLM_NORMALIZATION_MAX_TOKENS"])}}).encode()
request = urllib.request.Request(os.environ["LLM_URL"], body, {"Content-Type": "application/json"})
reply = json.load(urllib.request.urlopen(request, timeout=float(os.environ["LLM_TIMEOUT_SECONDS"])))["message"]["content"]
dirty = re.search(r"(?iu)а\.\.\.|но\.\.\.|э-э|\bну\b|\bя\s*,\s*я\b|\bхотел\s*,\s*хотел\b", reply)
print(json.dumps({"clean": not dirty, "meaning": all(w in reply.casefold() for w in ("встреча", "пять", "шесть"))}))')
check 'нормализация убрала междометия и повторы' test "$(json_field clean <<<"$probe")" = True
check 'нормализация сохранила факты' test "$(json_field meaning <<<"$probe")" = True

check 'тестовые клиенты зарегистрированы' fresh_clients
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
since_epoch=$(date +%s)
pjsua lab-sipue1 "m\nsip:${VOICE_TRANSCRIBER_MSISDN}@${IMS_DOMAIN}\n"
call_id=$(wait_call_id '.*AS terminated INVITE for voice agent call_id=\([^ ]*\) service=transcribe.*' "$since")
check 'диалог с услугой записи установлен' test -n "$call_id"
deadline=$((SECONDS + 20))
until docker logs lab-voice-agent --since "$since" 2>&1 |
    grep -q "VOICE tts call_id=$call_id reason=greeting state=sent" || ((SECONDS > deadline)); do
    sleep 1
done
check 'уведомление о записи прозвучало' grep -q "VOICE tts call_id=$call_id reason=greeting state=sent" \
    <<<"$(docker logs lab-voice-agent --since "$since" 2>&1)"

pjsua lab-sipue1 'cc\n1\n4\n'
sleep "$((AI_UTTERANCE_MAX_SECONDS + 1))"
pjsua lab-sipue1 'cd\n1\n4\n'

summary='{}'
deadline=$((SECONDS + 30))
while ((SECONDS < deadline)); do
    summary=$(service_get lab-ai-worker AI_WORKER_PORT /events | python3 -c '
import json, sys
events = [e for e in json.load(sys.stdin).get("events", [])
          if sys.argv[1] in e.get("call_ids", []) and e.get("processed_at", 0) >= float(sys.argv[2])
          and e.get("service_mode") == "transcribe" and e.get("recording_saved")]
print(json.dumps(max(events, default={}, key=lambda e: (bool(e.get("normalization_applied")),
                                                         e.get("normalized_transcript_chars", 0)))))' \
        "$call_id" "$since_epoch")
    [[ -n "$(json_field recording_session_id <<<"$summary")" ]] && break
    sleep 1
done
field() { json_field "$1" <<<"$summary"; }
session=$(field recording_session_id)

check 'создана приватная сессия записи' test -n "$session"
check 'распознан русский текст' test "$(field transcript_cyrillic_chars)" -gt 0
check 'язык записи — ru' test "$(field detected_language)" = ru
check 'LLM нормализовала расшифровку' test "$(field normalization_applied)" = True
check 'нормализация — закреплённой моделью' test "$(field normalization_llm_model)" = "$LLM_MODEL"
check 'нормализованный текст непустой и русский' test "$(field normalized_transcript_cyrillic_chars)" -gt 0

pjsua lab-sipue1 'ha\n'
# Каталог записи принадлежит uid 65532 (AI Worker): читаем его изнутри контейнера.
in_worker() { docker exec lab-ai-worker sh -c "$1"; }
deadline=$((SECONDS + 15))
until in_worker "test -f $RECORDING_ROOT/$session/completed.json" || ((SECONDS > deadline)); do
    sleep 1
done
check 'метаданные записи закрыты по BYE' in_worker "test -f $RECORDING_ROOT/$session/completed.json"
check 'transcript.txt не пуст' in_worker "test -s $RECORDING_ROOT/$session/transcript.txt"
check 'turn-0001.wav — PCM 8 кГц моно >= 3 с' docker exec lab-ai-worker python -c "
import wave
with wave.open('$RECORDING_ROOT/$session/turn-0001.wav') as w:
    assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 8000)
    assert w.getnframes() >= 24000"
printf 'INFO: session=%s raw_chars=%s normalized_chars=%s retention_days=%s\n' "$session" \
    "$(field transcript_chars)" "$(field normalized_transcript_chars)" "$RECORDING_RETENTION_DAYS"

finish 'OPT-IN RECORDING -> STT -> LLM NORMALIZATION -> TRANSCRIPT'
