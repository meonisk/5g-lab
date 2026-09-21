#!/usr/bin/env bash
# Prove the live subscriber PCMU -> STT -> LLM -> TTS -> IMS RTP loop.
# No audio, transcript, prompt, or generated response is written to evidence.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../scripts" && pwd)
root=$(cd -- "$script_dir/.." && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

base=(docker compose --env-file "$root/app/config/lab.env" --env-file "$root/local/secrets/ims.env" -f "$root/docker-compose.yml")
fail=0
check() {
    local label=$1; shift
    if "$@"; then printf 'PASS: %s\n' "$label"; else printf 'FAIL: %s\n' "$label"; fail=1; fi
}
cleanup() {
    docker exec lab-sipue1 sh -lc 'printf "cd\n1\n4\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
    docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
}
trap cleanup EXIT

query_events() {
    docker exec lab-ai-worker python -c '
import os, urllib.request
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii").read().strip()
request=urllib.request.Request(
    "http://127.0.0.1:" + os.environ["AI_WORKER_PORT"] + "/events",
    headers={"Authorization": "Bearer " + token})
print(urllib.request.urlopen(request, timeout=3).read().decode())'
}

clear_adapter_sessions() {
    docker exec lab-media-adapter python -c '
import json,os,urllib.parse,urllib.request
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii").read().strip()
base="http://127.0.0.1:"+os.environ["MEDIA_ADAPTER_PORT"]+"/sessions"
headers={"Authorization":"Bearer "+token}
sessions=json.load(urllib.request.urlopen(urllib.request.Request(base,headers=headers),timeout=3))["sessions"]
for call_id in sessions:
    request=urllib.request.Request(base+"/"+urllib.parse.quote(call_id,safe=""),headers=headers,method="DELETE")
    urllib.request.urlopen(request,timeout=3).read()'
}

printf '===== wait for local STT model =====\n'
deadline=$((SECONDS + 180))
status=''
while ((SECONDS < deadline)); do
    status=$(query_events 2>/dev/null || true)
    [[ -n "$status" ]] && [[ $(python -c 'import json,sys; print(json.load(sys.stdin).get("status"))' <<<"$status") == ok ]] && break
    sleep 2
done
check 'faster-whisper model is ready' python -c \
    'import json,sys; assert json.load(sys.stdin)["status"] == "ok"' <<<"$status"
check 'configured backend is live' python -c \
    'import json,sys; assert json.load(sys.stdin)["backend"] == "faster-whisper"' <<<"$status"
llm_source=$(docker exec lab-llm-worker ollama show "$LLM_MODEL" --modelfile 2>/dev/null || true)
check 'pinned Unsloth GGUF is available' grep -q "sha256-${LLM_GGUF_SHA256}" <<<"$llm_source"

"${base[@]}" up -d --no-deps --force-recreate sipue1 >/dev/null
deadline=$((SECONDS + 70))
while ((SECONDS < deadline)); do
    (docker logs lab-sipue1 2>&1 || true) | grep -q 'Response msg 200/REGISTER' && break
    sleep 2
done
check 'fresh translation client registered through IMS' \
    grep -q 'Response msg 200/REGISTER' <<<"$(docker logs lab-sipue1 2>&1 || true)"

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
since_epoch=$(python -c 'import time; print(time.time())')
clear_adapter_sessions
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" terminate all >/dev/null 2>&1 || true
sleep 1
docker exec lab-sipue1 sh -lc "printf 'm\nsip:${VOICE_TRANSLATOR_MSISDN}@${IMS_DOMAIN}\n' > /tmp/pjsua-control"

deadline=$((SECONDS + 25))
call_id=''
while ((SECONDS < deadline)); do
    as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
    call_id=$(sed -n 's/.*AS terminated INVITE for voice agent call_id=\([^ ]*\).*/\1/p' <<<"$as_logs" | tail -1)
    [[ -n "$call_id" ]] && break
    sleep 1
done
check 'voice-agent IMS dialog started' test -n "$call_id"

# PJSUA registers the deterministic Russian WAV as conference port 1; the
# active call is port 4. Each turn connects caller audio for one bounded
# utterance and then disconnects it so the agent can speak without triggering
# barge-in. Both turns retain the same SIP dialog and Call-ID.
deadline=$((SECONDS + 15))
while ((SECONDS < deadline)); do
    voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)
    grep -q "VOICE tts call_id=$call_id reason=greeting state=sent" <<<"$voice_logs" && break
    sleep 1
