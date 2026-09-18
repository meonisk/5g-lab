#!/usr/bin/env bash
set -Eeuo pipefail

: "${IMSI:?IMSI is required}"
: "${IMS_DIGEST_PASSWORD:?IMS_DIGEST_PASSWORD is required in secrets/ims.env}"

: "${IMS_DOMAIN:?IMS_DOMAIN is required}"
: "${PCSCF_IP:?PCSCF_IP is required}"
: "${PCSCF_SIP_PORT:?PCSCF_SIP_PORT is required}"
: "${RTPENGINE_IP:?RTPENGINE_IP is required}"
: "${IMS_UE_GATEWAY:?IMS_UE_GATEWAY is required}"
: "${IMS_UE_CIDR:?IMS_UE_CIDR is required}"
: "${SIP_UE_AUTO_ANSWER:?SIP_UE_AUTO_ANSWER is required}"

ipv4_to_int() {
    local a b c d
    IFS=. read -r a b c d <<<"$1"
    printf '%u\n' "$(( (a << 24) | (b << 16) | (c << 8) | d ))"
}

ipv4_in_cidr() {
    local address=$1 network=${2%/*} bits=${2#*/} mask address_i network_i
    address_i=$(ipv4_to_int "$address")
    network_i=$(ipv4_to_int "$network")
    mask=$(( (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF ))
    (( (address_i & mask) == (network_i & mask) ))
}

for _ in $(seq 1 60); do
    ims_tun=''
    for candidate in /sys/class/net/uesimtun*; do
        [[ -e "$candidate" ]] || continue
        device=${candidate##*/}
        candidate_ip=$(ip -o -4 addr show "$device" | awk '{print $4}' | cut -d/ -f1)
        if ipv4_in_cidr "$candidate_ip" "$IMS_UE_CIDR"; then
            ims_tun=$device
            break
        fi
    done
    [[ -n "$ims_tun" ]] && break
    sleep 1
done
[[ -n "${ims_tun:-}" ]] || { echo 'ERROR: no TUN reaches IMS_UE_GATEWAY' >&2; exit 1; }
ue_ip=$(ip -o -4 addr show "$ims_tun" | awk '{print $4}' | cut -d/ -f1)

# These /32 routes are the proof-carrying boundary: SIP and relayed media enter
# UERANSIM's IMS PDU session instead of taking the shared Docker bridge.
ip route replace "$PCSCF_IP/32" dev "$ims_tun"
ip route replace "$RTPENGINE_IP/32" dev "$ims_tun"
printf 'IMS transport: dev=%s source=%s gateway=%s\n' "$ims_tun" "$ue_ip" "$IMS_UE_GATEWAY"

control=/tmp/pjsua-control
rm -f "$control"
mkfifo "$control"
exec 3<>"$control"

exec pjsua \
    --log-level=4 --app-log-level=4 --null-audio --no-tcp --use-compact-form \
    --auto-answer="$SIP_UE_AUTO_ANSWER" \
    --id "sip:${IMSI}@${IMS_DOMAIN}" \
    --registrar "sip:${IMS_DOMAIN}" \
    --proxy "sip:${PCSCF_IP}:${PCSCF_SIP_PORT};transport=udp;lr" \
    --realm "$IMS_DOMAIN" \
    --username "${IMSI}@${IMS_DOMAIN}" \
    --password "$IMS_DIGEST_PASSWORD" \
    --reg-timeout=3600 \
    --ip-addr="$ue_ip" \
    <&3
