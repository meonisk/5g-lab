#!/usr/bin/env bash
set -Eeuo pipefail
ip -4 addr show "$UPF_IMS_TUN" | grep -Fq "inet $IMS_UE_GATEWAY_CIDR"
ss -lun | grep -q ':8805 '
ss -lun | grep -q ':2152 '
iptables -t nat -C POSTROUTING -s "$INTERNET_UE_CIDR" -o eth0 -j MASQUERADE
# Неожиданное правило NAT для адресов IMS означает, что сервис не готов.
rules=$(iptables -t nat -S)
! grep -F "$IMS_UE_CIDR" <<< "$rules" | grep -Eq 'SNAT|MASQUERADE'
