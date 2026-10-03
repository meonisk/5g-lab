#!/usr/bin/env bash
# OAI simple-switch использует один tun0 для всех DNN; сохраняем исходные адреса IMS.
set -Eeuo pipefail
for attempt in $(seq 1 60); do
    if ip link show "$UPF_IMS_TUN" >/dev/null 2>&1; then
        ip addr replace "$IMS_UE_GATEWAY_CIDR" dev "$UPF_IMS_TUN"
        ip route replace "$IMS_UE_CIDR" dev "$UPF_IMS_TUN"
        iptables -t nat -C POSTROUTING -s "$INTERNET_UE_CIDR" -o eth0 -j MASQUERADE 2>/dev/null ||
            iptables -t nat -A POSTROUTING -s "$INTERNET_UE_CIDR" -o eth0 -j MASQUERADE
        echo 'OAI UPF: маршрут IMS настроен, NAT включён только для internet'
        exit 0
    fi
    sleep 1
done
echo 'OAI UPF: интерфейс TUN не появился за отведённое время' >&2
exit 1
