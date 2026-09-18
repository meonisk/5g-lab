#!/usr/bin/env bash
# Prove that live PCMU from an IMS call reaches the local faster-whisper backend
# and produces an in-memory transcript. No audio is written to disk.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
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
check 'faster-whisper model is ready' test -n "$status"
check 'configured backend is live' grep -q '"backend": "faster-whisper"' <<<"$status"

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
since_epoch=$(python -c 'import time; print(time.time())')
clear_adapter_sessions
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" terminate all >/dev/null 2>&1 || true
sleep 1
docker exec lab-sipue1 sh -lc "printf 'm\nsip:${VOICE_AGENT_MSISDN}@${IMS_DOMAIN}\n' > /tmp/pjsua-control"

deadline=$((SECONDS + 25))
call_id=''
while ((SECONDS < deadline)); do
    as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
    call_id=$(sed -n 's/.*AS terminated INVITE for voice agent call_id=\([^ ]*\).*/\1/p' <<<"$as_logs" | tail -1)
    [[ -n "$call_id" ]] && break
    sleep 1
done
check 'voice-agent IMS dialog started' test -n "$call_id"

printf '===== process live RTP audio =====\n'
deadline=$((SECONDS + 60))
summary=''
while ((SECONDS < deadline)); do
    status=$(query_events 2>/dev/null || true)
    if [[ -n "$status" ]]; then
        summary=$(python -c '
import json,sys
data=json.load(sys.stdin); call_id=sys.argv[1]; since=float(sys.argv[2])
matches=[e for e in data.get("events",[]) if call_id in e.get("call_ids",[]) and e.get("processed_at",0)>=since and e.get("audio_duration_seconds",0)>0]
best=max(matches, key=lambda e:e.get("transcript_chars",0), default={})
print(json.dumps({k:best.get(k) for k in ("backend_id","audio_duration_seconds","audio_rms","transcript","transcript_chars","processing_ms","audio_sha256")}, ensure_ascii=False))' \
            "$call_id" "$since_epoch" <<<"$status")
        chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_chars") or 0)' <<<"$summary")
        ((chars > 0)) && break
    fi
    sleep 2
done

[[ -n "$summary" ]] || summary='{}'
audio_seconds=$(python -c 'import json,sys; print(json.load(sys.stdin).get("audio_duration_seconds") or 0)' <<<"$summary")
chars=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript_chars") or 0)' <<<"$summary")
backend_id=$(python -c 'import json,sys; print(json.load(sys.stdin).get("backend_id") or "")' <<<"$summary")
processing_ms=$(python -c 'import json,sys; print(json.load(sys.stdin).get("processing_ms") or 0)' <<<"$summary")
transcript=$(python -c 'import json,sys; print(json.load(sys.stdin).get("transcript") or "")' <<<"$summary")

check 'real PCMU audio was decoded and processed' python -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 3 else 1)' "$audio_seconds"
check 'local semantic STT produced text' test "$chars" -gt 0
check 'result identifies the replaceable backend' grep -q '^faster-whisper:' <<<"$backend_id"
printf 'INFO: backend=%s audio_seconds=%s processing_ms=%s transcript=%q\n' \
    "$backend_id" "$audio_seconds" "$processing_ms" "$transcript"

printf 'REAL IMS AUDIO -> LOCAL STT: %s\n' "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
