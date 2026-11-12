#!/usr/bin/env bash
# Вызовы через 5G, а не из сети ядра: PJSUA запускается внутри namespace UE OAI
# (scripts/rfsim.sh up) и ходит в IMS через туннель oaitun, gNB и UPF. Проверяет
# PDU-сессию в пуле IMS, REGISTER абонентов UE1/UE2 с адресом туннеля, перевод
# 1003 для UE1, обычный вызов UE2 -> UE1 со звуком в обе стороны, расшифровку 1004
# для UE2, услуги профиля UE1 (перевод и запись UE1 -> UE2), «*номер» UE2 -> *UE1 и
# звонок при остановленном SIP AS. Аутентификация — SIP Digest, IMS AKA и IPsec
# здесь не проверяются. Нужны sudo (ip netns, chroot) и образ lab-pjsua.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

work=$root/local/rfsim
jail=$work/pjsua-root
# Короткая фраза: SIP_UE_TEST_UTTERANCE длиннее предела реплики AI Worker и
# режется по maximum-duration, а не по паузе.
phrase='Добрый день. Как у вас дела?'
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sudo -v || exit 1

tunnel_ip() {
    sudo ip netns exec "ue$1" ip -4 -o addr show oaitun_ue1 2>/dev/null | awk '{print $4}' | cut -d/ -f1
}
in_ims_pool() {
    python3 -c 'import ipaddress, sys; sys.exit(ipaddress.ip_address(sys.argv[1]) not in ipaddress.ip_network(sys.argv[2]))' \
        "$1" "$IMS_UE_CIDR"
}
log_of() { printf '%s/pjsua-ue%s.log' "$work" "$1"; }
mark() { wc -l <"$(log_of "$1")"; }
# Команды консоли PJSUA через FIFO; "\n" разделяет команду и её аргументы.
# timeout: запись в FIFO без читателя (клиент не стартовал) иначе висит вечно.
ue_cmd() { timeout 3 sh -c 'printf "%b" "$1" >"$2"' control "$2" "$jail/tmp/control-ue$1"; }

# Ждём строку в журнале клиента после отметки mark.
wait_log() {
    local n=$1 pattern=$2 seconds=$3 offset=$4 deadline=$((SECONDS + $3)) text
    while ((SECONDS < deadline)); do
        # Без пайпа в grep -q: под pipefail SIGPIPE писателя даёт ложный провал.
        text=$(tail -n +"$((offset + 1))" "$(log_of "$n")")
        grep -Eq -- "$pattern" <<<"$text" && return 0
        sleep 1
    done
    return 1
}
wait_docker() {
    local container=$1 pattern=$2 seconds=$3 deadline=$((SECONDS + $3))
    while ((SECONDS < deadline)); do
        log_has "$container" "$pattern" "$since" && return 0
        sleep 1
    done
    return 1
}

# Оба уведомления о записи (нога A и нога B) доиграны Voice Agent.
announcements_sent() {
    local deadline=$((SECONDS + $1)) text
    while ((SECONDS < deadline)); do
        text=$(docker logs --since "$since" lab-voice-agent 2>&1)
        (($(grep -c 'reason=announcement state=sent' <<<"$text") >= 2)) && return 0
        sleep 1
    done
    return 1
}

stop_clients() {
    for n in 1 2; do ue_cmd "$n" 'ha\nq\n' 2>/dev/null || true; done
    sleep 1
    sudo pkill -f -- "[c]hroot $jail" 2>/dev/null || true
    docker start lab-sip-as >/dev/null 2>&1 || true  # тест F мог упасть с остановленным AS
}
trap stop_clients EXIT

