#!/usr/bin/env bash
# Sourced by every shell gate: loads lab.env, reports PASS/FAIL lines and drives
# the test SIP clients lab-sipue1/2 through their PJSUA control FIFO.
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
set -a
# shellcheck source=../../config/lab.env
source "$root/app/config/lab.env"
set +a
compose=(docker compose --project-directory "$root" --env-file "$root/app/config/lab.env"
    -f "$root/docker-compose.yml" --profile test)

fail=0
check() {
    local label=$1; shift
    if "$@" >/dev/null 2>&1; then
        printf 'PASS: %s\n' "$label"
    else
        printf 'FAIL: %s\n' "$label"
        fail=1
    fi
}

# Print the final verdict line and exit with its status.
finish() {
    printf '%s: %s\n' "$1" "$([[ $fail == 0 ]] && echo PASS || echo FAIL)"
    exit "$fail"
}

# Send PJSUA console commands; "\n" separates commands and their arguments.
pjsua() {
    docker exec "$1" sh -c 'printf "%b" "$1" > /tmp/pjsua-control' control "$2"
}

hangup_clients() {
    for client in lab-sipue1 lab-sipue2; do
        pjsua "$client" 'ha\n' >/dev/null 2>&1 || true
    done
}

# Recreate both clients so their logs start at a fresh REGISTER, then wait for
# 200 OK. Callers may export SIPUE*_PLAYBACK_FILE first to mount dialogue WAVs.
fresh_clients() {
    "${compose[@]}" up -d --no-deps --force-recreate sipue1 sipue2 >/dev/null 2>&1 || return 1
    local deadline=$((SECONDS + 40))
    while ((SECONDS < deadline)); do
        if docker logs lab-sipue1 2>&1 | grep -q 'Response msg 200/REGISTER' &&
            docker logs lab-sipue2 2>&1 | grep -q 'Response msg 200/REGISTER'; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# The service API needs the internal bearer token, so the request runs inside
# the service container that already owns it.
service_get() {
    docker exec "$1" python -c '
import os, sys, urllib.request
token = open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii").read().strip()
request = urllib.request.Request(
    "http://127.0.0.1:" + os.environ[sys.argv[1]] + sys.argv[2],
    headers={"Authorization": "Bearer " + token},
)
print(urllib.request.urlopen(request, timeout=3).read().decode())' "$2" "$3"
}

# JSON field from stdin, default 0/empty; keeps the gates free of jq.
json_field() {
    python3 -c 'import json,sys; v=json.load(sys.stdin).get(sys.argv[1]); print("" if v is None else v)' "$1"
}

# Call-ID of the latest SIP AS log line matching a sed capture expression.
wait_call_id() {
    local pattern=$1 since=$2 deadline=$((SECONDS + 25)) call_id=''
    while ((SECONDS < deadline)); do
        call_id=$(docker logs lab-sip-as --since "$since" 2>&1 | sed -n "s/$pattern/\\1/p" | tail -1)
        [[ -n "$call_id" ]] && break
        sleep 1
    done
    printf '%s' "$call_id"
}
