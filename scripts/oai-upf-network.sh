#!/usr/bin/env bash
# OAI simple-switch uses one tun0 for all DNNs. Keep IMS source addresses intact.
set -Eeuo pipefail
for attempt in $(seq 1 60); do
    if ip link show "$UPF_IMS_TUN" >/dev/null 2>&1; then
        ip addr replace "$IMS_UE_GATEWAY_CIDR" dev "$UPF_IMS_TUN"
        ip route replace "$IMS_UE_CIDR" dev "$UPF_IMS_TUN"
        iptables -t nat -C POSTROUTING -s "$INTERNET_UE_CIDR" -o eth0 -j MASQUERADE 2>/dev/null ||
            iptables -t nat -A POSTROUTING -s "$INTERNET_UE_CIDR" -o eth0 -j MASQUERADE
        echo 'OAI UPF: IMS route and internet-only NAT configured'
        exit 0
    fi
    sleep 1
done
echo 'OAI UPF: no live TUN before deadline' >&2
exit 1