# Корень файловой системы образа lab-pjsua: Docker не умеет запускать контейнер
# в чужом namespace, поэтому тот же pjsua запускается через chroot.
prepare_jail() {
    if [[ ! -x $jail/usr/local/bin/pjsua ]]; then
        docker image inspect lab-pjsua >/dev/null || return 1
        sudo mkdir -p "$jail"
        local container
        container=$(docker create lab-pjsua) || return 1
        docker export "$container" | sudo tar -x -C "$jail"
        docker rm "$container" >/dev/null
    fi
    local node
    for node in 'null 3' 'random 8' 'urandom 9'; do
        set -- $node
        [[ -c $jail/dev/$1 ]] || { sudo rm -f "$jail/dev/$1"; sudo mknod -m 666 "$jail/dev/$1" c 1 "$2"; }
    done
    # Фраза и 20 с тишины: плеер PJSUA играет по кругу, а агенту нужна пауза,
    # чтобы закончить реплику и ответить, не будучи перебитым.
    sudo chroot "$jail" espeak-ng -v "$TTS_VOICE" -s "$TTS_RATE" -w /tmp/phrase.wav "$phrase" &&
        sudo python3 - "$jail/tmp" <<'EOF'
import sys, wave
folder = sys.argv[1]
with wave.open(f"{folder}/phrase.wav", "rb") as source:
    params, audio = source.getparams(), source.readframes(source.getnframes())
with wave.open(f"{folder}/phrase-pause.wav", "wb") as target:
    target.setparams(params)
    target.writeframes(audio + bytes(params.sampwidth * params.framerate * 20))
with open(f"{folder}/phrase.seconds", "w") as seconds:
    seconds.write(str(len(audio) // (params.sampwidth * params.framerate) + 1))
EOF
}

# Клиент UEn с ключами абонента UEn из lab.env. --no-vad: тишина тоже уходит в
# RTP, иначе счётчики пакетов зависят от длины фразы. --auto-update-nat=0: если
# UPF делает NAT, PJSUA видит в 401 адрес UPF и заново начинает REGISTER с новым
# Contact посреди аутентификации — S-CSCF отвечает 403. Телефон так не делает.
start_client() {
    local n=$1 address=$2 imsi_name=UE${1}_IMSI key_name=UE${1}_IMS_K
    local imsi=${!imsi_name}
    sudo rm -f "$jail/tmp/control-ue$n"
    sudo mkfifo -m 666 "$jail/tmp/control-ue$n"
    nohup sudo ip netns exec "ue$n" chroot "$jail" bash -c 'exec 3<>"$0"; exec stdbuf -oL -eL pjsua "$@" <&3' \
        "/tmp/control-ue$n" --log-level=4 --app-log-level=4 --null-audio --no-tcp --no-vad --auto-update-nat=0 \
        --clock-rate=8000 --snd-clock-rate=8000 --dis-codec='*' --add-codec="$SIP_UE_CODEC" \
        --auto-answer=200 --play-file=/tmp/phrase-pause.wav \
        --id "sip:$imsi@$IMS_DOMAIN" --registrar "sip:$IMS_DOMAIN" \
        --proxy "sip:$PCSCF_IP:$PCSCF_SIP_PORT;transport=udp;lr" --realm "$IMS_DOMAIN" \
        --username "$imsi@$IMS_DOMAIN" --password "${!key_name}" \
        --ip-addr="$address" --bound-addr="$address" >"$(log_of "$n")" 2>&1 &
}

# Порты конференц-моста: проигрыватель WAV подаётся в последний вызов.
connect_player() {
    local n=$1 offset rows
    offset=$(mark "$n")
    ue_cmd "$n" 'cl\n'
    sleep 1
    rows=$(tail -n +"$((offset + 1))" "$(log_of "$n")" | grep -E '^Port #')
    player=$(grep '\.wav' <<<"$rows" | sed -E 's/^Port #0*([0-9]+).*/\1/' | tail -1)
    call=$(grep -E '\] +sip:' <<<"$rows" | sed -E 's/^Port #0*([0-9]+).*/\1/' | tail -1)
    [[ -n $player && -n $call ]] && ue_cmd "$n" "cc\n$player\n$call\n"
}

# Фраза звучит один раз: повтор по кругу перебивал бы медленный ответ агента.
say_once() {
    connect_player "$1"
    sleep "$(cat "$jail/tmp/phrase.seconds")"
    [[ -n ${player:-} && -n ${call:-} ]] && ue_cmd "$1" "cd\n$player\n$call\n"
}

# RX текущего вызова из dq; PJSUA пишет тысячи как "2.0Kpkt".
rx_packets() {
    local n=$1 offset
    offset=$(mark "$n")
    ue_cmd "$n" 'dq\n'
    sleep 1
    tail -n +"$((offset + 1))" "$(log_of "$n")" | awk '/RX pt=/ { getline
        for (i = 1; i <= NF; i++) if ($i ~ /pkt$/) { v = $i; sub(/pkt$/, "", v)
            if (v ~ /K$/) { sub(/K$/, "", v); v *= 1000 }
            print int(v); exit } }'
}

echo '===== 5G: PDU-сессии UE ====='
declare -A address
for n in 1 2; do
    address[$n]=$(tunnel_ip "$n")
    check "UE$n: туннель oaitun_ue1 (${address[$n]:-нет}) — scripts/rfsim.sh up" test -n "${address[$n]}"
    [[ -n ${address[$n]} ]] || finish '5G UE'
    check "UE$n: адрес в пуле IMS $IMS_UE_CIDR (DNN $IMS_DNN)" in_ims_pool "${address[$n]}"
    # Наши сервисы — только через туннель: иначе SIP и RTP могли бы уйти в обход 5G.
    sudo ip netns exec "ue$n" ip route replace "$LAB_NETWORK_CIDR" dev oaitun_ue1
    check "UE$n: P-CSCF доступен через туннель" sudo ip netns exec "ue$n" ping -c2 -W3 "$PCSCF_IP"
done

echo '===== 5G: регистрация в IMS ====='
check 'корень PJSUA из образа lab-pjsua и фраза с паузой' prepare_jail
for n in 1 2; do start_client "$n" "${address[$n]}"; done
for n in 1 2; do
    imsi_name=UE${n}_IMSI
    check "UE$n: REGISTER 200 OK" wait_log "$n" 'registration success' 40 0
    # Contact в 200 OK на REGISTER возвращает регистратор S-CSCF: это сохранённый им адрес.
    check "S-CSCF: контакт ${!imsi_name}@${address[$n]} (адрес туннеля)" \
        wait_log "$n" "Contact: <sip:${!imsi_name}@${address[$n]}:[0-9]+;alias=" 5 0
    # Регистратор видит адрес UPF вместо адреса UE: UPF применяет SNAT и к DNN ims.
    # Вызовы при этом идут (rport), но контакт живёт только пока жива NAT-запись.
    if grep -q "Contact: <sip:${!imsi_name}@${UPF_IP}:" "$(log_of "$n")"; then
        echo "  ПРИЧИНА: UPF ядра делает NAT трафика UE в IMS (контакт @$UPF_IP)."
        echo "  Нужен NAT только в интернет — docs/guide-1-ims-core.md, шаг 2 (enable_snat: no)."
    fi
done

echo "===== A: UE1 -> переводчик $VOICE_TRANSLATOR_MSISDN ====="
# Журналы сервисов читаются с начала каждого теста: строки прошлого теста не в счёт.
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset=$(mark 1)
ue_cmd 1 "m\nsip:$VOICE_TRANSLATOR_MSISDN@$IMS_DOMAIN\n"
check 'UE1: 200/INVITE' wait_log 1 'Response msg 200/INVITE' 30 "$offset"
check 'Voice Agent: приветствие' wait_docker lab-voice-agent 'reason=greeting state=sent' 20
say_once 1
# На CPU рядом с rfsim перевод занимает до 20 с; запас на STT, LLM и синтез.
check 'Voice Agent: перевод озвучен полностью' wait_docker lab-voice-agent 'reason=llm_reply state=sent' 120
greeting=$(docker logs --since "$since" lab-voice-agent 2>&1 | sed -n 's/.*reason=greeting .*packets=\([0-9]*\).*/\1/p' | tail -1)
sleep 3
rx=$(rx_packets 1)
check "UE1: получил приветствие и перевод (RX ${rx:-0} > ${greeting:-0})" test "${rx:-0}" -gt "${greeting:-0}"
ue_cmd 1 'ha\n'
sleep 2

echo "===== B: UE2 -> UE1 ($UE2_MSISDN -> $UE1_MSISDN) ====="
offset1=$(mark 1)
offset2=$(mark 2)
ue_cmd 2 "m\nsip:$UE1_MSISDN@$IMS_DOMAIN\n"
check 'UE2: 200/INVITE от UE1' wait_log 2 'Response msg 200/INVITE' 30 "$offset2"
check 'UE1: вызов принят' wait_log 1 'state changed to CONFIRMED' 10 "$offset1"
connect_player 1
connect_player 2
sleep 20
# 20 с при ptime 20 мс — около 1000 пакетов; порог оставляет запас на рывки rfsim.
for n in 1 2; do
    rx=$(rx_packets "$n")
    check "UE$n: звук от собеседника (RX ${rx:-0} > 500)" test "${rx:-0}" -gt 500
done
ue_cmd 2 'ha\n'
check 'UE1: BYE дошёл' wait_log 1 'DISCONNECTED' 15 "$offset1"

echo "===== C: UE2 -> расшифровка $VOICE_TRANSCRIBER_MSISDN ====="
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset=$(mark 2)
ue_cmd 2 "m\nsip:$VOICE_TRANSCRIBER_MSISDN@$IMS_DOMAIN\n"
check 'UE2: 200/INVITE' wait_log 2 'Response msg 200/INVITE' 30 "$offset"
sleep 6
say_once 2
check 'AI Worker: фраза UE2 распознана' wait_docker lab-ai-worker 'utterance_processed .*transcript_chars=[1-9]' 90
ue_cmd 2 'ha\n'

sleep 2
echo "===== D: UE1 -> UE2: перевод $UE1_LANGUAGE-$UE2_LANGUAGE и запись ====="
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset1=$(mark 1)
offset2=$(mark 2)
ue_cmd 1 "m\nsip:$UE2_MSISDN@$IMS_DOMAIN\n"
check 'UE1: 200/INVITE (нога A translate AS)' wait_log 1 'Response msg 200/INVITE' 40 "$offset1"
# Без перевода остальные ожидания D (~4 мин) заведомо FAIL: сразу к E.
if wait_docker lab-sip-as 'AS translate answered .* languages=ru-en' 10; then
    check 'SIP AS: перевод ru-en' true
    check 'SIP AS: запись обеих ног после уведомления' \
        wait_docker lab-sip-as 'AS record started call_id=[^ ]+ legs=2' 40
    # «record started» пишется, когда уведомления поставлены в очередь, а не сыграны:
    # фраза UE1 не должна звучать поверх уведомления в ноге A.
    check 'Voice Agent: уведомления сыграны в обеих ногах' announcements_sent 60
    say_once 1
    check 'Voice Agent: перевод UE1 озвучен английским голосом' \
        wait_docker lab-voice-agent "reason=llm_reply state=sent.*voice=$TTS_TRANSLATION_VOICE" 120
    ue_cmd 1 'ha\n'
    check 'UE2: BYE ноги B дошёл' wait_log 2 'DISCONNECTED' 15 "$offset2"
    check 'AI Worker: запись закрыта' wait_docker lab-ai-worker 'AI recording_finalized session=' 30
else
    check 'SIP AS: перевод ru-en' false
    echo 'INFO: перевод не установлен, остальные проверки D пропущены'
    ue_cmd 1 'ha\n'
fi
d_failed=$(docker logs lab-voice-agent --since "$since" 2>&1 | grep -c 'reason=llm_reply state=sent')
if ((d_failed == 0)); then
    # Почему нет перевода: события AI/Voice/Media без потока пакетов (без текста реплик).
    echo "===== ДИАГНОСТИКА D с $since ====="
    for container in lab-ai-worker lab-voice-agent lab-media-adapter lab-sip-as; do
        echo "----- $container -----"
        docker logs "$container" --since "$since" 2>&1 |
            grep -vE 'stream_received|MEDIA delivered' | tail -60
    done
    echo '----- lab-media-adapter: окна RTP по направлению и услуге -----'
    docker logs lab-media-adapter --since "$since" 2>&1 |
        sed -n 's/.*MEDIA delivered direction=\([^ ]*\) .* audio=\([0-9]*\) .*service=\([^ ]*\).*/\1 \3 audio=\2/p' |
        sed -E 's/audio=[1-9][0-9]*$/audio>0/' | sort | uniq -c
    echo '----- lab-ai-worker: принятые окна (с аудио / всего) и очередь -----'
    received=$(docker logs lab-ai-worker --since "$since" 2>&1 | grep -c 'stream_received' || true)
    with_audio=$(docker logs lab-ai-worker --since "$since" 2>&1 |
        grep -cE 'stream_received .*audio=[1-9]' || true)
    echo "stream_received=$received with_audio=$with_audio"
    service_get lab-ai-worker AI_WORKER_PORT /events 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print({k: d.get(k) for k in ("queue_depth", "utterance_queue_depth", "pending_utterances",
                             "buffered_streams", "active_calls", "model_error")})'
    echo '===== КОНЕЦ ДИАГНОСТИКИ D ====='
fi
sleep 2

echo "===== E: UE2 -> *UE1: разовый перевод ====="
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset1=$(mark 1)
offset2=$(mark 2)
ue_cmd 2 "m\nsip:*$UE1_MSISDN@$IMS_DOMAIN\n"
check 'UE2: 200/INVITE' wait_log 2 'Response msg 200/INVITE' 40 "$offset2"
check 'SIP AS: перевод en-ru' wait_docker lab-sip-as 'AS translate answered .* languages=en-ru' 10
ue_cmd 2 'ha\n'
check 'UE1: BYE дошёл' wait_log 1 'DISCONNECTED' 15 "$offset1"
sleep 2

echo '===== F: SIP AS остановлен: UE1 -> UE2 ====='
docker stop -t 1 lab-sip-as >/dev/null
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
offset1=$(mark 1)
ue_cmd 1 "m\nsip:$UE2_MSISDN@$IMS_DOMAIN\n"
if ! wait_log 1 'Response msg 200/INVITE' 60 "$offset1"; then
    check 'UE1: 200/INVITE без SIP AS (DefaultHandling)' false
    echo "===== ДИАГНОСТИКА F с $since ====="
    echo '----- UE1: ответы на INVITE -----'
    tail -n +"$((offset1 + 1))" "$(log_of 1)" | grep -E '(TX|RX) [0-9]+ bytes|state changed' | tail -40
    echo '----- lab-scscf: маршрутизация и ISC -----'
    docker logs lab-scscf --since "$since" 2>&1 |
        grep -E 'NOTICE|WARNING|ERROR|ISC_|isc_|Faked|failure' | tail -120
    echo '===== КОНЕЦ ДИАГНОСТИКИ F ====='
else
    check 'UE1: 200/INVITE без SIP AS (DefaultHandling)' true
fi
ue_cmd 1 'ha\n'
docker start lab-sip-as >/dev/null

finish '5G UE -> IMS -> AI'
