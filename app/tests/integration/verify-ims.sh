#!/usr/bin/env bash
# Шаги 1–3 вызова: DNS IMS, абоненты и Cx в PyHSS, маршрут к пулу UE через UPF,
# регистрация двух тестовых клиентов REGISTER -> 401 -> REGISTER -> 200 через
# P/I/S-CSCF с UAR/MAR/SAR к HSS. Телефоны и вызовы не затрагивает.
set -uo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

echo '===== IMS DNS ====='
for entry in "pcscf $PCSCF_IP" "icscf $ICSCF_IP" "scscf $SCSCF_IP" "hss $PYHSS_IP" "as $SIP_AS_IP"; do
    read -r name expected <<<"$entry"
    check "dnsmasq: $name.$IMS_DOMAIN -> $expected" \
        docker exec lab-dns sh -c "nslookup '$name.$IMS_DOMAIN' '$LOOPBACK_IP' | grep -Fq '$expected'"
done
check "dnsmasq: SRV _sip._udp.$IMS_DOMAIN -> I-CSCF:$ICSCF_SIP_PORT" \
    docker exec lab-dns sh -c "nslookup -type=srv _sip._udp.$IMS_DOMAIN '$LOOPBACK_IP' | grep -q '$ICSCF_SIP_PORT'"

echo '===== Маршрут к UE через UPF ====='
for container in lab-pcscf lab-scscf lab-rtpengine; do
    check "$container: $IMS_UE_CIDR via $UPF_IP" \
        sh -c "docker exec $container ip route show '$IMS_UE_CIDR' | grep -q 'via $UPF_IP'"
done

echo '===== PyHSS ====='
subscribers=$(curl -fsS "http://$PYHSS_API_BIND:$PYHSS_API_PORT/ims_subscriber/list?page=0&page_size=200")
for imsi in "$UE1_IMSI" "$UE2_IMSI" "$SIPUE1_IMSI" "$SIPUE2_IMSI"; do
    check "PyHSS: IMS-абонент $imsi" grep -q "\"$imsi\"" <<<"$subscribers"
done
check "PyHSS: Diameter Cx слушает $PYHSS_IP:$PYHSS_BIND_PORT" docker exec lab-pyhss python3 -c \
    "import socket; socket.create_connection(('$PYHSS_IP', $PYHSS_BIND_PORT), 3)"
# Готовность Cx: тот же разбор cdp.list_peers, что и в scripts/start.py.
for container in lab-icscf lab-scscf; do
    check "$container: Cx к hss.$IMS_DOMAIN открыт" sh -c "docker exec $container kamcmd cdp.list_peers |
        python3 -c 'import sys; sys.path.insert(0, \"$root/scripts\"); import start;
raise SystemExit(0 if start.connected_hss_peer(sys.stdin.read(), \"$IMS_DOMAIN\") else 1)'"
done

echo '===== Регистрация тестовых клиентов ====='
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
check 'lab-sipue1 и lab-sipue2: REGISTER 200 OK' fresh_clients
scscf_logs=$(docker logs --since "$since" lab-scscf 2>&1)
icscf_logs=$(docker logs --since "$since" lab-icscf 2>&1)
for entry in "$SIPUE1_IMSI $SIPUE1_IP" "$SIPUE2_IMSI $SIPUE2_IP"; do
    read -r imsi address <<<"$entry"
    check "S-CSCF: контакт $imsi@$address действителен" \
        grep -q "${imsi}@${address}.*Contact valid" <<<"$scscf_logs"
done
uaa_ok() { grep -q uaa_return <<<"$icscf_logs" && ! grep -q 'UAR failure' <<<"$icscf_logs"; }
check 'I-CSCF: UAA получен (выбор S-CSCF)' uaa_ok
check 'S-CSCF: MAA успешен (вектор аутентификации)' grep -q 'maa_return code is 1' <<<"$scscf_logs"
check 'S-CSCF: SAA успешен (профиль и iFC)' grep -q 'saa_return code is 1' <<<"$scscf_logs"

finish 'IMS DNS + HSS + REGISTRATION'
