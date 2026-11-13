#!/usr/bin/env bash
# Полная проверка стенда одной командой, по порядку: preflight, start.py, абоненты,
# перезапуск S-CSCF и DNS, spike ISC (GO / GO-F1 / NO-GO), проверка iFC задачи 2,
# verify-ims, verify-services, регрессия задачи 14, verify-5g (если есть rfsim).
# Каждый шаг — с таймаутом; PASS = код 0 и решающая строка в выводе. Сбой шага не
# останавливает прогон: зависимые шаги — SKIP, остальные выполняются. Стенд не
# останавливается; spike восстанавливает iFC, S-CSCF и lab-sip-as даже при Ctrl-C.
# Журнал целиком — local/verify-all/<UTC>.log, в конце — таблица PASS/FAIL/SKIP.
#   scripts/verify-all.sh                 # режим AI — AI_MODE из lab.env
#   scripts/verify-all.sh --mode baseline # передаётся в scripts/start.py
# Запускать от обычного пользователя в группе docker (sudo спросит пароль сам, если
# найден rfsim). GO-F1: SIP_AS_LEG_B_ROUTE=orig задаётся переменной окружения при
# повторном start.py — lab.env не меняется; навсегда — правкой строки в lab.env.
set -uo pipefail
self=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")
source "$(dirname -- "$self")/../app/tests/integration/common.sh"
source "$root/scripts/lib/verify-all-lib.sh"
cd "$root" || exit 1
tests=$root/app/tests/integration

START_ARGS=("$@")
START_MODE=''
[[ ${1:-} == --mode && -n ${2:-} ]] && START_MODE=$2
[[ ${1:-} == --mode=* ]] && START_MODE=${1#--mode=}

step_preflight() {
    local ok=1 compose_version
    command -v docker >/dev/null || { echo 'ERROR: нет docker'; ok=0; }
    docker info >/dev/null 2>&1 || { echo 'ERROR: docker недоступен: docker info'; ok=0; }
    compose_version=$(docker compose version --short 2>/dev/null)
    if [[ -z $compose_version ]]; then
        echo 'ERROR: нет docker compose v2'
        ok=0
    elif ! printf '2.33.0\n%s\n' "${compose_version#v}" | sort -VC; then
        echo "WARN: Compose $compose_version старше 2.33 (README)"
    fi
    command -v python3 >/dev/null || { echo 'ERROR: нет python3'; ok=0; }
    command -v timeout >/dev/null || { echo 'ERROR: нет timeout (coreutils)'; ok=0; }
    echo "branch: $(git rev-parse --abbrev-ref HEAD) commit: $(git rev-parse HEAD)"
    if [[ -n $(git status --porcelain) ]]; then
        echo 'WARN: рабочее дерево не чистое — прогон проверяет незакоммиченный код:'
        git status --short
    fi
    ((EUID != 0)) || echo 'WARN: запуск от root: local/ получит владельца root; rfsim ищется в /root'
    python3 scripts/start.py "${START_ARGS[@]}" --check || ok=0
    ((ok)) && echo 'PREFLIGHT: PASS'
}

step_restart() {
    docker restart lab-scscf lab-dns || return 1
    wait_ims_ready 120 || { echo 'ERROR: Cx I/S-CSCF к HSS не открыт за 120 с'; return 1; }
    local deadline=$((SECONDS + 60))
    until docker exec lab-dns nslookup "scscf.$IMS_DOMAIN" "$LOOPBACK_IP" 2>/dev/null |
        grep -Fq "$SCSCF_IP"; do
        ((SECONDS < deadline)) || { echo 'ERROR: lab-dns не отвечает'; return 1; }
        sleep 2
    done
    echo "READY: S-CSCF Cx открыт, lab-dns отвечает scscf.$IMS_DOMAIN -> $SCSCF_IP"
}

# Задача 2, шаг 9: dry-run печатает профили lab.env, файлы iFC в lab-pyhss совпадают
# с provision.ifc_xml() для каждого абонента.
step_task2() {
    local dry expected
    dry=$(python3 scripts/provision.py) || return 1
    echo "$dry"
    expected="SIPUE1: IMSI $SIPUE1_IMSI, MSISDN $SIPUE1_MSISDN, услуги ${SIPUE1_SERVICES:--}, язык ${SIPUE1_LANGUAGE:-$DEFAULT_LANGUAGE} (dry-run)"
    grep -Fxq "$expected" <<<"$dry" || { echo "FAIL: нет строки dry-run: $expected"; return 1; }
    python3 - <<'EOF' || return 1
import subprocess, sys
sys.path.insert(0, "scripts")
import provision
settings = provision.read_env()
bad = 0
for entry in provision.subscribers(settings):
    path = f"/pyhss/ifc-{entry['name']}.xml"
    stored = subprocess.run(["docker", "exec", "lab-pyhss", "cat", path],
                            capture_output=True, text=True, check=False).stdout
    want = provision.ifc_xml(settings, entry["services"])
    ok = stored == want
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'}: {path} = ifc_xml({','.join(entry['services']) or '-'}),"
          f" InitialFilterCriteria> x{stored.count('InitialFilterCriteria>')}")
raise SystemExit(1 if bad else 0)
EOF
    echo 'TASK 2 PROVISIONING + IFC: PASS'
}

