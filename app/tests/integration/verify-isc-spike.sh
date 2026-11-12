#!/usr/bin/env bash
# Spike ISC (план 2026-11-12, задача 1, шаги 4–6) без ручных шагов: spike-iFC для
# SIPUE1, lab-sip-as заменяется контейнером spike_isc_chain.py, вызов SIPUE1 ->
# SIPUE2, семь проверок. Сначала нога B идёт с ISC-меткой (isc); если не все PASS —
# fallback F1 через sip:orig@ (orig). Последняя содержательная строка:
#   SPIKE DECISION: GO | GO-F1 | NO-GO | ERROR
# Стенд восстанавливается всегда (trap EXIT, в том числе Ctrl-C и SIGTERM): iFC
# абонентов из lab.env (provision.py --apply), перезапуск S-CSCF, lab-sip-as
# запущен, spike-контейнер и тестовые клиенты удалены.
#   bash app/tests/integration/verify-isc-spike.sh          # spike + восстановление
#   bash app/tests/integration/verify-isc-spike.sh cleanup  # только восстановление
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

spike=$root/app/tests/integration/spike_isc_chain.py
container=lab-spike-isc
spike_in=/lab/app/tests/integration/spike_isc_chain.py

cleanup() {
    # Восстановление не прерывается повторным Ctrl-C: игнор наследуют и docker/python.
    trap '' INT TERM
    local ok=1
    echo '===== spike: восстановление стенда ====='
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker start lab-sip-as >/dev/null || ok=0
    # iFC абонентов — из lab.env, как после start.py; spike restore — запасной путь.
    (cd "$root" && python3 scripts/provision.py --apply >/dev/null) ||
        python3 "$spike" restore || ok=0
    # S-CSCF держит spike-iFC в кэше профиля: сбросить перезапуском.
    docker restart lab-scscf >/dev/null && wait_ims_ready 120 || ok=0
    "${compose[@]}" rm -sf sipue1 sipue2 >/dev/null 2>&1 || true
    if ((ok)); then echo 'SPIKE CLEANUP: DONE'; else echo 'SPIKE CLEANUP: FAILED'; fi
}

if [[ ${1:-} == cleanup ]]; then
    cleanup
    exit 0
fi
trap 'exit 130' INT
trap 'exit 143' TERM
trap cleanup EXIT

decide() {
    printf 'SPIKE DECISION: %s\n' "$1"
    exit "$2"
}

# Одна попытка: spike-контейнер с режимом ноги B, вызов, семь проверок из шага 4.
# Возврат 0 — все семь PASS; check() из common.sh ставит fail=1 при FAIL.
attempt() {
    local mode=$1 since logs leg a
    echo "===== spike: нога B через $mode ====="
    docker rm -f "$container" >/dev/null 2>&1 || true
    # Без --rm: если spike упадёт, его вывод остаётся для docker logs. Путь в контейнере
    # той же глубины, что в репозитории: скрипт считает ROOT от своего пути.
    docker run -d --name "$container" --network "$CORE_NETWORK_NAME" --ip "$SIP_AS_IP" \
        -e SIP_AS_IP -e SIP_AS_PORT -e SCSCF_IP -e SCSCF_SIP_PORT -e IMS_DOMAIN \
        -e "SPIKE_LEG_B_ROUTE=$mode" \
        -v "$spike:$spike_in:ro" --entrypoint python lab-sip-as "$spike_in" serve >/dev/null ||
        decide 'ERROR — spike-контейнер не запустился' 2
    sleep 1
    if [[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) != true ]]; then
        docker logs "$container" 2>&1 | tail -20
        decide 'ERROR — spike-контейнер завершился сразу после запуска' 2
    fi
    fresh_clients || decide 'ERROR — SIPUE1/SIPUE2 не зарегистрировались' 2
    since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    pjsua lab-sipue1 "m\nsip:${SIPUE2_MSISDN}@${IMS_DOMAIN}\n"
    sleep 10
    logs=$(docker logs "$container" 2>&1)
    echo "$logs"
    leg=$(sed -n 's/^SPIKE1 leg_b call_id=\([^ ]*\) for .*/\1/p' <<<"$logs" | tail -1)
    a=$(sed -n 's/^SPIKE1 leg_b call_id=[^ ]* for call_id=\(.*\)$/\1/p' <<<"$logs" | tail -1)

    fail=0
    check 'нога B создана spike1' test -n "$leg"
    check 'нога B прошла spike2 (приоритет 25)' grep -q "^SPIKE2 INVITE call_id=$leg\$" <<<"$logs"
    check 'нога B прошла as (приоритет 30)' grep -q "^AS INVITE call_id=$leg\$" <<<"$logs"
    check 'Call-ID звонящего не прошёл дальше spike1' \
        bash -c "! grep -q '^SPIKE2 INVITE call_id=$a\$' <<<\"\$0\"" "$logs"
    check 'S-CSCF обработал ногу B' \
        bash -c "docker logs lab-scscf --since $since 2>&1 | grep -q 'SCSCF: INVITE .*, $leg)'"
    check 'SIPUE2 получил INVITE ноги B' \
        bash -c "docker logs lab-sipue2 --since $since 2>&1 | grep -qiE '^(Call-ID|i): *$leg'"
    check 'SIPUE1 получил 200/INVITE' \
        bash -c "docker logs lab-sipue1 --since $since 2>&1 | grep -q 'Response msg 200/INVITE'"
    if [[ -n $leg ]] && grep -q "^SPIKE1 INVITE call_id=$leg\$" <<<"$logs"; then
        echo 'INFO: S-CSCF начал цепочку заново для ноги B (spike1 видел её)'
    else
        echo 'INFO: S-CSCF продолжил цепочку со следующего приоритета'
    fi
    hangup_clients
    return "$fail"
}

echo '===== spike: iFC spike1(10) -> spike2(25) -> as(30) для SIPUE1 ====='
python3 "$spike" install || decide 'ERROR — spike-iFC не записан в PyHSS' 2
# S-CSCF берёт iFC при регистрации: сбросить кэш профиля перезапуском.
docker restart lab-scscf >/dev/null && wait_ims_ready 120 ||
    decide 'ERROR — S-CSCF не открыл Cx после перезапуска' 2
docker stop lab-sip-as >/dev/null || decide 'ERROR — lab-sip-as не остановлен' 2

attempt isc && decide GO 0
echo 'INFO: не все семь PASS с ISC-меткой — fallback F1 (нога B через sip:orig@)'
attempt orig && decide GO-F1 0
decide NO-GO 1
