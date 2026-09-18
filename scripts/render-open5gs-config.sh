#!/bin/sh
set -eu

source_config=$1
rendered_config=$2
cp "$source_config" "$rendered_config"

for name in INTERNET_UE_CIDR INTERNET_UE_GATEWAY INTERNET_DNN IMS_UE_CIDR IMS_UE_GATEWAY IMS_DNN PCSCF_IP DNS_IP; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || { echo "ERROR: missing $name" >&2; exit 2; }
    sed "s|__${name}__|$value|g" "$rendered_config" > "$rendered_config.next"
    mv "$rendered_config.next" "$rendered_config"
done

if grep -q '__[A-Z0-9_][A-Z0-9_]*__' "$rendered_config"; then
    echo "ERROR: unresolved placeholder in $rendered_config" >&2
    exit 2
fi
