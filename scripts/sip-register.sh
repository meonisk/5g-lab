#!/usr/bin/env bash
# Attempt IMS registration from a UE-side SIP client container (Phase 4B).
# The pjsua container shares the UE network namespace, so REGISTER is sourced
# from the ims PDU session address (uesimtun1) and routed via the P-CSCF.
#
# Usage: sip-register.sh <lab-sipue1|lab-sipue2>
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

container=${1:-}

case "$container" in
    lab-sipue1) ue=lab-ue1; imsi=$UE1_IMSI ;;
    lab-sipue2) ue=lab-ue2; imsi=$UE2_IMSI ;;
    *) printf 'ERROR: unknown container %s (use lab-sipue1|lab-sipue2)\n' "$container" >&2; exit 2 ;;
esac

docker restart "$container" >/dev/null
deadline=$((SECONDS + 25))
route_src=''
while (( SECONDS < deadline )); do
    route_line=$(docker exec "$ue" ip route get "$PCSCF_IP" 2>/dev/null || true)
    route_src=$(sed -n 's/.* src \([^ ]*\).*/\1/p' <<<"$route_line")
    [[ "$route_line" == *" dev uesimtun"* ]] && break
    sleep 1
done
ue_ip=$route_src
printf '== %s expected IMPU sip:%s@%s from %s ==\n' \
    "$container" "$imsi" "$IMS_DOMAIN" "$ue_ip"
if [[ -z "$ue_ip" || "$route_line" != *" dev uesimtun"* ]]; then
    printf 'ERROR: P-CSCF route does not use an IMS PDU TUN: %s\n' "$route_line" >&2
    exit 1
fi

while (( SECONDS < deadline )); do
    logs=$(docker logs --since 30s "$container" 2>&1)
    if grep -q 'Response msg 200/REGISTER' <<<"$logs"; then
        printf '%s\n' "$logs" | grep -E 'IMS transport|SIP UDP socket|TX .*REGISTER|RX .*401/REGISTER|RX .*200/REGISTER|registration success' | tail -10
        exit 0
    fi
    if grep -Eq 'registration failed, status=(403|404|500|503|504)' <<<"$logs"; then
        printf '%s\n' "$logs" | grep -E 'RX .*REGISTER|registration failed' | tail -8 >&2
        exit 1
    fi
    sleep 1
done
docker logs --since 30s "$container" 2>&1 | tail -40 >&2
printf 'ERROR: registration did not complete in 25 seconds\n' >&2
exit 1