# GO-F1: lab-sip-as пересоздаётся start.py с SIP_AS_LEG_B_ROUTE=orig из окружения
# (интерполяция Compose важнее --env-file); lab.env и другие файлы не меняются.
step_f1() {
    SIP_AS_LEG_B_ROUTE=orig python3 scripts/start.py "${START_ARGS[@]}" || return 1
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' lab-sip-as |
        grep -qx 'SIP_AS_LEG_B_ROUTE=orig' || { echo 'ERROR: lab-sip-as без orig'; return 1; }
    echo 'F1 OVERRIDE: SIP_AS_LEG_B_ROUTE=orig in lab-sip-as'
}

# Внутренний вызов шага: bash verify-all.sh __step ИМЯ [аргументы start.py].
if [[ ${1:-} == __step ]]; then
    step=$2
    shift 2
    START_ARGS=("$@")
    "step_$step"
    exit
fi

# ---------------------------------------------------------------- журнал
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$root/local/verify-all"
LOG=$root/local/verify-all/$stamp.log
STEP_DIR=$(mktemp -d)
# tee игнорирует Ctrl-C: иначе журнал оборвётся раньше итоговой таблицы.
exec > >(trap '' INT TERM; exec tee -a "$LOG") 2>&1
tee_pid=$!
keepalive=''
finish_run() {
    [[ -n $keepalive ]] && kill "$keepalive" 2>/dev/null
    rm -rf "$STEP_DIR"
}
trap finish_run EXIT
trap on_interrupt INT TERM
print_header

fivegee=0
if reason=$(have_5g); then
    fivegee=1
    # verify-5g-ue.sh и rfsim.sh вызывают sudo: пароль один раз сейчас, затем держим.
    if sudo -n true 2>/dev/null || sudo -v; then
        # Без журнала: иначе цикл держит открытым канал tee, и wait "$tee_pid" в конце
        # ждёт его вечно (прогон напечатал итог и не вернул приглашение).
        (while kill -0 $$ 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done) \
            </dev/null >/dev/null 2>&1 &
        keepalive=$!
    else
        fivegee=0
        reason='sudo недоступен'
    fi
fi

regression=(
    "verify-ims-call|600|^IMS CALL \+ AS \+ RTPENGINE \+ AI FAIL-OPEN: PASS$|bash $tests/verify-ims-call.sh"
    "verify-voice-agent|600|^VOICE AGENT SERVICE NUMBER: PASS$|bash $tests/verify-voice-agent.sh"
    "verify-translation|600|^RU SPEECH -> STT -> EN TRANSLATION -> TTS -> RTP: PASS$|bash $tests/verify-translation.sh"
    "verify-transcription|600|^OPT-IN RECORDING -> STT -> LLM NORMALIZATION -> TRANSCRIPT: PASS$|bash $tests/verify-transcription.sh"
    "verify_interpreter.py|600|\"pass\": true|python3 $tests/verify_interpreter.py"
    "verify-security|300|^SECURITY/PRIVACY GATE: PASS$|bash $tests/verify-security.sh"
)
later=(start.py provision restart isc-spike f1-override task2-ifc verify-ims verify-services)
later+=("${regression[@]%%|*}" verify-5g)

skip_all() {
    local name
    for name in "${later[@]}"; do [[ -n $(result_of "$name") ]] || skip_step "$name" "$1"; done
}