done
check 'Russian greeting completed before subscriber speech' \
    grep -q "VOICE tts call_id=$call_id reason=greeting state=sent.*voice=$TTS_VOICE" <<<"${voice_logs:-}"

printf '===== process two Russian dialogue turns =====\n'
for turn in $(seq 1 "$AI_MIN_REPLIES_FOR_SMOKE"); do
    docker exec lab-sipue1 sh -lc "printf 'cc\n1\n4\n' > /tmp/pjsua-control"
    python -c 'import sys,time; time.sleep(float(sys.argv[1])+0.5)' "$AI_UTTERANCE_MAX_SECONDS"
    docker exec lab-sipue1 sh -lc "printf 'cd\n1\n4\n' > /tmp/pjsua-control"
    deadline=$((SECONDS + 30))
    while ((SECONDS < deadline)); do
        voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)
        sent=$(grep -c "VOICE tts call_id=$call_id reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" <<<"$voice_logs" || true)
        [[ "$sent" -ge "$turn" ]] && break
        sleep 1
    done
    check "Russian dialogue turn $turn returned through RTP" test "${sent:-0}" -ge "$turn"
done

deadline=$((SECONDS + 30))
summary=''
while ((SECONDS < deadline)); do
    status=$(query_events 2>/dev/null || true)
    if [[ -n "$status" ]]; then
        summary=$(python -c '
import json,sys
data=json.load(sys.stdin); call_id=sys.argv[1]; since=float(sys.argv[2])
matches=[e for e in data.get("events",[]) if call_id in e.get("call_ids",[]) and e.get("processed_at",0)>=since and e.get("audio_duration_seconds",0)>0]
delivered=[e for e in matches if e.get("reply_delivered")]
english=[e for e in delivered if e.get("reply_voice")==sys.argv[3] and e.get("llm_response_latin_chars",0)>=int(sys.argv[4]) and e.get("llm_response_cyrillic_chars",0)<=int(sys.argv[5])]
best=max(english or delivered or matches, key=lambda e:(e.get("audio_duration_seconds",0),e.get("transcript_chars",0)), default={})
out={k:best.get(k) for k in ("backend_id","direction","service_mode","audio_duration_seconds","audio_rms","transcript_chars","transcript_cyrillic_chars","detected_language","processing_ms","llm_model","llm_processing_ms","llm_response_chars","llm_response_cyrillic_chars","llm_response_latin_chars","reply_voice","reply_delivered")}
out["delivered_replies"]=len(delivered)
out["english_replies"]=len(english)
print(json.dumps(out, ensure_ascii=False))' \
            "$call_id" "$since_epoch" "$TTS_TRANSLATION_VOICE" "$TRANSLATION_MIN_LATIN_CHARS" "$TRANSLATION_MAX_CYRILLIC_CHARS" <<<"$status")
        chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_chars") or 0)' <<<"$summary")
        delivered=$(python -c 'import json,sys; print(str(bool(json.load(sys.stdin).get("reply_delivered"))).lower())' <<<"$summary")
        delivered_replies=$(python -c 'import json,sys; print(json.load(sys.stdin).get("delivered_replies") or 0)' <<<"$summary")
        english_replies=$(python -c 'import json,sys; print(json.load(sys.stdin).get("english_replies") or 0)' <<<"$summary")
        [[ "$delivered" == true && "$english_replies" -ge "$AI_MIN_REPLIES_FOR_SMOKE" ]] && break
    fi
    sleep 2
done

[[ -n "$summary" ]] || summary='{}'
audio_seconds=$(python -c 'import json,sys; print(json.load(sys.stdin).get("audio_duration_seconds") or 0)' <<<"$summary")
chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_chars") or 0)' <<<"$summary")
backend_id=$(python -c 'import json,sys; print(json.load(sys.stdin).get("backend_id") or "")' <<<"$summary")
processing_ms=$(python -c 'import json,sys; print(json.load(sys.stdin).get("processing_ms") or 0)' <<<"$summary")
llm_ms=$(python -c 'import json,sys; print(json.load(sys.stdin).get("llm_processing_ms") or 0)' <<<"$summary")
response_chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("llm_response_chars") or 0)' <<<"$summary")
transcript_cyrillic=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_cyrillic_chars") or 0)' <<<"$summary")
response_latin=$(python -c 'import json,sys; print(json.load(sys.stdin).get("llm_response_latin_chars") or 0)' <<<"$summary")
response_cyrillic=$(python -c 'import json,sys; print(json.load(sys.stdin).get("llm_response_cyrillic_chars") or 0)' <<<"$summary")
reply_voice=$(python -c 'import json,sys; print(json.load(sys.stdin).get("reply_voice") or "")' <<<"$summary")
service_mode=$(python -c 'import json,sys; print(json.load(sys.stdin).get("service_mode") or "")' <<<"$summary")
detected_language=$(python -c 'import json,sys; print(json.load(sys.stdin).get("detected_language") or "")' <<<"$summary")
delivered_replies=$(python -c 'import json,sys; print(json.load(sys.stdin).get("delivered_replies") or 0)' <<<"$summary")
english_replies=$(python -c 'import json,sys; print(json.load(sys.stdin).get("english_replies") or 0)' <<<"$summary")
direction=$(python -c 'import json,sys; print(json.load(sys.stdin).get("direction") or "")' <<<"$summary")
delivered=$(python -c 'import json,sys; print(str(bool(json.load(sys.stdin).get("reply_delivered"))).lower())' <<<"$summary")

