#!/usr/bin/env bash
# Весь стенд одной командой: ядро OAI, IMS + AI и gNB на SDR.
#   scripts/stand.sh down     # выключить всё; данные (абоненты, модели, SQN) остаются
#   scripts/stand.sh up       # включить всё и проверить (stand_check.py)
#   scripts/stand.sh up --mode baseline   # аргументы после up — для scripts/setup.sh
#   scripts/stand.sh status
# Порядок up: ядро -> core-setup.sh apply -> setup.sh (IMS + AI) -> gnb.sh up ->
# stand_check.py. После перезагрузки сервера достаточно up: контейнеры IMS и AI
# поднимаются сами, ядро и gNB — нет.
# Ядро останавливается (stop), а не удаляется: в базе MySQL ядра без тома живут
# абоненты UDR и их SQN; новая база вернула бы SQN в ноль, и SIM отвергли бы сеть.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
set -a
# shellcheck source=../app/config/lab.env
source app/config/lab.env
set +a

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n===== %s =====\n' "$*"; }

# Каталог ядра: OAI_CORE_DIR, иначе — откуда Compose запускал oai-amf (метка есть
# и у остановленного контейнера), иначе ~/oai-cn5g.
if [[ -z ${OAI_CORE_DIR:-} ]]; then
    OAI_CORE_DIR=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
        oai-amf 2>/dev/null || true)
    OAI_CORE_DIR=${OAI_CORE_DIR:-$HOME/oai-cn5g}
fi
export OAI_CORE_DIR
core=(docker compose --project-directory "$OAI_CORE_DIR" -f "$OAI_CORE_DIR/docker-compose.yaml")
nfs=(mysql oai-nrf oai-udr oai-udm oai-ausf oai-amf oai-smf oai-upf)

running() { [[ $(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null) == true ]]; }

core_healthy() {
    local name state
    for name in "${nfs[@]}"; do
        state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
            "$name" 2>/dev/null || echo missing)
        [[ $state == healthy || $state == running ]] || return 1
    done
}

down() {
    sudo -v
    step "gNB на SDR"
    scripts/gnb.sh down
    step "rfsim"
    scripts/rfsim.sh down
    step "IMS + AI"
    # Тома (PyHSS, модели, записи) остаются; удаляются только контейнеры и сети стенда.
    docker compose -p lab-docker down --remove-orphans
    step "ядро OAI ($OAI_CORE_DIR)"
    "${core[@]}" stop
    step "итог"
    status
}

up() {
    [[ -f $OAI_CORE_DIR/docker-compose.yaml ]] || die "нет ядра в $OAI_CORE_DIR (OAI_CORE_DIR)"
    sudo -v
    step "ядро OAI ($OAI_CORE_DIR)"
    # Демо-IMS ядра выключен профилем (core-setup.sh), поэтому up его не поднимает.
    "${core[@]}" up -d
    local deadline=$((SECONDS + 180))
    until core_healthy; do
        ((SECONDS < deadline)) || die "ядро не стало healthy за 3 минуты: ${core[*]} ps"
        sleep 3
    done
    echo "ядро: все NF работают"

    step "настройка ядра: PLMN, P-CSCF, абоненты UDR"
    scripts/core-setup.sh apply
    step "IMS + AI"
    scripts/setup.sh "$@"
    step "gNB на SDR"
    local radio=0
    if [[ -n ${GNB_CONF:-} || -f local/gnb/source.txt ]]; then
        # Сбой радио не мешает проверить остальное: stand_check выполняется всё равно.
        scripts/gnb.sh up || { radio=1; echo "WARN: gNB не запустился: tail -50 local/gnb/gnb.log"; }
    else
        echo "gNB не настроен (GNB_CONF пуст): пропуск"
    fi
    step "проверка"
    python3 scripts/stand_check.py
    return "$radio"
}

status() {
    local name
    for name in "${nfs[@]}" lab-pyhss lab-pcscf lab-scscf lab-sip-as lab-voice-agent lab-ai-worker; do
        printf '  %-16s %s\n' "$name" "$(running "$name" && echo работает || echo остановлен)"
    done
    printf '  %-16s %s\n' gNB "$(pgrep -f '[n]r-softmodem' >/dev/null && echo работает || echo остановлен)"
}

case ${1:-} in
down) down ;;
up) shift; up "$@" ;;
status) status ;;
*) die "использование: scripts/stand.sh up | down | status" ;;
esac
