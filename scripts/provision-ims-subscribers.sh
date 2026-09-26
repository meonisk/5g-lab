#!/usr/bin/env bash
# Provision the two env-defined IMS subscribers through the PyHSS REST API.
# Key material comes from the ignored local/secrets/ims.env file.
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

: "${UE1_IMSI:?UE1_IMSI is required}"
: "${UE2_IMSI:?UE2_IMSI is required}"
: "${UE1_MSISDN:?UE1_MSISDN is required}"
: "${UE2_MSISDN:?UE2_MSISDN is required}"
: "${IMS_DOMAIN:?IMS_DOMAIN is required}"
: "${SCSCF_SIP_PORT:?SCSCF_SIP_PORT is required}"
: "${IMS_DNN:?IMS_DNN is required}"

profiles=(
    "1 $UE1_IMSI $UE1_MSISDN"
    "2 $UE2_IMSI $UE2_MSISDN"
)

resolve_ims_keys() {
    local ue=$1 k_name opc_name amf_name
    k_name="UE${ue}_IMS_K"
    opc_name="UE${ue}_IMS_OPC"
    amf_name="UE${ue}_IMS_AMF"
    if [[ -n ${!k_name:-} || -n ${!opc_name:-} || -n ${!amf_name:-} ]]; then
        ims_k=${!k_name:-}
        ims_opc=${!opc_name:-}
        ims_amf=${!amf_name:-}
    else
        ims_k=${SUBSCRIBER_K:-}
        ims_opc=${SUBSCRIBER_OPC:-}
        ims_amf=${SUBSCRIBER_AMF:-}
    fi
    [[ "$ims_k" =~ ^[0-9a-fA-F]{32}$ && "$ims_opc" =~ ^[0-9a-fA-F]{32}$ && "$ims_amf" =~ ^[0-9a-fA-F]{4}$ ]] || {
        printf 'ERROR: incomplete IMS AKA credential set for UE%s\n' "$ue" >&2
        return 2
    }
}

for entry in "${profiles[@]}"; do
    read -r ue _ <<< "$entry"
    resolve_ims_keys "$ue"
done

if [[ "$action" == '--dry-run' ]]; then
    printf 'Validated IMS subscriber plan (no API calls):\n'
    for entry in "${profiles[@]}"; do
        read -r _ imsi msisdn <<< "$entry"
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
    read -r ue imsi msisdn <<< "$entry"
    resolve_ims_keys "$ue"

    auc_payload=$(mktemp /tmp/auc.XXXXXX.json)
    ims_payload=$(mktemp /tmp/ims.XXXXXX.json)
    response=$(mktemp /tmp/resp.XXXXXX.json)
    trap 'rm -f "$auc_payload" "$ims_payload" "$response"' EXIT

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
    if [[ "$code" != '200' ]]; then
        printf 'ERROR: AuC lookup for IMSI %s returned HTTP %s\n' "$imsi" "$code" >&2
        exit 1
    fi
    # PyHSS answers 200 with a JSON null body for a missing record.
    auc_id=$(python3 -c 'import json,sys
record=json.load(sys.stdin)
print("" if record is None else record["auc_id"])' < "$response")
    if [[ -n "$auc_id" ]]; then
        # PyHSS may omit ki/opc from REST. The validator falls back to a
        # read-only database query and binds keys to this AuC ID and IMSI.
        peer_imsi=$UE1_IMSI
        [[ "$imsi" == "$UE1_IMSI" ]] && peer_imsi=$UE2_IMSI
        EXPECTED_IMS_K="$ims_k" EXPECTED_IMS_OPC="$ims_opc" EXPECTED_IMS_AMF="$ims_amf" \
            python3 "$script_dir/validate_ims_auc.py" --record "$response" \
                --imsi "$imsi" --auc-id "$auc_id" --peer-imsi "$peer_imsi" || {
            printf 'ERROR: IMS AKA mismatch for IMSI %s; explicit migration required\n' "$imsi" >&2
            exit 1
        }
        # Never PATCH an existing AuC: its SQN advances during authentication,
        # and overwriting its key material would invalidate the active UE.
        printf 'Preserved AuC entry %s for IMSI %s\n' "$auc_id" "$imsi"
    else
        cat > "$auc_payload" <<EOF
{"ki": "$ims_k", "opc": "$ims_opc", "amf": "$ims_amf", "sqn": 96, "imsi": "$imsi"}
EOF
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