check 'real PCMU audio was decoded and processed' python -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 3 else 1)' "$audio_seconds"
check 'local semantic STT produced text' test "$chars" -gt 0
check 'Russian STT produced Cyrillic text' test "$transcript_cyrillic" -gt 0
check 'STT result is identified as Russian' test "$detected_language" = ru
check 'result identifies the replaceable backend' grep -q '^faster-whisper:' <<<"$backend_id"
check 'only subscriber-originated audio entered AI' sh -c \
    "test '$direction' = caller_to_core || test '$direction' = caller_to_agent"
check 'local LLM generated and delivered a bounded reply' test "$delivered" = true
check 'LLM reply is non-empty' test "$response_chars" -gt 0
check 'service selected Russian-to-English translation mode' test "$service_mode" = translate
check 'LLM produced an English-only translation' sh -c "test '$response_latin' -ge '$TRANSLATION_MIN_LATIN_CHARS' && test '$response_cyrillic' -le '$TRANSLATION_MAX_CYRILLIC_CHARS'"
check 'translation selected the English TTS voice' test "$reply_voice" = "$TTS_TRANSLATION_VOICE"
check 'multiple dialogue turns were delivered in one IMS call' test "$delivered_replies" -ge "$AI_MIN_REPLIES_FOR_SMOKE"
check 'every required turn passed the output-language barrier' test "$english_replies" -ge "$AI_MIN_REPLIES_FOR_SMOKE"
deadline=$((SECONDS + 20))
voice_logs=''
while ((SECONDS < deadline)); do
    voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)
    [[ $(grep -c "VOICE tts call_id=$call_id reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" <<<"$voice_logs" || true) -ge $AI_MIN_REPLIES_FOR_SMOKE ]] && break
    sleep 1
done
tts_replies=$(grep -c "VOICE tts call_id=$call_id reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" <<<"$voice_logs" || true)
check 'English TTS sent every translation as RTP' test "$tts_replies" -ge "$AI_MIN_REPLIES_FOR_SMOKE"
printf 'INFO: backend=%s language=%s turns=%s audio_seconds=%s stt_ms=%s transcript_chars=%s llm_ms=%s response_chars=%s\n' \
    "$backend_id" "$detected_language" "$delivered_replies" "$audio_seconds" "$processing_ms" "$chars" "$llm_ms" "$response_chars"

printf 'RUSSIAN IMS AUDIO -> ENGLISH TRANSLATION -> TTS -> RTP: %s\n' "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
