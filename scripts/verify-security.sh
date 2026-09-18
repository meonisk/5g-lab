#!/usr/bin/env bash
# Security/privacy regression gate for the custom IMS service path.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

fail=0
check() {
    local label=$1; shift
    if "$@" >/dev/null 2>&1; then printf 'PASS: %s\n' "$label"; else printf 'FAIL: %s\n' "$label"; fail=1; fi
}

inspect_equals() {
    local container=$1 template=$2 expected=$3 actual
    actual=$(docker inspect --format "$template" "$container")
    test "$actual" = "$expected"
}

for container in lab-sip-as lab-media-adapter lab-ai-worker lab-voice-agent; do
    check "$container root filesystem is read-only" inspect_equals "$container" '{{.HostConfig.ReadonlyRootfs}}' true
    check "$container has no-new-privileges" sh -c \
        "docker inspect --format '{{json .HostConfig.SecurityOpt}}' '$container' | grep -q 'no-new-privileges'"
done
for container in lab-pyhss lab-icscf lab-scscf lab-pcscf lab-sipue1 lab-sipue2; do
    check "$container uses bounded Docker logs" sh -c \
        "docker inspect --format '{{index .HostConfig.LogConfig.Config \"max-size\"}}' '$container' | grep -qx '$CUSTOM_SERVICE_LOG_MAX_SIZE'"
done
check 'PyHSS file logs are transient tmpfs' sh -c \
    "docker inspect --format '{{json .HostConfig.Tmpfs}}' lab-pyhss | grep -q '/pyhss/log'"

for container in lab-sip-as lab-ai-worker lab-voice-agent; do
    check "$container drops every Linux capability" sh -c \
        "docker inspect --format '{{json .HostConfig.CapDrop}}' '$container' | grep -q '\"ALL\"'"
done
check 'Media Adapter retains only NET_RAW capability' sh -c \
    "docker inspect --format '{{json .HostConfig.CapAdd}} {{json .HostConfig.CapDrop}}' lab-media-adapter | grep -q 'NET_RAW.*ALL'"

unauthorized=$(docker exec lab-voice-agent wget -S -O- "http://127.0.0.1:${VOICE_AGENT_HTTP_PORT}/status" 2>&1 || true)
check 'Voice Agent status rejects missing bearer token' grep -q '401 Unauthorized' <<<"$unauthorized"

ai_unauthorized=$(docker exec lab-ai-worker python -c '
import os,urllib.error,urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:"+os.environ["AI_WORKER_PORT"]+"/events",timeout=2)
    print("unexpected-success")
except urllib.error.HTTPError as exc:
    print(exc.code)')
check 'AI transcript endpoint rejects missing bearer token' test "$ai_unauthorized" = 401
check 'AI model state is isolated in its dedicated volume' sh -c \
    "docker inspect --format '{{json .Mounts}}' lab-ai-worker | grep -q '\"Destination\":\"$AI_MODEL_CACHE\".*\"RW\":true'"

token=$(docker exec lab-sip-as sh -c 'cat "$SERVICE_CONTROL_TOKEN_FILE"')
authorized=$(docker exec lab-sip-as wget -qO- --header="Authorization: Bearer $token" \
    "http://${VOICE_AGENT_IP}:${VOICE_AGENT_HTTP_PORT}/status")
check 'authenticated service control request succeeds' grep -q '"status": "ok"' <<<"$authorized"

bad_media=$(docker exec lab-sip-as python -c '
import json,os,urllib.error,urllib.request
token=open(os.environ["SERVICE_CONTROL_TOKEN_FILE"]).read().strip()
req=urllib.request.Request(os.environ["VOICE_AGENT_URL"].rstrip("/")+"/calls",
    json.dumps({"call_id":"security-test","remote_ip":"127.0.0.1","remote_port":9}).encode(),
    {"Content-Type":"application/json","Authorization":"Bearer "+token})
try:
    urllib.request.urlopen(req,timeout=2)
    print("unexpected-success")
except urllib.error.HTTPError as exc:
    print(exc.code)
')
check 'Voice Agent rejects non-RTPengine media destination' test "$bad_media" = 400

check 'subscriber identities are absent from custom service environment' sh -c \
    "! docker inspect lab-sip-as lab-media-adapter lab-ai-worker lab-voice-agent | grep -qE 'SUBSCRIBER_(K|OPC)|IMS_DIGEST_PASSWORD'"
check 'Mongo provisioning does not receive SIP Digest secret' sh -c \
    "! docker inspect lab-mongo | grep -q 'IMS_DIGEST_PASSWORD='"
check 'UERANSIM does not receive SIP Digest secret' sh -c \
    "! docker inspect lab-ue1 lab-ue2 | grep -q 'IMS_DIGEST_PASSWORD='"
check 'PJSUA does not receive subscriber K or OPc' sh -c \
    "! docker inspect lab-sipue1 lab-sipue2 | grep -qE 'SUBSCRIBER_(K|OPC)='"
custom_logs=$(docker logs lab-sip-as 2>&1; docker logs lab-media-adapter 2>&1; \
    docker logs lab-ai-worker 2>&1; docker logs lab-voice-agent 2>&1)
check 'custom service logs contain no subscriber IMSI' sh -c \
    "! grep -qE '$UE1_IMSI|$UE2_IMSI'" <<<"$custom_logs"
check 'AI operational logs contain no transcript text' sh -c \
    "! grep -q 'transcript='" <<<"$(docker logs lab-ai-worker 2>&1)"

printf 'SECURITY/PRIVACY GATE: %s\n' "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
exit "$fail"
