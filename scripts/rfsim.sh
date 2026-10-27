#!/usr/bin/env bash
# Радио без телефона: gNB и два UE OAI в режиме RF Simulator, в фоне, журналы в
# local/rfsim. Нужен собранный openairinterface5g и конфигурации стенда; сами
# конфигурации не меняются — копии получают DNN IMS_DNN и адрес NG/N3 хоста на
# мосту ядра (в исходных стоит адрес контейнера gNB, которого на хосте нет).
#   scripts/rfsim.sh up | down | status
# Запускать от обычного пользователя: sudo нужен только OAI и ip netns.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
set -a
# shellcheck source=../app/config/lab.env
source "$root/app/config/lab.env"
set +a

# Пути стенда; переопределяются в lab.env или окружении.
ran=${OAI_RAN_DIR:-$HOME/openairinterface5g}
confs=${OAI_RAN_CONF_DIR:-$HOME/projects/oai_configs}
gnb_source=${RFSIM_GNB_CONF:-band78_20mhz.conf}
read -r -a ue_sources <<<"${RFSIM_UE_CONFS:-ue0.conf ue1.conf}"
work=$root/local/rfsim
build=$ran/cmake_targets/ran_build/build
# Кавычки обязательны: [0] без них — шаблон имени файла для bash.
channel=('--rfsimulator.[0].options' chanmod --channelmod.modellist modellist_rfsimu_1)
# Шаблон процессов с нашими копиями; [n] не даёт pgrep/pkill найти собственную
# командную строку, в которой этот шаблон записан.
ours="[n]r-.*softmodem -O $work/"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# OAI создаёт туннель по номеру UE в своём процессе; у каждого UE он нулевой,
# поэтому в каждом namespace интерфейс называется одинаково.
tunnel_ip() {
    sudo ip netns exec "ue$1" ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}' | cut -d/ -f1
}

wait_for() {
    local seconds=$1; shift
    local deadline=$((SECONDS + seconds))
    while ((SECONDS < deadline)); do
        "$@" && return 0
        sleep 1
    done
    return 1
}

# Адрес хоста на мосту ядра — шлюз сети, к которой подключён P-CSCF.
host_address() {
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.Gateway}}/{{.IPPrefixLen}}{{end}}' lab-pcscf
}

prepare_configs() {
    mkdir -p "$work"
    # @include OAI ищет рядом с конфигурацией, поэтому модели канала копируются.
    cp "$confs"/channelmod_rfsimu*.conf "$work/"
    local address
    address=$(host_address)
    [[ $address == */* && $address != /* ]] || die "нет шлюза сети ядра у lab-pcscf; стенд запущен?"
    sed -E "s#(GNB_IPV4_ADDRESS_FOR_(NG_AMF|NGU)) *= *\"[^\"]*\"#\\1 = \"$address\"#" \
        "$confs/$gnb_source" >"$work/gnb.conf"
    local n
    for n in 1 2; do
        sed -E "s/dnn *= *\"[^\"]*\"/dnn = \"$IMS_DNN\"/" "$confs/${ue_sources[n - 1]}" >"$work/ue$n.conf"
    done
}

start_radio() {
    pgrep -f '[s]oftmodem' >/dev/null && die "softmodem уже запущен: $(pgrep -af '[s]oftmodem' | head -1)"
    [[ -x $build/nr-softmodem ]] || die "нет $build/nr-softmodem"
    sudo -v
    prepare_configs

    # </dev/null у фоновых процессов: они не забирают терминал и не портят его режим.
    nohup sudo env RFSIMULATOR=server "$build/nr-softmodem" -O "$work/gnb.conf" --continuous-tx \
        --rfsim "${channel[@]}" </dev/null >"$work/gnb.log" 2>&1 &
    wait_for 30 grep -q 'Received NGSetupResponse' "$work/gnb.log" ||
        die "gNB не подключился к AMF: grep -E 'SCTP|errno|bind' $work/gnb.log"
    echo "gNB: NGSetupResponse получен"

    # Частоту и numerology UE берёт из строки, которую печатает сам gNB.
    local ue_options
    ue_options=$(sed -n 's/.*Command line parameters for OAI UE: //p' "$work/gnb.log" | head -1)
    [[ -n $ue_options ]] || die "gNB не напечатал параметры UE"

    local n
    for n in 1 2; do
        # multi-ue.sh создаёт namespace ueN; сервер rfsim доступен из него на 10.(200+N).1.100.
        sudo ip netns list | grep -qw "ue$n" || sudo "$ran/tools/scripts/multi-ue.sh" "-c$n" >/dev/null
        # shellcheck disable=SC2086 # параметры UE — несколько отдельных слов
        nohup sudo ip netns exec "ue$n" "$build/nr-uesoftmodem" -O "$work/ue$n.conf" --rfsim $ue_options \
            "${channel[@]}" "--rfsimulator.[0].serveraddr" "10.$((200 + n)).1.100" </dev/null >"$work/ue$n.log" 2>&1 &
        # UE подключаются по очереди: при одновременном входе gNB rfsim под нагрузкой
        # не успевает с PDCCH (растёт CCE fail), и SMF отклоняет сессию по таймеру.
        # Регистрация и PDU-сессия одного UE занимают до двух минут.
        wait_for 120 test -n "$(tunnel_ip "$n")" ||
            die "UE$n без PDU-сессии: grep -E 'PduSession|reject' $work/ue$n.log; docker logs --tail 20 oai-smf. Радио оставлено для разбора: scripts/rfsim.sh down"
        printf 'UE%s: %s\n' "$n" "$(tunnel_ip "$n")"
    done
}

# Останавливаются только процессы с нашими копиями конфигураций: чужой gNB не трогаем.
# Сначала UE по SIGINT, пока gNB ещё работает: так у UE есть шанс отключиться от
# сети. Иначе SMF хранит старую PDU-сессию, и новый запрос с тем же ID остаётся
# без ответа.
stop_radio() {
    local ues="[n]r-uesoftmodem -O $work/"
    sudo pkill -INT -f -- "$ues" 2>/dev/null || true
    wait_for 10 sh -c "! pgrep -f -- '$ues' >/dev/null" || true
    sudo pkill -INT -f -- "$ours" 2>/dev/null || true
    wait_for 10 sh -c "! pgrep -f -- '$ours' >/dev/null" || sudo pkill -9 -f -- "$ours" || true
    grep -h 'Deregistration' "$work"/ue[12].log 2>/dev/null | tail -2 || true
    echo "rfsim остановлен"
}

status() {
    pgrep -af -- "$ours" || echo "rfsim не запущен"
    local n
    for n in 1 2; do
        printf 'UE%s: %s\n' "$n" "$(tunnel_ip "$n" || true)"
    done
}

case ${1:-} in
up) start_radio ;;
down) stop_radio ;;
status) status ;;
*) die "использование: scripts/rfsim.sh up | down | status" ;;
esac