# ---------------------------------------------------------------- шаги
if ! run_step preflight 300 '^PREFLIGHT: PASS$' -- bash "$self" __step preflight "${START_ARGS[@]}"; then
    skip_all 'preflight FAIL'
elif ! run_step start.py 3600 '^STARTED: IMS \+ AI \(' -- python3 scripts/start.py "${START_ARGS[@]}"; then
    skip_all 'start.py FAIL: стенд не готов'
else
    profiles=1 spike_ok=0 spike_reason='' decision=''
    run_step provision 300 '^SIPUE2: IMPU sip:' -- python3 scripts/provision.py --apply || profiles=0
    run_step restart 300 '^READY: ' -- bash "$self" __step restart || profiles=0

    if ((!profiles)); then
        skip_step isc-spike 'provision или restart FAIL'
        spike_reason='зависимость provision/restart FAIL'
    else
        run_step isc-spike 900 '^SPIKE DECISION: (GO|GO-F1)$' -- bash "$tests/verify-isc-spike.sh"
        spike_out=$LAST_OUT
        [[ -n $spike_out ]] && decision=$(sed -n 's/^SPIKE DECISION: //p' "$spike_out" | tail -1)
        # Страховка: spike запускался, но не подтвердил восстановление — восстановить здесь.
        if [[ -n $spike_out ]] && ! grep -qx 'SPIKE CLEANUP: DONE' "$spike_out"; then
            say 'spike не подтвердил восстановление — восстанавливаю стенд'
            timeout -k 30 400 bash "$tests/verify-isc-spike.sh" cleanup < /dev/null
        fi
        case $decision in
        GO) spike_ok=1 ;;
        GO-F1) run_step f1-override 1800 '^F1 OVERRIDE: ' -- bash "$self" __step f1 "${START_ARGS[@]}" &&
            spike_ok=1 || spike_reason='GO-F1, но SIP_AS_LEG_B_ROUTE=orig не применён' ;;
        *) spike_reason="spike ${decision:-без решения}: услуги translate/record не проверяются" ;;
        esac
    fi
    if [[ -z $(result_of f1-override) ]]; then
        [[ $decision == GO ]] && skip_step f1-override 'spike GO: ISC-метка работает, F1 не нужен'
        [[ $decision == GO ]] || skip_step f1-override "spike ${decision:-не запускался}: F1 не применяется"
    fi

    run_step task2-ifc 300 '^TASK 2 PROVISIONING \+ IFC: PASS$' -- bash "$self" __step task2
    run_step verify-ims 600 '^IMS DNS \+ HSS \+ REGISTRATION: PASS$' -- bash "$tests/verify-ims.sh"
    if ((spike_ok || interrupted)); then
        run_step verify-services 1200 '^IMS SERVICES: TRANSLATE \+ RECORD \+ STAR \+ PLAIN \+ AS DOWN: PASS$' \
            -- bash "$tests/verify-services.sh"
    elif ((profiles)); then
        fail_step verify-services "$spike_reason"
    else
        skip_step verify-services "$spike_reason"
    fi

    # Незавершённый вызов предыдущего шага занимает место Voice Agent (compact: 2):
    # следующий шаг видит «стенд занят» или переводимый звонок идёт без перевода.
    settle_calls() {
        ((interrupted)) && return
        # 150 с: сессия Media Adapter без BYE истекает через MEDIA_SESSION_TTL_SECONDS (120).
        bash -c 'source "$1/common.sh" && wait_no_ai_calls 150' settle "$tests" ||
            say 'ВНИМАНИЕ: остались вызовы Voice Agent или сессии Media Adapter после 150 с'
    }

    for entry in "${regression[@]}"; do
        IFS='|' read -r name seconds expect command <<<"$entry"
        settle_calls
        # shellcheck disable=SC2086 # команда из таблицы выше, пути без пробелов
        run_step "$name" "$seconds" "$expect" -- $command
    done

    if ((fivegee)); then
        settle_calls
        run_step verify-5g 1800 '^5G UE -> IMS -> AI: PASS$' --tty -- "$root/scripts/verify-5g.sh"
    else
        skip_step verify-5g "нет стенда 5G: $reason"
    fi
fi

print_summary
status=$?
echo "LOG: $LOG"
exec >&- 2>&-
wait "$tee_pid" 2>/dev/null
exit "$status"
