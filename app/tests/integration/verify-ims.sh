#!/usr/bin/env bash
# Phase 4A (docker lab) gate:
#   - both UEs hold internet+ims PDU sessions (TUN per DNN)
#   - ims pool reachable through UPF $UPF_IMS_TUN without NAT
#   - IMS DNS zone resolves from inside the lab
#   - PyHSS holds both IMS subscribers and listens on Diameter Cx
set -uo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../scripts" && pwd)
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
    # Current interface addresses prove live PDU sessions; logs may contain stale successes.
    if ! addresses=$(docker exec "$ue" ip -o -4 addr show); then
        printf 'FAIL: %s: cannot read current interfaces\n' "$ue"
        fail=1
        continue
    fi
    ims_tun=''
    ims_ip=''
    internet_tun=''
    while read -r index candidate family cidr rest; do
        [[ $candidate == uesimtun* && $family == inet ]] || continue
        candidate_ip=${cidr%%/*}
        if ipv4_in_cidr "$candidate_ip" "$IMS_UE_CIDR"; then
            ims_tun=$candidate
            ims_ip=$candidate_ip
        elif ipv4_in_cidr "$candidate_ip" "$INTERNET_UE_CIDR"; then
            internet_tun=$candidate
        fi
    done <<< "$addresses"
    if [[ -n $ims_tun && -n $internet_tun && $ims_tun != "$internet_tun" ]]; then
        printf 'PASS: %s: live internet and ims TUN addresses\n' "$ue"
        check "$ue: ping $IMS_UE_GATEWAY via $ims_tun" \
            docker exec "$ue" ping -I "$ims_tun" -c 3 -W 2 "$IMS_UE_GATEWAY"
        for target in "$PCSCF_IP" "$RTPENGINE_IP"; do
            if route=$(docker exec "$ue" ip -4 route get "$target") && \
                [[ " $route " == *" dev $ims_tun "* && " $route " == *" src $ims_ip "* ]]; then
                printf 'PASS: %s: route to %s uses %s from %s\n' "$ue" "$target" "$ims_tun" "$ims_ip"
            else
                printf 'FAIL: %s: route to %s bypasses ims TUN/source\n' "$ue" "$target"
                fail=1
            fi
        done
    else
        printf 'FAIL: %s: live internet/ims TUN pair missing\n' "$ue"
        fail=1
    fi
done

echo "===== UPF ims DNN ($UPF_IMS_TUN, no NAT) ====="
check "$UPF_IMS_TUN carries $IMS_UE_GATEWAY_CIDR" \
    docker exec lab-upf sh -c "ip -4 addr show $UPF_IMS_TUN | grep -Fq 'inet $IMS_UE_GATEWAY_CIDR'"
check "kernel route $IMS_UE_CIDR dev $UPF_IMS_TUN" \
    docker exec lab-upf sh -c "ip route show '$IMS_UE_CIDR' | grep -q 'dev $UPF_IMS_TUN'"
if nat_rules=$(docker exec lab-upf iptables -t nat -S); then
    if grep -Fq "$IMS_UE_CIDR" <<< "$nat_rules"; then
        printf 'FAIL: no MASQUERADE for the ims pool\n'
        fail=1
    else
        printf 'PASS: no MASQUERADE for the ims pool\n'
    fi
else
    printf 'FAIL: cannot read UPF NAT rules\n'
    fail=1
fi
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
