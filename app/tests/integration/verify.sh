#!/usr/bin/env bash
# Reproduce the asterisk_legacy two-UE evidence against the containerised lab.
set -uo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"
: "${INTERNET_UE_GATEWAY:?INTERNET_UE_GATEWAY is required}"
: "${INTERNET_UE_CIDR:?INTERNET_UE_CIDR is required}"

echo "===== gNB NG Setup ====="
docker logs lab-gnb 2>&1 | grep -E "SCTP connection established|NG Setup procedure"

for ue in lab-ue1 lab-ue2; do
    echo "===== $ue registration and PDU session ====="
    docker logs "$ue" 2>&1 | grep -E "Initial Registration is successful|PDU Session establishment is successful|TUN interface"

    internet_tun=''
    for candidate in uesimtun0 uesimtun1; do
        candidate_ip=$(docker exec "$ue" sh -c "ip -o -4 addr show '$candidate' 2>/dev/null | awk '{print \$4}' | cut -d/ -f1" || true)
        if [[ -n "$candidate_ip" ]] && ipv4_in_cidr "$candidate_ip" "$INTERNET_UE_CIDR"; then
            internet_tun=$candidate
            break
        fi
    done
    [[ -n "$internet_tun" ]] || { printf 'FAIL: no TUN reaches internet gateway for %s\n' "$ue"; continue; }
    echo "----- $ue -> ogstun $INTERNET_UE_GATEWAY via $internet_tun -----"
    docker exec "$ue" ping -I "$internet_tun" -c 4 "$INTERNET_UE_GATEWAY" 2>&1 | tail -2

    echo "----- $ue -> $INTERNET_PROBE_IP -----"
    docker exec "$ue" ping -I "$internet_tun" -c 4 "$INTERNET_PROBE_IP" 2>&1 | tail -2
done

echo "===== UPF ogstun ====="
docker exec lab-upf ip -4 addr show ogstun | sed -n '2p'

echo "===== subscribers ====="
docker exec lab-mongo mongosh --quiet --eval \
    'db.getSiblingDB("open5gs").subscribers.find({},{imsi:1,_id:0}).toArray()'
