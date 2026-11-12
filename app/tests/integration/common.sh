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

# Print the final verdict line and exit with its status. Test clients exist only
# for the duration of a gate: they are removed here, not left on the stand.
finish() {
    # Сначала BYE: удалённый клиент не завершает вызов, и Voice Agent держит место
    # до истечения таймаута, а следующая проверка видит «стенд занят».
    hangup_clients
    wait_no_ai_calls 15 || true
    "${compose[@]}" rm -sf sipue1 sipue2 >/dev/null 2>&1 || true
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

# Есть ли строка (grep -E) в журнале контейнера; третий аргумент — --since. Вывод
# сначала целиком читается в переменную: в `docker logs | grep -q` под pipefail grep
# выходит на первом совпадении, docker logs получает SIGPIPE, и пайплайн «падает»
# именно тогда, когда строка найдена (ложный FAIL на длинных журналах).
log_has() {
    local text
    text=$(docker logs "$1" ${3:+--since "$3"} 2>&1)
    grep -Eq -- "$2" <<<"$text"
}

# Recreate both clients so their logs start at a fresh REGISTER, then wait for
# 200 OK. Callers may export SIPUE*_PLAYBACK_FILE first to mount dialogue WAVs.
fresh_clients() {
    "${compose[@]}" up -d --no-deps --force-recreate sipue1 sipue2 >/dev/null 2>&1 || return 1
    local deadline=$((SECONDS + 40))
    while ((SECONDS < deadline)); do
        if log_has lab-sipue1 'Response msg 200/REGISTER' &&
            log_has lab-sipue2 'Response msg 200/REGISTER'; then
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

# Ждать, пока не останется вызовов в Voice Agent и сессий в Media Adapter (сессия без
# BYE живёт MEDIA_SESSION_TTL_SECONDS после последнего RTP). Аргумент — предел в секундах.
wait_no_ai_calls() {
    local deadline=$((SECONDS + ${1:-30})) calls sessions
    count_of() {
        python3 -c 'import json,sys; print(len(json.load(sys.stdin).get(sys.argv[1], {})))' "$1" \
            2>/dev/null
    }
    while ((SECONDS < deadline)); do
        calls=$(service_get lab-voice-agent VOICE_AGENT_HTTP_PORT /status 2>/dev/null | count_of calls)
        sessions=$(service_get lab-media-adapter MEDIA_ADAPTER_PORT /sessions 2>/dev/null |
            count_of sessions)
        [[ $calls == 0 && $sessions == 0 ]] && return 0
        sleep 1
    done
    return 1
}

# При FAIL, до удаления клиентов: SIP-обмен SIPUE, решения S-CSCF и SIP AS с момента $1.
sip_diag() {
    local since=$1 client
    echo "===== ДИАГНОСТИКА SIP с $since ====="
    for client in lab-sipue1 lab-sipue2; do
        echo "----- $client: сообщения и состояния вызовов -----"
        docker logs "$client" --since "$since" 2>&1 |
            grep -E '(TX|RX) [0-9]+ bytes|state changed|DISCONNECTED|^([Cc]all-I[Dd]|i):' | tail -120
    done
    echo '----- lab-scscf: маршрутизация и ISC -----'
    docker logs lab-scscf --since "$since" 2>&1 |
        grep -E 'NOTICE|WARNING|ERROR|ISC_|isc_|Faked|failure' | tail -120
    echo '----- lab-sip-as -----'
    docker logs lab-sip-as --since "$since" 2>&1 | tail -80
    echo '===== КОНЕЦ ДИАГНОСТИКИ ====='
}

# LLM (Ollama) есть только в baseline; в compact/minimal контейнера нет, а
# нормализация расшифровки — raw. Проверки LLM тогда пропускаются, а не падают.
llm_enabled() {
    [[ $(docker inspect -f '{{.State.Running}}' lab-llm-worker 2>/dev/null) == true ]]
}

skip() {
    printf 'SKIP: %s\n' "$1"
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

# После docker restart lab-scscf: ждать открытого Cx I/S-CSCF к HSS (тот же разбор
# cdp.list_peers, что в scripts/start.py). Аргумент — предел ожидания в секундах.
wait_ims_ready() {
    local deadline=$((SECONDS + ${1:-90}))
    while ((SECONDS < deadline)); do
        python3 -c 'import sys; sys.path.insert(0, sys.argv[1] + "/scripts"); import provision, start
raise SystemExit(0 if start.ims_peers_ready(provision.read_env()) else 1)' "$root" && return 0
        sleep 2
    done
    return 1
}
