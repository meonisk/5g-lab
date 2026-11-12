#!/usr/bin/env bash
# Подключается из scripts/verify-all.sh и scripts/profile.sh: журнал, запуск шага с
# таймаутом, итоговая таблица, журналы контейнеров при FAIL. Сам ничего не запускает.
# RUN_TITLE — заголовок итоговой таблицы (по умолчанию VERIFY-ALL).

STEP_NAMES=()
STEP_RESULTS=()
STEP_NOTES=()
interrupted=0
current=''
LAST_OUT=''
DUMP_CONTAINERS=(lab-scscf lab-sip-as lab-ai-worker lab-voice-agent lab-media-adapter)

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

record() {
    STEP_NAMES+=("$1")
    STEP_RESULTS+=("$2")
    STEP_NOTES+=("$3")
    printf '>>> %s: %s — %s\n' "$2" "$1" "$3"
}

skip_step() { record "$1" SKIP "$2"; }
fail_step() { record "$1" FAIL "$2"; }

# Результат шага по имени; пусто — шаг ещё не записан.
result_of() {
    local i
    for i in "${!STEP_NAMES[@]}"; do
        [[ ${STEP_NAMES[$i]} == "$1" ]] && printf '%s' "${STEP_RESULTS[$i]}"
    done
}

dump_container_logs() {
    local container
    for container in "${DUMP_CONTAINERS[@]}"; do
        echo "----- docker logs --tail 80 $container -----"
        docker logs --tail 80 "$container" 2>&1 || echo "(нет контейнера $container)"
    done
    echo '----- конец журналов контейнеров -----'
}

# Ctrl-C/SIGTERM: текущему шагу — SIGTERM (его trap восстанавливает стенд),
# остальные шаги — SKIP. timeout держит команду вне группы терминала, поэтому
# сигнал передаём сами.
on_interrupt() {
    interrupted=1
    [[ -n $current ]] && pkill -TERM -P "$current" -x timeout 2>/dev/null
}

# Есть ли OAI rfsim (те же пути, что в scripts/rfsim.sh) и запущенный AMF ядра.
have_5g() {
    local build=${OAI_RAN_DIR:-$HOME/openairinterface5g}/cmake_targets/ran_build/build
    [[ -x $build/nr-softmodem && -x $build/nr-uesoftmodem ]] || { echo "нет rfsim в $build"; return 1; }
    docker ps --format '{{.Names}}' | grep -qx oai-amf || { echo 'нет контейнера oai-amf'; return 1; }
}

# run_step ИМЯ СЕКУНД РЕГУЛЯРКА [--tty] -- КОМАНДА...
# PASS — код 0 и в выводе есть строка по РЕГУЛЯРКЕ (решающая строка шага);
# SKIP — код 0 и строка «STEP SKIP: причина» (шаг сам понял, что невозможен);
# FAIL — иначе, с причиной. --tty: команде нужен терминал (sudo в verify-5g).
# LAST_OUT — файл вывода шага (пусто, если шаг не запускался).
run_step() {
    local name=$1 seconds=$2 expect=$3 foreground=()
    shift 3
    [[ $1 == --tty ]] && { foreground=(--foreground); shift; }
    [[ $1 == -- ]] && shift
    LAST_OUT=''
    if ((interrupted)); then
        skip_step "$name" 'прервано пользователем'
        return 1
    fi
    local out rc line last skipped
    out=$(mktemp "$STEP_DIR/step.XXXXXX")
    LAST_OUT=$out
    echo
    say "===== ШАГ: $name (таймаут ${seconds}s) ====="
    say "+ $*"
    (
        timeout "${foreground[@]}" -k 180 "$seconds" "$@" < /dev/null 2>&1 | tee "$out"
        exit "${PIPESTATUS[0]}"
    ) &
    current=$!
    while true; do
        wait "$current"
        rc=$?
        # wait прерван сигналом (trap уже передал SIGTERM) — ждём завершения шага.
        kill -0 "$current" 2>/dev/null || break
    done
    current=''
    line=$(grep -E -- "$expect" "$out" | tail -1)
    skipped=$(sed -n 's/^STEP SKIP: //p' "$out" | tail -1)
    # Первая строка FAIL/ERROR — обычно причина, остальные — следствия.
    last=$(grep -E '^(FAIL|ERROR)|: FAIL$' "$out" | head -1)
    if ((rc == 124 || rc == 137)); then
        fail_step "$name" "таймаут ${seconds}s"
    elif ((interrupted)); then
        fail_step "$name" "прервано (код $rc)"
    elif ((rc == 0)) && [[ -n $skipped ]]; then
        skip_step "$name" "$skipped"
        return 0
    elif ((rc != 0)); then
        fail_step "$name" "код $rc${last:+; $last}; ожидалось /$expect/"
    elif [[ -z $line ]]; then
        fail_step "$name" "код 0, но нет строки /$expect/"
    else
        record "$name" PASS "$line"
        return 0
    fi
    dump_container_logs
    return 1
}

print_summary() {
    local i pass=0 fail=0 skip=0
    echo
    echo "==================== ИТОГ ${RUN_TITLE:-VERIFY-ALL} ===================="
    printf '%-3s %-5s %-30s %s\n' '#' 'RES' 'ШАГ' 'РЕШАЮЩАЯ СТРОКА / ПРИЧИНА'
    for i in "${!STEP_NAMES[@]}"; do
        printf '%-3s %-5s %-30s %s\n' "$((i + 1))" "${STEP_RESULTS[$i]}" "${STEP_NAMES[$i]}" \
            "${STEP_NOTES[$i]}"
        case ${STEP_RESULTS[$i]} in
        PASS) pass=$((pass + 1)) ;;
        FAIL) fail=$((fail + 1)) ;;
        *) skip=$((skip + 1)) ;;
        esac
    done
    echo '========================================================'
    printf '%s: %s — PASS %d, FAIL %d, SKIP %d\n' "${RUN_TITLE:-VERIFY-ALL}" \
        "$([[ $fail == 0 && $interrupted == 0 ]] && echo PASS || echo FAIL)" "$pass" "$fail" "$skip"
    [[ $fail == 0 && $interrupted == 0 ]]
}

print_header() {
    echo '==================== VERIFY-ALL ===================='
    echo "date (UTC):   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "host:         $(hostname) ($(uname -srm))"
    echo "user:         $(id -un) (uid $EUID)"
    echo "repo:         $root"
    echo "branch:       $(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    echo "commit:       $(git -C "$root" log -1 --format='%h %s' 2>/dev/null)"
    echo "AI mode:      ${START_MODE:-$AI_MODE (AI_MODE из lab.env)}"
    echo "leg B route:  ${SIP_AS_LEG_B_ROUTE} (lab.env; spike может переключить на orig)"
    echo "docker:       $(docker version --format '{{.Server.Version}}' 2>&1 | head -1)"
    echo "compose:      $(docker compose version --short 2>&1 | head -1)"
    echo "python3:      $(python3 --version 2>&1)"
    echo "log:          $LOG"
    echo '===================================================='
}
