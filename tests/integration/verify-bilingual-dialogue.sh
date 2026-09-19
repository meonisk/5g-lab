#!/usr/bin/env bash
# Prove a coherent two-phone Russian/English WAV conversation over IMS/RTP.
# Synthetic speech content stays in the local private fixture/recording trees.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts" && pwd)
root=$(cd -- "$script_dir/.." && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

base=(docker compose --env-file "$root/lab.env" --env-file "$root/secrets/ims.env" -f "$root/docker-compose.yml")
dialogue=("${base[@]}" -f "$root/docker-compose.dialogue.yml")
fail=0
restored=0
clear_adapter_sessions() {
    docker exec lab-media-adapter python -c '
import json,os,urllib.parse,urllib.request
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"],encoding="ascii").read().strip()
base="http://127.0.0.1:"+os.environ["MEDIA_ADAPTER_PORT"]+"/sessions"
h={"Authorization":"Bearer "+token}
d=json.load(urllib.request.urlopen(urllib.request.Request(base,headers=h),timeout=3))
for cid in d["sessions"]:
 urllib.request.urlopen(urllib.request.Request(base+"/"+urllib.parse.quote(cid,safe=""),headers=h,method="DELETE"),timeout=3).read()' || true
}
check() {
    local label=$1; shift
    if "$@"; then printf 'PASS: %s\n' "$label"; else printf 'FAIL: %s\n' "$label"; fail=1; fi
}
restore_clients() {
    docker logs lab-sipue1 >"$root/private/dialogue/last-ue1.log" 2>&1 || true
    docker logs lab-sipue2 >"$root/private/dialogue/last-ue2.log" 2>&1 || true
    docker exec lab-sipue1 sh -lc 'printf "cd\n1\n4\nha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
    docker exec lab-sipue2 sh -lc 'printf "cd\n1\n4\nha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
    clear_adapter_sessions
    if ((restored == 0)); then
        "${base[@]}" up -d --no-deps --force-recreate sipue1 sipue2 >/dev/null 2>&1 || true
        restored=1
    fi
}
trap restore_clients EXIT

manifest="$root/private/dialogue/manifest.json"
check 'bilingual fixture manifest exists' test -s "$manifest"
fixture_check=$(python -c '
import hashlib,json,pathlib,sys,wave
root=pathlib.Path(sys.argv[1]); m=json.loads((root/"manifest.json").read_text(encoding="utf-8-sig")); ok=True
for item in m["tracks"].values():
 p=root/item["file"]
 with wave.open(str(p),"rb") as w: ok &= w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==8000
 ok &= hashlib.sha256(p.read_bytes()).hexdigest()==item["sha256"]
print("ok" if ok else "bad")' "$root/private/dialogue")
check 'both WAV tracks are hash-verified 8 kHz mono PCM' test "$fixture_check" = ok

"${dialogue[@]}" up -d --no-deps --force-recreate sipue1 sipue2 >/dev/null
deadline=$((SECONDS + 70))
while ((SECONDS < deadline)); do
    if (docker logs lab-sipue1 2>&1 || true) | grep -q 'Response msg 200/REGISTER' \
       && (docker logs lab-sipue2 2>&1 || true) | grep -q 'Response msg 200/REGISTER'; then
        break
    fi
    sleep 2
done
ue1_logs=$(docker logs lab-sipue1 2>&1 || true)
ue2_logs=$(docker logs lab-sipue2 2>&1 || true)
check 'UE1 dialogue client registered through IMS' grep -q 'Response msg 200/REGISTER' <<<"$ue1_logs"
check 'UE2 dialogue client registered through IMS' grep -q 'Response msg 200/REGISTER' <<<"$ue2_logs"
check 'UE1 loaded the Russian Pavel fixture' grep -q "$BILINGUAL_DIALOGUE_UE1_FILE" <<<"$ue1_logs"
check 'UE2 loaded the English Zira fixture' grep -q "$BILINGUAL_DIALOGUE_UE2_FILE" <<<"$ue2_logs"

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
clear_adapter_sessions
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-sipue2 sh -lc 'printf "ha\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" terminate all >/dev/null 2>&1 || true
sleep 1
call_started=0
for _ in $(seq 1 5); do
    if docker exec lab-sipue1 sh -lc 'printf "m\nsip:${UE2_IMSI}@${IMS_DOMAIN}\n" > /tmp/pjsua-control'; then
        call_started=1
        break
    fi
    sleep 1
done
check 'dialogue caller accepted the call command' test "$call_started" = 1

deadline=$((SECONDS + 30)); call_id=''
while ((SECONDS < deadline)); do
    as_logs=$(docker logs lab-sip-as --since "$since" 2>&1)
    call_id=$(sed -n 's/.*AS observed INVITE call_id=\([^ ]*\).*/\1/p' <<<"$as_logs" | tail -1)
    ue1_logs=$(docker logs lab-sipue1 --since "$since" 2>&1)
    [[ -n "$call_id" && "$ue1_logs" == *'Response msg 200/INVITE'* ]] && break
    sleep 1
done
check 'two-subscriber IMS dialog reached 200 OK' test -n "$call_id"

docker exec lab-media-adapter python -c '
import json,os,urllib.request,sys,time
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"],encoding="ascii").read().strip()
body=json.dumps({"call_id":sys.argv[1],"observed_at":time.time(),"service_mode":"bilingual_test"}).encode()
req=urllib.request.Request("http://127.0.0.1:"+os.environ["MEDIA_ADAPTER_PORT"]+"/sessions",body,
 {"Content-Type":"application/json","Authorization":"Bearer "+token})
urllib.request.urlopen(req,timeout=3).read()' "$call_id"

docker exec lab-sipue1 sh -lc 'printf "cc\n1\n4\n" > /tmp/pjsua-control'
docker exec lab-sipue2 sh -lc 'printf "cc\n1\n4\n" > /tmp/pjsua-control'
sleep "$BILINGUAL_DIALOGUE_PLAYBACK_SECONDS"

call_info=$(docker exec lab-rtpengine rtpengine-ctl -ip "$RTPENGINE_IP" -port "$RTPENGINE_CLI_PORT" call "$call_id" info 2>&1 || true)
ue1_ip=$(docker exec lab-ue1 ip route get "$PCSCF_IP" | sed -n 's/.* src \([^ ]*\).*/\1/p')
ue2_ip=$(docker exec lab-ue2 ip route get "$PCSCF_IP" | sed -n 's/.* src \([^ ]*\).*/\1/p')
ue1_packets=$(awk -v ip="$ue1_ip" '$0 ~ ip && $0 !~ /RTCP/ {for(i=1;i<=NF;i++) if($i=="p,") sum+=$(i-1)} END{print sum+0}' <<<"$call_info")
ue2_packets=$(awk -v ip="$ue2_ip" '$0 ~ ip && $0 !~ /RTCP/ {for(i=1;i<=NF;i++) if($i=="p,") sum+=$(i-1)} END{print sum+0}' <<<"$call_info")
check 'dialogue negotiated PCMU/8000 for the processing path' grep -q 'PCMU/8000' <<<"$call_info"
check 'Russian UE sent substantial RTP through its IMS PDU session' test "$ue1_packets" -ge "$BILINGUAL_DIALOGUE_MIN_RTP_PACKETS"
check 'English UE sent substantial RTP through its IMS PDU session' test "$ue2_packets" -ge "$BILINGUAL_DIALOGUE_MIN_RTP_PACKETS"

query_events() {
    docker exec lab-ai-worker python -c '
import os,urllib.request
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"],encoding="ascii").read().strip()
req=urllib.request.Request("http://127.0.0.1:"+os.environ["AI_WORKER_PORT"]+"/events",
 headers={"Authorization":"Bearer "+token})
print(urllib.request.urlopen(req,timeout=3).read().decode())'
}
deadline=$((SECONDS + 40)); summary='{}'
while ((SECONDS < deadline)); do
    status=$(query_events 2>/dev/null || true)
    summary=$(python -c '
import json,sys
d=json.load(sys.stdin); cid=sys.argv[1]
e=[x for x in d.get("events",[]) if cid in x.get("call_ids",[]) and x.get("service_mode")=="bilingual_test" and x.get("normalization_applied")]
langs=sorted(set(x.get("detected_language") for x in e if x.get("detected_language")))
streams=sorted(set(x.get("source_stream_id") for x in e if x.get("source_stream_id")))
sessions=[x.get("recording_session_id") for x in e if x.get("recording_session_id")]
forced=sum(x.get("utterance_end_reason")=="maximum-duration" for x in e)
print(json.dumps({"events":len(e),"languages":langs,"streams":streams,"forced":forced,"session":sessions[-1] if sessions else ""}))' "$call_id" <<<"$status")
    [[ $(python -c 'import json,sys; d=json.load(sys.stdin); print("yes" if {"ru","en"}<=set(d["languages"]) and len(d["streams"])>=2 else "no")' <<<"$summary") == yes ]] && break
    sleep 2
done
check 'STT detected and normalized both Russian and English speech' python -c \
    'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if {"ru","en"}<=set(d["languages"]) else 1)' <<<"$summary"
check 'AI separated both pseudonymous RTP speaker streams' python -c \
    'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if len(d["streams"])>=2 else 1)' <<<"$summary"
check 'dialogue phrases ended on voice-activity boundaries, not the duration limit' python -c \
    'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d["forced"]==0 else 1)' <<<"$summary"

session_id=$(python -c 'import json,sys; print(json.load(sys.stdin).get("session") or "")' <<<"$summary")
docker exec lab-sipue1 sh -lc 'printf "cd\n1\n4\nha\n" > /tmp/pjsua-control'
docker exec lab-sipue2 sh -lc 'printf "cd\n1\n4\n" > /tmp/pjsua-control' >/dev/null 2>&1 || true
session_path="$root/private/recordings/$session_id"
deadline=$((SECONDS + 90))
while ((SECONDS < deadline)); do [[ -f "$session_path/completed.json" ]] && break; sleep 1; done
check 'bilingual private recording finalized on BYE' test -f "$session_path/completed.json"
status=$(query_events 2>/dev/null || true)
final_event_count=$(python -c '
import json,sys
d=json.load(sys.stdin); cid=sys.argv[1]
e=[x for x in d.get("events",[]) if cid in x.get("call_ids",[]) and x.get("service_mode")=="bilingual_test" and x.get("normalization_applied")]
if any(x.get("utterance_end_reason")=="maximum-duration" for x in e): raise SystemExit(1)
print(len(e))' "$call_id" <<<"$status" 2>/dev/null || echo 0)
check 'exactly four complete normalized dialogue turns were emitted' test "$final_event_count" = 4
check 'private transcript contains two pseudonymous speaker labels' python -c '
import pathlib,sys
t=pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
raise SystemExit(0 if "[speaker_1/" in t and "[speaker_2/" in t else 1)' "$session_path/transcript.txt"
check 'private transcript contains complete semantics from all four turns' python -c '
import pathlib,sys
t=pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").lower()
groups=(("здравствуйте","эмили"),("звук","транскрип"),("hello","alex"),("russian","english","transcript"))
lines=[line for line in t.splitlines() if line.strip()]
raise SystemExit(0 if len(lines)==4 and all(all(token in t for token in group) for group in groups) else 1)' "$session_path/transcript.txt"

printf 'INFO: call=%s ue1_packets=%s ue2_packets=%s normalized_events=%s private_session=%s\n' \
    "$call_id" "$ue1_packets" "$ue2_packets" "$final_event_count" "$session_id"
printf 'TWO-PHONE RUSSIAN/ENGLISH WAV DIALOGUE -> IMS -> STT -> LLM NORMALIZATION: %s\n' \
    "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
