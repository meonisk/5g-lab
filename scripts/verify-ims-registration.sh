#!/usr/bin/env bash
# Phase 4B (docker lab) gate: both UE-side SIP clients complete IMS
# registration (REGISTER -> 401 challenge -> authorized REGISTER -> 200 OK)
# through P-CSCF / I-CSCF / S-CSCF with Cx interaction against PyHSS.
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

uaa_success() {
    grep -q 'uaa_return' <<<"$icscf_logs" && ! grep -q 'UAR failure' <<<"$icscf_logs"
}

echo "===== REGISTER lab-sipue1 ====="
out1=$("$script_dir/sip-register.sh" lab-sipue1 2>&1)
printf '%s\n' "$out1" | grep -E "registering|OK|Unauthorized|Forbidden|error|Error" | head -8
check "lab-sipue1 REGISTER 200 OK" grep -q 'Response msg 200/REGISTER' <<<"$out1"

echo "===== REGISTER lab-sipue2 ====="
out2=$("$script_dir/sip-register.sh" lab-sipue2 2>&1)
printf '%s\n' "$out2" | grep -E "registering|OK|Unauthorized|Forbidden|error|Error" | head -8
check "lab-sipue2 REGISTER 200 OK" grep -q 'Response msg 200/REGISTER' <<<"$out2"

echo "===== S-CSCF registrar state and IMS source path ====="
scscf_logs=$(docker logs --since 10m lab-scscf 2>&1)
for tuple in "lab-ue1 $UE1_IMSI" "lab-ue2 $UE2_IMSI"; do
    read -r ue imsi <<<"$tuple"
    route_line=$(docker exec "$ue" ip route get "$PCSCF_IP" 2>/dev/null || true)
    ue_ip=$(sed -n 's/.* src \([^ ]*\).*/\1/p' <<<"$route_line")
    check "$imsi P-CSCF route uses IMS PDU TUN" grep -q ' dev uesimtun' <<<"$route_line"
    check "$imsi has a current valid S-CSCF contact from $ue_ip" \
        grep -q "${imsi}@${ue_ip}.*Contact valid" <<<"$scscf_logs"
done

echo "===== Cx interaction evidence ====="
icscf_logs=$(docker logs --since 10m lab-icscf 2>&1)
check "I-CSCF received UAA and forwarded registration" uaa_success
check "S-CSCF received successful MAA" grep -q 'maa_return code is 1' <<<"$scscf_logs"
check "S-CSCF received successful SAA" grep -q 'saa_return code is 1' <<<"$scscf_logs"

if [ "$fail" -eq 0 ]; then
    echo "PHASE 4B (DOCKER): PASS"
else
    echo "PHASE 4B (DOCKER): FAIL"
    exit 1
fi
