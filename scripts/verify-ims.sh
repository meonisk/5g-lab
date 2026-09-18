#!/usr/bin/env bash
# Phase 4A (docker lab) gate:
#   - both UEs hold internet+ims PDU sessions (TUN per DNN)
#   - ims pool reachable through UPF ogstun2 without NAT
#   - IMS DNS zone resolves from inside the lab
#   - PyHSS holds both IMS subscribers and listens on Diameter Cx
set -uo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

fail=0
check() {
    local name=$1; shift
    if "$@" >/dev/null 2>&1; then
        printf 'PASS: %s\n' "$name"
    else
        printf 'FAIL: %s\n' "$name"
        fail=1
    fi
}

: "${IMS_DOMAIN:?IMS_DOMAIN is required}"
: "${IMS_UE_GATEWAY:?IMS_UE_GATEWAY is required}"
: "${IMS_UE_GATEWAY_CIDR:?IMS_UE_GATEWAY_CIDR is required}"
: "${IMS_UE_CIDR:?IMS_UE_CIDR is required}"
: "${INTERNET_UE_CIDR:?INTERNET_UE_CIDR is required}"
: "${PYHSS_API_BIND:?PYHSS_API_BIND is required}"
: "${PYHSS_API_PORT:?PYHSS_API_PORT is required}"

echo "===== UE PDU sessions (internet + ims) ====="
for ue in lab-ue1 lab-ue2; do
    n=$(docker logs "$ue" 2>&1 | grep -c "PDU Session establishment is successful")
    check "$ue: two PDU sessions established" test "$n" -ge 2
    docker logs "$ue" 2>&1 | grep "TUN interface" | tail -2
    ims_tun=''
    for candidate in uesimtun0 uesimtun1; do
        candidate_ip=$(docker exec "$ue" sh -c "ip -o -4 addr show '$candidate' 2>/dev/null | awk '{print \$4}' | cut -d/ -f1" || true)
        if [[ -n "$candidate_ip" ]] && ipv4_in_cidr "$candidate_ip" "$IMS_UE_CIDR"; then
            ims_tun=$candidate
            break
        fi
    done
    if [ -n "$ims_tun" ]; then
        check "$ue: ping $IMS_UE_GATEWAY via $ims_tun" \
            docker exec "$ue" ping -I "$ims_tun" -c 3 -W 2 "$IMS_UE_GATEWAY"
    else
        printf 'FAIL: %s: no ims TUN device found in logs\n' "$ue"
        fail=1
    fi
done

echo "===== UPF ims DNN (ogstun2, no NAT) ====="
check "ogstun2 carries $IMS_UE_GATEWAY_CIDR" \
    docker exec lab-upf sh -c "ip -4 addr show ogstun2 | grep -Fq 'inet $IMS_UE_GATEWAY_CIDR'"
check "kernel route $IMS_UE_CIDR dev ogstun2" \
    docker exec lab-upf sh -c "ip route show '$IMS_UE_CIDR' | grep -q 'dev ogstun2'"
check "no MASQUERADE for the ims pool" \
    sh -c "! docker exec lab-upf iptables -t nat -S | grep -Fq '$IMS_UE_CIDR'"
check "internet pool NAT intact" \
    docker exec lab-upf sh -c "iptables -t nat -S | grep -Fq '$INTERNET_UE_CIDR'"

echo "===== IMS DNS ====="
for entry in "pcscf $PCSCF_IP" "icscf $ICSCF_IP" "scscf $SCSCF_IP" "hss $PYHSS_IP"; do
    read -r name expected_ip <<<"$entry"
    check "dnsmasq resolves $name.$IMS_DOMAIN to $expected_ip" \
        docker exec lab-dns sh -c "nslookup '$name.$IMS_DOMAIN' '$LOOPBACK_IP' | grep -Fq '$expected_ip'"
done
check "dnsmasq SRV _sip._udp home domain -> icscf:$ICSCF_SIP_PORT" \
    docker exec lab-dns sh -c "nslookup -type=srv _sip._udp.$IMS_DOMAIN '$LOOPBACK_IP' 2>/dev/null | grep -q '$ICSCF_SIP_PORT'"

echo "===== PyHSS ====="
check "REST API lists both IMSIs" \
    sh -c "curl -fsS 'http://$PYHSS_API_BIND:$PYHSS_API_PORT/ims_subscriber/list' | grep -q '$UE1_IMSI' && curl -fsS 'http://$PYHSS_API_BIND:$PYHSS_API_PORT/ims_subscriber/list' | grep -q '$UE2_IMSI'"
check "Diameter Cx listening on ${IMS_DOMAIN}:$PYHSS_BIND_PORT" \
    docker exec lab-pyhss python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('$PYHSS_IP', int('$PYHSS_BIND_PORT')))"

if [ "$fail" -eq 0 ]; then
    echo "PHASE 4A (DOCKER): PASS"
else
    echo "PHASE 4A (DOCKER): FAIL"
    exit 1
fi
