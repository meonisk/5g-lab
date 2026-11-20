#!/usr/bin/env bash
# Свой gNB на SDR (USRP): тот же nr-softmodem, но конфигурация — копия с PLMN
# MCC/MNC из lab.env (SIM-карты видят только сеть своего PLMN). Адреса AMF/NG/N3,
# частоты и параметры радио берутся из исходной конфигурации без изменений.
#   scripts/gnb.sh up       # запустить; уже работающий чужой gNB перезапускается с копией
#   scripts/gnb.sh down     # остановить gNB (и чужой, сохранив его команду)
#   scripts/gnb.sh status
# Исходная конфигурация: GNB_CONF (имя в OAI_RAN_CONF_DIR или путь). Пусто — берётся
# конфигурация и аргументы уже работающего nr-softmodem (не rfsim) и он заменяется;
# после gnb.sh down повторный up берёт их из local/gnb/source.txt.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
set -a
# shellcheck source=../app/config/lab.env
source "$root/app/config/lab.env"
set +a
# shellcheck source=lib/ran-conf.sh
source "$root/scripts/lib/ran-conf.sh"

ran=${OAI_RAN_DIR:-$HOME/openairinterface5g}
confs=${OAI_RAN_CONF_DIR:-$HOME/projects/oai_configs}
build=$ran/cmake_targets/ran_build/build
work=$root/local/gnb
ours="[n]r-softmodem -O $work/"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# PID работающего gNB на радио: nr-softmodem без --rfsim и не наш.
foreign_gnb() {
    local pid
    for pid in $(pgrep -x nr-softmodem || true); do
        tr '\0' '\n' <"/proc/$pid/cmdline" | grep -qx -- '--rfsim' && continue
        tr '\0' '\n' <"/proc/$pid/cmdline" | grep -q -- "^$work/" && continue
        echo "$pid"
        return 0
    done
    return 1
}

# Аргументы процесса без argv[0] и без пары «-O файл»: файл заменит наша копия.
process_args() {
    local skip=0 started=0 arg
    while IFS= read -r -d '' arg; do
        # Всё до самого nr-softmodem (интерпретатор, обёртка) отбрасывается.
        ((started)) || { [[ $arg == *nr-softmodem ]] && started=1; continue; }
        ((skip == 1)) && { skip=2; continue; }
        [[ $arg == -O ]] && { skip=1; continue; }
        printf '%s\0' "$arg"
    done <"/proc/$1/cmdline"
}

process_conf() {
    tr '\0' '\n' <"/proc/$1/cmdline" | sed -n '/^-O$/{n;p;q}'
}

# Работающий gNB партнёров: команда сохраняется в source.txt, процесс останавливается.
take_over() {
    local pid source args=()
    pid=$(foreign_gnb) || return 0
    source=$(process_conf "$pid")
    [[ -f $source ]] || die "gNB PID $pid: нет файла $source (gNB в контейнере? укажите GNB_CONF)"
    mapfile -d '' -t args < <(process_args "$pid")
    mkdir -p "$work"
    printf '%s
' "$source" "${args[@]}" >"$work/source.txt"
    echo "останавливаю gNB PID $pid ($source); команда сохранена в $work/source.txt"
    sudo kill -INT "$pid"
    timeout 15 sh -c "while kill -0 $pid 2>/dev/null; do sleep 1; done" || sudo kill -9 "$pid" || true
}

up() {
    [[ -x $build/nr-softmodem ]] || die "нет $build/nr-softmodem"
    pgrep -f -- "$ours" >/dev/null && { echo "gNB уже запущен этим скриптом"; status; return 0; }
    sudo -v
    take_over

    local source='' args=()
    if [[ -n ${GNB_CONF:-} ]]; then
        source=$GNB_CONF
        [[ $source == /* ]] || source=$confs/$source
        read -r -a args <<<"${GNB_ARGS:---continuous-tx}"
    elif [[ -f $work/source.txt ]]; then
        mapfile -t args <"$work/source.txt"
        source=${args[0]}
        args=("${args[@]:1}")
    fi
    [[ -n $source ]] || die "gNB не запущен и GNB_CONF пуст: укажите конфигурацию SDR в lab.env"
    [[ -f $source ]] || die "нет файла конфигурации $source"
    echo "gNB: исходная конфигурация $source"

    # @include OAI ищет рядом с конфигурацией: соседние .conf копируются.
    cp "$(dirname "$source")"/*.conf "$work/" 2>/dev/null || true
    gnb_plmn <"$source" >"$work/gnb.conf"

    # </dev/null: фоновый процесс не забирает терминал.
    nohup sudo "$build/nr-softmodem" -O "$work/gnb.conf" "${args[@]}" </dev/null >"$work/gnb.log" 2>&1 &
    timeout 60 sh -c "until grep -q 'Received NGSetupResponse' '$work/gnb.log'; do sleep 1; done" ||
        die "gNB не подключился к AMF: tail -50 $work/gnb.log (исходная: $source)"
    echo "gNB: NGSetupResponse получен, PLMN $MCC/$MNC"
}

# Останавливает наш gNB и gNB партнёров (с сохранением команды): радио свободно для rfsim.
down() {
    sudo -v
    sudo pkill -INT -f -- "$ours" 2>/dev/null || true
    timeout 15 sh -c "while pgrep -f -- '$ours' >/dev/null; do sleep 1; done" ||
        sudo pkill -9 -f -- "$ours" || true
    take_over
    echo "gNB остановлен; повторный запуск: scripts/gnb.sh up ($work/source.txt)"
}

status() {
    pgrep -af -- "$ours" || echo "наш gNB не запущен"
    grep -oE '(mcc|mnc|mnc_length) *= *[0-9]+' "$work/gnb.conf" 2>/dev/null | tr -d ' ' | sort -u | xargs || true
}

case ${1:-} in
up) up ;;
down) down ;;
status) status ;;
*) die "использование: scripts/gnb.sh up | down | status" ;;
esac
