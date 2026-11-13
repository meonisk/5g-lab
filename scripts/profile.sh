#!/usr/bin/env bash
# Профилирование стенда одной командой: CPU узлов и задержка перевода по этапам в
# сценариях S1–S5, перебор настроек AI (модель Whisper, потоки STT, потоковый режим,
# пауза конца фразы) и итог — что нужно для «конец фразы -> перевод» ≤ 2 с при rfsim.
# Дизайн — docs/superpowers/specs/2026-11-12-profiling-design.md, чтение отчёта —
# docs/guide-5-5g-scripts.md. Стенд IMS + AI должен быть запущен (scripts/start.py).
#   scripts/profile.sh                    # 5 раундов, полный перебор
#   scripts/profile.sh --quick            # меньше вариантов перебора, короче простой
#   scripts/profile.sh --rounds 3 --no-sweep | --no-scenarios
# Результат — local/profile/<UTC>/: report.md, report.json, profile.log и сырые JSON.
# rfsim возвращается в состояние до запуска, тестовые клиенты и временные контейнеры
# удаляются даже при сбое и Ctrl-C (trap). sudo спросит пароль сам, если найден rfsim.
set -uo pipefail
self=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")
source "$(dirname -- "$self")/../app/tests/integration/common.sh"
source "$root/scripts/lib/verify-all-lib.sh"
cd "$root" || exit 1
RUN_TITLE=PROFILE
profile=$root/scripts/profile
rfsim_pattern="[n]r-.*softmodem -O $root/local/rfsim/"

usage() {
    sed -n '2,12p' "$self" | sed 's/^# \{0,1\}//'
    echo 'Параметры: --rounds N (5), --quick, --no-sweep, --no-scenarios, -h'
}

ROUNDS=5 QUICK=0 SWEEP=1 SCENARIOS=1
while (($#)); do
    case $1 in
    --rounds) ROUNDS=${2:-}; shift ;;
    --rounds=*) ROUNDS=${1#--rounds=} ;;
    --quick) QUICK=1 ;;
    --no-sweep) SWEEP=0 ;;
    --no-scenarios) SCENARIOS=0 ;;
    -h | --help) usage; exit 0 ;;
    __step) break ;;
    *) echo "ERROR: неизвестный параметр $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
