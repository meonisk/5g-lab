#!/usr/bin/env bash
# Test SIP client: PJSUA registers to our P-CSCF straight from the core bridge
# (SIP Digest, no 5G UE) and is controlled through the FIFO /tmp/pjsua-control.
set -Eeuo pipefail

: "${IMSI:?IMSI is required}"
: "${IMS_DIGEST_PASSWORD:?IMS_DIGEST_PASSWORD is required}"
: "${SIP_UE_IP:?SIP_UE_IP is required}"
: "${IMS_DOMAIN:?IMS_DOMAIN is required}"
: "${PCSCF_IP:?PCSCF_IP is required}"
: "${PCSCF_SIP_PORT:?PCSCF_SIP_PORT is required}"
: "${SIP_UE_AUTO_ANSWER:?SIP_UE_AUTO_ANSWER is required}"
: "${SIP_UE_AUTO_CONFERENCE:?SIP_UE_AUTO_CONFERENCE is required}"
: "${SIP_UE_TEST_UTTERANCE:?SIP_UE_TEST_UTTERANCE is required}"
: "${SIP_UE_PLAYBACK_FILE:=}"
: "${SIP_UE_CODEC:?SIP_UE_CODEC is required}"
: "${TTS_VOICE:?TTS_VOICE is required}"
: "${TTS_RATE:?TTS_RATE is required}"

# Speech source: a mounted synthetic WAV for dialogue tests, otherwise one
# Russian phrase rendered locally by espeak-ng.
playback=/tmp/ims-agent-test.wav
if [[ -n "$SIP_UE_PLAYBACK_FILE" ]]; then
    [[ "$SIP_UE_PLAYBACK_FILE" == /* ]] || SIP_UE_PLAYBACK_FILE="/$SIP_UE_PLAYBACK_FILE"
    [[ -s "$SIP_UE_PLAYBACK_FILE" ]] || { echo "ERROR: playback fixture is missing: $SIP_UE_PLAYBACK_FILE" >&2; exit 1; }
    playback=$SIP_UE_PLAYBACK_FILE
    printf 'Using mounted playback fixture: %s\n' "$playback"
else
    espeak-ng -v "$TTS_VOICE" -s "$TTS_RATE" -w "$playback" "$SIP_UE_TEST_UTTERANCE"
fi

control=/tmp/pjsua-control
rm -f "$control"
mkfifo "$control"
exec 3<>"$control"

conference_arguments=()
if [[ "$SIP_UE_AUTO_CONFERENCE" == 1 ]]; then
    conference_arguments=(--auto-conf)
fi

# Line-buffered output keeps SIP events visible in docker logs while the dialog
# is live; the integration tests read them from there.
exec stdbuf -oL -eL pjsua \
    --log-level=4 --app-log-level=4 --null-audio --no-tcp --use-compact-form \
    --clock-rate=8000 --snd-clock-rate=8000 \
    --dis-codec='*' --add-codec="$SIP_UE_CODEC" \
    --play-file="$playback" "${conference_arguments[@]}" \
    --auto-answer="$SIP_UE_AUTO_ANSWER" \
    --id "sip:${IMSI}@${IMS_DOMAIN}" \
    --registrar "sip:${IMS_DOMAIN}" \
    --proxy "sip:${PCSCF_IP}:${PCSCF_SIP_PORT};transport=udp;lr" \
    --realm "$IMS_DOMAIN" \
    --username "${IMSI}@${IMS_DOMAIN}" \
    --password "$IMS_DIGEST_PASSWORD" \
    --reg-timeout=3600 \
    --ip-addr="$SIP_UE_IP" \
    <&3
