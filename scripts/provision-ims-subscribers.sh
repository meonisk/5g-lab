#!/usr/bin/env bash
# Provision the two env-defined IMS subscribers.
# into lab-pyhss via its REST API. Lab counterpart of the ims repo
# deploy/provision-ims-subscribers.sh; key material is the stand's public
# local secrets are loaded from the ignored local/secrets/ims.env file.
set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=load-lab-env.sh
source "$script_dir/load-lab-env.sh"

action='--dry-run'
: "${PYHSS_API_BIND:?PYHSS_API_BIND is required}"
: "${PYHSS_API_PORT:?PYHSS_API_PORT is required}"
api_base=${PYHSS_API_BASE:-http://${PYHSS_API_BIND}:${PYHSS_API_PORT}}

usage() {
    printf 'Usage: %s [--dry-run|--apply]\n' "$0"
}

while (($#)); do
    case "$1" in
        --dry-run|--apply) action=$1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

: "${SUBSCRIBER_K:?SUBSCRIBER_K is required}"
: "${SUBSCRIBER_OPC:?SUBSCRIBER_OPC is required}"
: "${SUBSCRIBER_AMF:?SUBSCRIBER_AMF is required}"
: "${UE1_IMSI:?UE1_IMSI is required}"
: "${UE2_IMSI:?UE2_IMSI is required}"
: "${UE1_MSISDN:?UE1_MSISDN is required}"
: "${UE2_MSISDN:?UE2_MSISDN is required}"
: "${IMS_DOMAIN:?IMS_DOMAIN is required}"
: "${SCSCF_SIP_PORT:?SCSCF_SIP_PORT is required}"
: "${IMS_DNN:?IMS_DNN is required}"

profiles=(
    "$UE1_IMSI $UE1_MSISDN"
    "$UE2_IMSI $UE2_MSISDN"
)

if [[ "$action" == '--dry-run' ]]; then
    printf 'Validated IMS subscriber plan (no API calls):\n'
    for entry in "${profiles[@]}"; do
        read -r imsi msisdn <<< "$entry"
        printf '  IMSI %s -> IMPI %s@%s, IMPU sip:%s@..., MSISDN %s\n' \
            "$imsi" "$imsi" "$IMS_DOMAIN" "$msisdn" "$msisdn"
    done
    exit 0
fi

command -v curl >/dev/null 2>&1 || { printf 'ERROR: curl is unavailable\n' >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { printf 'ERROR: python3 is unavailable\n' >&2; exit 2; }

# PyHSS Cx authentication resolves the IMS subscriber first, then follows the
# regular subscriber -> AuC relation to build the authentication vector.  The
# APN itself is not used by Open5GS in this lab, but PyHSS requires the foreign
# key for every regular subscriber row.
apn_id=$(curl -fsS "$api_base/apn/list?page=0&page_size=200" \
    | python3 -c 'import json,sys
rows=json.load(sys.stdin)
print(next((row["apn_id"] for row in rows if row.get("apn")==sys.argv[1]), ""))' "$IMS_DNN")
if [[ -z "$apn_id" ]]; then
    curl -fsS -X PUT -H 'Content-Type: application/json' \
        -d "{\"apn\":\"$IMS_DNN\",\"ip_version\":0,\"apn_ambr_dl\":1000000,\"apn_ambr_ul\":1000000,\"qci\":9,\"arp_priority\":8,\"arp_preemption_capability\":false,\"arp_preemption_vulnerability\":true}" \
        "$api_base/apn/" >/dev/null
    apn_id=$(curl -fsS "$api_base/apn/list?page=0&page_size=200" \
        | python3 -c 'import json,sys
rows=json.load(sys.stdin)
print(next(row["apn_id"] for row in rows if row.get("apn")==sys.argv[1]))' "$IMS_DNN")
fi

for entry in "${profiles[@]}"; do
    read -r imsi msisdn <<< "$entry"

    auc_payload=$(mktemp /tmp/auc.XXXXXX.json)
    ims_payload=$(mktemp /tmp/ims.XXXXXX.json)
    response=$(mktemp /tmp/resp.XXXXXX.json)
    trap 'rm -f "$auc_payload" "$ims_payload" "$response"' EXIT

    cat > "$auc_payload" <<EOF
{"ki": "$SUBSCRIBER_K", "opc": "$SUBSCRIBER_OPC", "amf": "$SUBSCRIBER_AMF", "sqn": 96, "imsi": "$imsi"}
EOF

    cat > "$ims_payload" <<EOF
{
  "imsi": "$imsi",
  "msisdn": "$msisdn",
  "ifc_path": "default_ifc.xml",
  "sh_template_path": "default_sh_user_data.xml",
  "scscf": "sip:scscf.${IMS_DOMAIN}:${SCSCF_SIP_PORT}",
  "scscf_realm": "${IMS_DOMAIN}",
  "scscf_peer": "scscf.${IMS_DOMAIN}",
  "pcscf_realm": "${IMS_DOMAIN}",
  "pcscf_peer": "pcscf.${IMS_DOMAIN}"
}
EOF

    code=$(curl -sS -o "$response" -w '%{http_code}' "$api_base/auc/imsi/$imsi")
    # PyHSS answers 200 with a JSON null body for a missing record.
    if [[ "$code" == '200' && "$(cat "$response")" != 'null' ]]; then
        auc_id=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["auc_id"])' < "$response")
        curl -fsS -X PATCH -H 'Content-Type: application/json' \
            -d @"$auc_payload" "$api_base/auc/$auc_id" > /dev/null
        printf 'Updated AuC entry %s for IMSI %s\n' "$auc_id" "$imsi"
    else
        curl -fsS -X PUT -H 'Content-Type: application/json' \
            -d @"$auc_payload" "$api_base/auc/" > /dev/null
        auc_id=$(curl -fsS "$api_base/auc/imsi/$imsi" \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["auc_id"])')
        printf 'Created AuC entry for IMSI %s\n' "$imsi"
    fi

    subscriber_id=$(curl -fsS "$api_base/subscriber/list?page=0&page_size=200" \
        | python3 -c 'import json,sys
data=json.load(sys.stdin); target=sys.argv[1]
print(next((row["subscriber_id"] for row in data if row.get("imsi")==target), ""))' "$imsi")
    subscriber_payload=$(mktemp /tmp/subscriber.XXXXXX.json)
    cat > "$subscriber_payload" <<EOF
{"imsi":"$imsi","enabled":true,"auc_id":$auc_id,"default_apn":$apn_id,"apn_list":"$apn_id","msisdn":"$msisdn","ue_ambr_dl":1000000,"ue_ambr_ul":1000000,"nam":2,"roaming_enabled":false,"subscribed_rau_tau_timer":600}
EOF
    if [[ -n "$subscriber_id" ]]; then
        curl -fsS -X PATCH -H 'Content-Type: application/json' \
            -d @"$subscriber_payload" "$api_base/subscriber/$subscriber_id" >/dev/null
        printf 'Updated subscriber %s for IMSI %s\n' "$subscriber_id" "$imsi"
    else
        curl -fsS -X PUT -H 'Content-Type: application/json' \
            -d @"$subscriber_payload" "$api_base/subscriber/" >/dev/null
        printf 'Created subscriber for IMSI %s\n' "$imsi"
    fi
    rm -f "$subscriber_payload"

    ims_id=$(curl -fsS "$api_base/ims_subscriber/list?page=0&page_size=200" \
        | python3 -c 'import json,sys
data = json.load(sys.stdin)
target = sys.argv[1]
matches = [row["ims_subscriber_id"] for row in data if row.get("imsi") == target]
print(matches[0] if matches else "")' "$imsi")
    if [[ -n "$ims_id" ]]; then
        curl -fsS -X PATCH -H 'Content-Type: application/json' \
            -d @"$ims_payload" "$api_base/ims_subscriber/$ims_id" > /dev/null
        printf 'Updated IMS subscriber %s for IMSI %s\n' "$ims_id" "$imsi"
    else
        curl -fsS -X PUT -H 'Content-Type: application/json' \
            -d @"$ims_payload" "$api_base/ims_subscriber/" > /dev/null
        printf 'Created IMS subscriber for IMSI %s\n' "$imsi"
    fi
done

printf 'Provisioned the two IMS subscriber records in %s.\n' "$api_base"
