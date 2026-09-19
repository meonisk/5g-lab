#!/usr/bin/env bash
# Prove explicit opt-in IMS recording and private Russian transcription.
# The gate prints only metadata and never prints transcript or audio content.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
root=$(cd -- "$script_dir/.." && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

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
import os,urllib.request
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii").read().strip()
request=urllib.request.Request("http://127.0.0.1:"+os.environ["AI_WORKER_PORT"]+"/events",
    headers={"Authorization":"Bearer "+token})
print(urllib.request.urlopen(request,timeout=3).read().decode())'
}

[[ "$RECORDING_ENABLED" == 1 ]] || { echo 'FAIL: recording is not explicitly enabled'; exit 1; }

# Frozen synthetic contract probe: prove that the configured local model and
# prompt remove common disfluencies while retaining the two factual time words.
# Only boolean/count metadata leaves the container.
normalization_probe=$(docker exec lab-ai-worker python -c '
import json,os,re,urllib.request
source="А... ну... я, я хотел, хотел сказать, что, э-э, встреча будет в пять часов. Но... а... лучше в шесть."
body=json.dumps({"model":os.environ["LLM_MODEL"],"stream":False,"messages":[
 {"role":"system","content":os.environ["LLM_TRANSCRIPTION_PROMPT"]},
 {"role":"user","content":f"Вход: «{source}»\nВыход:"}],
 "options":{"temperature":0,"num_predict":int(os.environ["LLM_NORMALIZATION_MAX_TOKENS"])}}).encode()
reply=json.load(urllib.request.urlopen(urllib.request.Request(os.environ["LLM_URL"],body,
 {"Content-Type":"application/json"}),timeout=float(os.environ["LLM_TIMEOUT_SECONDS"]))) ["message"]["content"]
bad=bool(re.search(r"(?iu)а\.\.\.|но\.\.\.|э-э|\bну\b|\bя\s*,\s*я\b|\bхотел\s*,\s*хотел\b",reply))
meaning=all(word in reply.casefold() for word in ("встреча","пять","шесть"))
print(json.dumps({"disfluencies_removed":not bad,"meaning_preserved":meaning,"output_chars":len(reply)}))')
check 'normalization probe removed fillers, repeats, and false starts' python -c \
    'import json,sys; raise SystemExit(0 if json.load(sys.stdin)["disfluencies_removed"] else 1)' <<<"$normalization_probe"
check 'normalization probe preserved factual content' python -c \
    'import json,sys; raise SystemExit(0 if json.load(sys.stdin)["meaning_preserved"] else 1)' <<<"$normalization_probe"

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
since_epoch=$(python -c 'import time; print(time.time())')
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" terminate all >/dev/null 2>&1 || true
sleep 1
docker exec lab-sipue1 sh -lc "printf 'm\nsip:${VOICE_TRANSCRIBER_MSISDN}@${IMS_DOMAIN}\n' > /tmp/pjsua-control"

deadline=$((SECONDS + 25))
call_id=''
while ((SECONDS < deadline)); do
    as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
    call_id=$(sed -n 's/.*AS terminated INVITE for voice agent call_id=\([^ ]*\) service=transcribe.*/\1/p' <<<"$as_logs" | tail -1)
    voice_logs=$(docker logs lab-voice-agent --since "$since" 2>&1)
    [[ -n "$call_id" && "$voice_logs" == *"VOICE tts call_id=$call_id reason=greeting state=sent"* ]] && break
    sleep 1
done
check 'transcription service IMS dialog started' test -n "$call_id"
check 'recording disclosure greeting completed' \
    grep -q "VOICE tts call_id=$call_id reason=greeting state=sent.*voice=$TTS_VOICE" <<<"${voice_logs:-}"

docker exec lab-sipue1 sh -lc "printf 'cc\n1\n4\n' > /tmp/pjsua-control"
python -c 'import sys,time; time.sleep(float(sys.argv[1])+0.5)' "$AI_UTTERANCE_MAX_SECONDS"
docker exec lab-sipue1 sh -lc "printf 'cd\n1\n4\n' > /tmp/pjsua-control"

deadline=$((SECONDS + 30))
summary=''
while ((SECONDS < deadline)); do
    status=$(query_events 2>/dev/null || true)
    if [[ -n "$status" ]]; then
        summary=$(python -c '
import json,sys
d=json.load(sys.stdin); cid=sys.argv[1]; since=float(sys.argv[2])
m=[e for e in d.get("events",[]) if cid in e.get("call_ids",[]) and e.get("processed_at",0)>=since and e.get("service_mode")=="transcribe" and e.get("recording_saved")]
best=max(m,key=lambda e:(bool(e.get("normalization_applied")),e.get("normalized_transcript_chars",0),e.get("transcript_chars",0)),default={})
print(json.dumps({k:best.get(k) for k in ("recording_session_id","recording_saved","recording_turn","audio_duration_seconds","transcript_chars","transcript_cyrillic_chars","detected_language","normalization_applied","normalization_llm_model","normalization_processing_ms","normalized_transcript_chars","normalized_transcript_cyrillic_chars")},ensure_ascii=False))' \
            "$call_id" "$since_epoch" <<<"$status")
        session_id=$(python -c 'import json,sys; print(json.load(sys.stdin).get("recording_session_id") or "")' <<<"$summary")
        [[ -n "$session_id" ]] && break
    fi
    sleep 1
done

[[ -n "$summary" ]] || summary='{}'
session_id=$(python -c 'import json,sys; print(json.load(sys.stdin).get("recording_session_id") or "")' <<<"$summary")
transcript_chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_chars") or 0)' <<<"$summary")
cyrillic_chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_cyrillic_chars") or 0)' <<<"$summary")
language=$(python -c 'import json,sys; print(json.load(sys.stdin).get("detected_language") or "")' <<<"$summary")
normalization_applied=$(python -c 'import json,sys; print(str(bool(json.load(sys.stdin).get("normalization_applied"))).lower())' <<<"$summary")
llm_model=$(python -c 'import json,sys; print(json.load(sys.stdin).get("normalization_llm_model") or "")' <<<"$summary")
normalized_chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("normalized_transcript_chars") or 0)' <<<"$summary")
normalized_cyrillic=$(python -c 'import json,sys; print(json.load(sys.stdin).get("normalized_transcript_cyrillic_chars") or 0)' <<<"$summary")
check 'private recording session was created' test -n "$session_id"
check 'Russian transcription was produced' test "$transcript_chars" -gt 0
check 'transcription contains Cyrillic text' test "$cyrillic_chars" -gt 0
check 'recording language is Russian' test "$language" = ru
check 'local LLM normalized the transcription' test "$normalization_applied" = true
check 'normalization used the pinned local model' test "$llm_model" = "$LLM_MODEL"
check 'normalized transcript is non-empty Russian text' sh -c "test '$normalized_chars' -gt 0 && test '$normalized_cyrillic' -gt 0"

docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control'
session_path="$root/private/recordings/$session_id"
deadline=$((SECONDS + 15))
while ((SECONDS < deadline)); do
    [[ -f "$session_path/completed.json" ]] && break
    sleep 1
done
check 'recording metadata finalized on BYE' test -f "$session_path/completed.json"
check 'private transcript file exists' test -s "$session_path/transcript.txt"
check 'private WAV recording exists' test -s "$session_path/turn-0001.wav"
check 'private transcript file contains Russian text without exposing it' python -c '
import pathlib,sys
text=pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
raise SystemExit(0 if any("\u0400" <= c <= "\u052f" for c in text) else 1)' "$session_path/transcript.txt"
check 'saved WAV is valid 8 kHz mono PCM' python -c '
import sys,wave
with wave.open(sys.argv[1],"rb") as w:
    ok=w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==8000 and w.getnframes()>=24000
raise SystemExit(0 if ok else 1)' "$session_path/turn-0001.wav"

printf 'INFO: private_session=%s turns>=%s raw_chars=%s normalized_chars=%s retention_days=%s\n' \
    "$session_id" 1 "$transcript_chars" "$normalized_chars" "$RECORDING_RETENTION_DAYS"
printf 'IMS OPT-IN RECORDING -> STT -> LLM NORMALIZATION -> RUSSIAN TRANSCRIPTION: %s\n' "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