[[ $ROUNDS =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --rounds — целое > 0, а не '$ROUNDS'" >&2; exit 2; }
IDLE_SECONDS=$((QUICK ? 15 : 30))
REPEATS=$((QUICK ? 1 : 3))

rfsim_running() { pgrep -f -- "$rfsim_pattern" >/dev/null; }

step_preflight() {
    local ok=1 health
    command -v docker >/dev/null && docker info >/dev/null 2>&1 || { echo 'ERROR: docker недоступен'; ok=0; }
    command -v python3 >/dev/null || { echo 'ERROR: нет python3'; ok=0; }
    health=$(docker inspect -f '{{.State.Health.Status}}' lab-ai-worker 2>/dev/null)
    [[ $health == healthy ]] || { echo "ERROR: lab-ai-worker не healthy (${health:-нет контейнера})"; ok=0; }
    docker inspect -f '{{.State.Running}}' lab-voice-agent 2>/dev/null | grep -qx true ||
        { echo 'ERROR: lab-voice-agent не запущен'; ok=0; }
    docker image inspect lab-pjsua >/dev/null 2>&1 || { echo 'ERROR: нет образа lab-pjsua'; ok=0; }
    echo "nproc: $(nproc), cgroup: $([[ -f /sys/fs/cgroup/cgroup.controllers ]] && echo v2 || echo v1)"
    echo "rfsim до запуска: $(rfsim_running && echo запущен || echo остановлен)"
    if [[ -n $(git status --porcelain) ]]; then
        echo 'WARN: рабочее дерево не чистое — профилируется незакоммиченный код'
    fi
    python3 "$profile/report.py" "$RUN" --meta --rounds "$ROUNDS" --options "$OPTIONS" || ok=0
    ((ok)) && echo 'PREFLIGHT: PASS'
}

# Внутренний вызов шага: bash profile.sh __step ИМЯ КАТАЛОГ_ПРОГОНА РАУНДОВ ОПЦИИ.
if [[ ${1:-} == __step ]]; then
    RUN=$3 ROUNDS=$4 OPTIONS=${5:-}
    "step_$2"
    exit
fi

# ---------------------------------------------------------------- журнал
stamp=$(date -u +%Y%m%dT%H%M%SZ)
RUN=$root/local/profile/$stamp
mkdir -p "$RUN"
LOG=$RUN/profile.log
STEP_DIR=$(mktemp -d)
OPTIONS="rounds=$ROUNDS quick=$QUICK sweep=$SWEEP scenarios=$SCENARIOS"
exec > >(trap '' INT TERM; exec tee -a "$LOG") 2>&1
tee_pid=$!
keepalive='' restored=0 rfsim_before=0
rfsim_running && rfsim_before=1

# Стенд — как до запуска: временные контейнеры и тестовые клиенты удалены, rfsim в
# прежнем состоянии. Вызывается в конце и из trap EXIT; Ctrl-C во время — игнорируется.
restore_stand() {
    ((restored)) && return
    restored=1
    trap '' INT TERM
    say '===== ВОССТАНОВЛЕНИЕ СТЕНДА ====='
    docker ps -aq --filter name=lab-profile-sweep | xargs -r docker rm -f >/dev/null 2>&1
    "${compose[@]}" rm -sf sipue1 sipue2 >/dev/null 2>&1
    docker run --rm --network none -v "$root/local/private/interpreter:/fixtures" --entrypoint rm \
        lab-pjsua -f /fixtures/profile-phrase.wav >/dev/null 2>&1
    sudo -n pkill -f '[b]ench-ue[12] ' 2>/dev/null
    if ((rfsim_before)) && ! rfsim_running; then
        say 'rfsim был запущен до профилирования — поднимаю'
        timeout -k 30 400 "$root/scripts/rfsim.sh" up < /dev/null
    elif ((!rfsim_before)) && rfsim_running; then
        say 'rfsim не был запущен до профилирования — останавливаю'
        timeout -k 30 120 "$root/scripts/rfsim.sh" down < /dev/null
    fi
    say "rfsim: $(rfsim_running && echo запущен || echo остановлен) (до запуска: $( ((rfsim_before)) && echo запущен || echo остановлен))"
}
finish_run() {
    restore_stand
    [[ -n $keepalive ]] && kill "$keepalive" 2>/dev/null
    rm -rf "$STEP_DIR"
}
trap finish_run EXIT
trap on_interrupt INT TERM

echo '==================== PROFILE ===================='
echo "date (UTC):   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "host:         $(hostname) ($(uname -srm)), nproc $(nproc)"
echo "commit:       $(git log -1 --format='%h %s' 2>/dev/null)"
echo "AI mode:      $AI_MODE (AI_MODE из lab.env; работающий режим — в report.json)"
echo "options:      $OPTIONS"
echo "run:          $RUN"
echo '================================================='

fivegee=0
if reason=$(have_5g); then
    fivegee=1
    if sudo -n true 2>/dev/null || sudo -v; then
        (while kill -0 $$ 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done) &
        keepalive=$!
    else
        fivegee=0
        reason='sudo недоступен'
    fi
fi


scenario() { # scenario ИМЯ СЕКУНД [--tty]
    run_step "$1" "$2" "^SCENARIO $1: DONE" ${3:+"$3"} -- \
        python3 "$profile/scenarios.py" "$1" --out "$RUN" --rounds "$ROUNDS" --seconds "$IDLE_SECONDS"
}
skip_scenario() {
    python3 "$profile/scenarios.py" "$1" --out "$RUN" --skip "$2" >/dev/null
    skip_step "$1" "$2"
}
sweep() {
    run_step "sweep-$1" 6000 "^SWEEP $1: DONE" -- python3 "$profile/sweep.py" --load "$1" \
        --out "$RUN" --repeats "$REPEATS" $( ((QUICK)) && echo --quick)
}
radio() { # radio up|down
    if [[ $1 == up ]]; then
        rfsim_running && return 0
        run_step 'rfsim up' 400 '^UE2: [0-9]' --tty -- "$root/scripts/rfsim.sh" up
    else
        rfsim_running || return 0
        run_step 'rfsim down' 120 '^rfsim остановлен' --tty -- "$root/scripts/rfsim.sh" down
    fi
}

# ---------------------------------------------------------------- шаги
if ! run_step preflight 300 '^PREFLIGHT: PASS$' -- bash "$self" __step preflight "$RUN" "$ROUNDS" "$OPTIONS"; then
    for name in S1 S2 S3 S4 S5 sweep-idle sweep-rfsim; do skip_step "$name" 'preflight FAIL'; done
else
    # Без rfsim: S1, S3 и перебор при простое. rfsim, если был запущен, — остановить.
    if ((SCENARIOS || SWEEP)); then
        if ! radio down; then
            for name in S1 S3 sweep-idle; do skip_step "$name" 'rfsim не остановлен'; done
        else
            if ((SCENARIOS)); then
                scenario S1 $((IDLE_SECONDS + 120))
                scenario S3 $((ROUNDS * 150 + 300))
            fi
            ((SWEEP)) && sweep idle
        fi
    fi

    # С rfsim: S2, S4, S5 и перебор под нагрузкой; без 5G — SKIP с причиной.
    up_reason=''
    if ((!fivegee)); then
        up_reason="нет стенда 5G: $reason"
    elif ((SCENARIOS || SWEEP)) && ! radio up; then
        up_reason='rfsim up FAIL'
    fi
    if ((SCENARIOS)); then
        for name in S2 S4 S5; do
            if [[ -n $up_reason ]]; then
                skip_scenario "$name" "$up_reason"
            elif [[ $name == S2 ]]; then
                scenario S2 $((IDLE_SECONDS + 120))
            else
                scenario "$name" $((ROUNDS * 200 + 600)) --tty
            fi
        done
    fi
    if ((SWEEP)) && [[ -n $up_reason ]]; then
        skip_step sweep-rfsim "$up_reason"
    elif ((SWEEP)); then
        sweep rfsim
    fi
fi
run_step report 120 '^REPORT: ' -- python3 "$profile/report.py" "$RUN"

restore_stand
print_summary
status=$?
echo "REPORT: $RUN/report.md"
echo "LOG: $LOG"
exec >&- 2>&-
wait "$tee_pid" 2>/dev/null
exit "$status"
