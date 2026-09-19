#!/usr/bin/env bash
# Source from another script. It exports the public topology and local secrets
# from their two canonical files and rejects a missing configuration early.
lab_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for env_file in "$lab_root/lab.env" "$lab_root/secrets/ims.env"; do
    [[ -f "$env_file" ]] || { printf 'ERROR: missing %s\n' "$env_file" >&2; return 2; }
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
done

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
