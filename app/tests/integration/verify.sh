#!/usr/bin/env bash
# Reproduce the asterisk_legacy two-UE evidence against the containerised lab.
set -uo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../scripts" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"
: "${INTERNET_UE_GATEWAY:?INTERNET_UE_GATEWAY is required}"
: "${INTERNET_UE_CIDR:?INTERNET_UE_CIDR is required}"
: "${INTERNET_PROBE_IP:?INTERNET_PROBE_IP is required}"

failures=0
check_logs() {
    local container=$1 label=$2 logs pattern
    shift 2
    if ! logs=$(docker logs "$container" 2>&1); then
        printf 'FAIL: could not read %s logs\n' "$label" >&2
        failures=$((failures + 1))
        return
    fi
    for pattern in "$@"; do
        if ! grep -Fq "$pattern" <<<"$logs"; then
            printf 'FAIL: %s missing log event: %s\n' "$label" "$pattern" >&2
            failures=$((failures + 1))
        fi
    done
    grep -E 'SCTP connection established|NG Setup procedure|Initial Registration is successful|PDU Session establishment is successful|TUN interface' <<<"$logs" || true
}

check_command() {
    local label=$1
    shift
    if ! "$@"; then
        printf 'FAIL: %s\n' "$label" >&2
        failures=$((failures + 1))
    fi
}

echo "===== gNB NG Setup ====="
check_logs lab-gnb 'gNB' 'SCTP connection established' 'NG Setup procedure'

for ue in lab-ue1 lab-ue2; do
    echo "===== $ue registration and PDU session ====="
    check_logs "$ue" "$ue" 'Initial Registration is successful' 'PDU Session establishment is successful' 'TUN interface'

    internet_tun=''
    for candidate in uesimtun0 uesimtun1; do
        candidate_ip=$(docker exec "$ue" sh -c "ip -o -4 addr show '$candidate' 2>/dev/null | awk '{print \$4}' | cut -d/ -f1" 2>/dev/null) || candidate_ip=''
        if [[ -n "$candidate_ip" ]] && ipv4_in_cidr "$candidate_ip" "$INTERNET_UE_CIDR"; then
            internet_tun=$candidate
            break
        fi
    done
    if [[ -z "$internet_tun" ]]; then
        printf 'FAIL: no TUN reaches internet gateway for %s\n' "$ue" >&2
        failures=$((failures + 1))
        continue
    fi
    echo "----- $ue -> ogstun $INTERNET_UE_GATEWAY via $internet_tun -----"
    check_command "$ue gateway ping" docker exec "$ue" ping -I "$internet_tun" -c 4 "$INTERNET_UE_GATEWAY"

    echo "----- $ue -> $INTERNET_PROBE_IP -----"
    check_command "$ue internet probe ping" docker exec "$ue" ping -I "$internet_tun" -c 4 "$INTERNET_PROBE_IP"
done

echo "===== UPF ogstun ====="
check_command 'UPF ogstun address' docker exec lab-upf ip -4 addr show ogstun

echo "===== subscribers ====="
check_command 'subscriber query' docker exec lab-mongo mongosh --quiet --eval \
    'db.getSiblingDB("open5gs").subscribers.find({},{imsi:1,_id:0}).toArray()'

exit "$((failures > 0))"
