#!/usr/bin/env bash
# Панель стенда (docs/9-panel.md): веб-интерфейс на 127.0.0.1:PANEL_PORT, открывается
# через SSH-туннель: ssh -L 8090:localhost:8090 <сервер>.
#   scripts/panel.sh install   # venv, сборка интерфейса, образ захвата SIP, служба systemd
#   scripts/panel.sh start | stop | restart | status
#   scripts/panel.sh sudoers   # правило sudo без пароля для кнопок радио (печатает)
#   scripts/panel.sh run       # сервер панели в этом терминале (так его запускает служба)
# Служба — systemd пользователя lab-panel; захват SIP — контейнер lab-panel-sipcap вне
# проекта lab-docker (stand.sh down его не останавливает).
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
set -a
# shellcheck source=../app/config/lab.env
source app/config/lab.env
set +a

venv=$root/local/panel-venv
web=$root/app/panel/web
unit=$HOME/.config/systemd/user/lab-panel.service
sipcap=lab-panel-sipcap

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

build_web() {
    # Сборка там, где есть Node: на хосте или в закреплённом образе node.
    if command -v npm >/dev/null; then
        (cd "$web" && npm ci --no-audit --no-fund && npm run build)
    else
        docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$web:/web" -w /web \
            "$PANEL_NODE_IMAGE" sh -c 'npm ci --no-audit --no-fund && npm run build'
    fi
    [[ -f $web/dist/index.html ]] || die "интерфейс не собрался"
}

install() {
    command -v python3 >/dev/null || die "нет python3"
    [[ -x $venv/bin/python ]] || python3 -m venv "$venv" || die "нет venv: sudo apt install python3-venv"
    "$venv/bin/pip" install -q -r app/services/requirements-http.txt
    build_web
    docker build -q -t "$sipcap" app/panel/sipcap >/dev/null

    # PATH службы — как у пользователя сейчас: заданиям нужны docker, python3, OAI.
    mkdir -p "$(dirname "$unit")"
    cat >"$unit" <<EOF
[Unit]
Description=Панель стенда 5G (127.0.0.1:$PANEL_PORT)

[Service]
WorkingDirectory=$root
Environment=PATH=$PATH
ExecStart=$root/scripts/panel.sh run
Restart=on-failure
# Задания (stand.sh up и т.п.) переживают перезапуск панели.
KillMode=process

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable lab-panel >/dev/null
    # Без linger служба пользователя останавливается, когда он выходит из SSH.
    loginctl enable-linger "$USER" 2>/dev/null ||
        echo "WARN: loginctl enable-linger $USER не удался: панель живёт, пока вы в системе"
    start
    sudo -n true 2>/dev/null ||
        echo "Кнопки радио и включения стенда требуют sudo без пароля: scripts/panel.sh sudoers"
}

start_sipcap() {
    docker rm -f "$sipcap" >/dev/null 2>&1 || true
    # Только NET_RAW (AF_PACKET), файловая система только для чтения, журнал ограничен.
    docker run -d --name "$sipcap" --restart unless-stopped --network host \
        --cap-drop ALL --cap-add NET_RAW --read-only --security-opt no-new-privileges \
        --log-opt max-size=1m --log-opt max-file=2 \
        -e PANEL_SIPCAP_PORT -e PANEL_SIPCAP_MESSAGES "$sipcap" >/dev/null
}

start() {
    [[ -f $unit ]] || die "панель не установлена: scripts/panel.sh install"
    start_sipcap
    systemctl --user restart lab-panel
    sleep 2
    status
    echo "Откройте на своём компьютере: ssh -L $PANEL_PORT:localhost:$PANEL_PORT $(hostname)"
    echo "и затем http://localhost:$PANEL_PORT"
}

stop() {
    systemctl --user stop lab-panel 2>/dev/null || true
    docker rm -f "$sipcap" >/dev/null 2>&1 || true
    echo "панель остановлена"
}

status() {
    printf '  %-18s %s\n' lab-panel "$(systemctl --user is-active lab-panel 2>/dev/null || true)"
    printf '  %-18s %s\n' "$sipcap" "$(docker inspect -f '{{.State.Status}}' "$sipcap" 2>/dev/null || echo нет)"
    if curl -fsS -o /dev/null "http://127.0.0.1:$PANEL_PORT/api/status" 2>/dev/null; then
        echo "  API: http://127.0.0.1:$PANEL_PORT отвечает"
    else
        echo "  API не отвечает: journalctl --user -u lab-panel -n 50"
    fi
}

# Команды, которые скрипты стенда выполняют через sudo. ip netns exec, env и
# nr-softmodem запускают что угодно от root: правило фактически даёт root, как и
# группа docker. Для стенда это приемлемо, для общего сервера — нет.
sudoers() {
    local ran=${OAI_RAN_DIR:-$HOME/openairinterface5g} build path commands=()
    build=$ran/cmake_targets/ran_build/build
    for path in true kill pkill ip env taskset; do
        commands+=("$(PATH=$PATH:/usr/sbin:/sbin command -v "$path")")
    done
    commands+=("$build/nr-softmodem" "$build/nr-uesoftmodem" "$ran/tools/scripts/multi-ue.sh")
    local IFS=,
    printf '# /etc/sudoers.d/5g-lab: sudo без пароля для панели стенда 5G\n'
    printf '%s ALL=(root) NOPASSWD: %s\n' "$USER" "${commands[*]}"
}

run() {
    [[ -x $venv/bin/python ]] || die "нет $venv: scripts/panel.sh install"
    export PYTHONPATH=$root/app/panel/server
    exec "$venv/bin/python" -m lab_panel
}

case ${1:-} in
install) install ;;
start | restart) start ;;
stop) stop ;;
status) status ;;
sudoers) sudoers ;;
run) run ;;
*) die "использование: scripts/panel.sh install | start | stop | restart | status | sudoers | run" ;;
esac
