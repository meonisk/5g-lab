#!/bin/sh
# lab-docker dns entrypoint: route back to the UE ims pool via the UPF
# (the ims DNN has no NAT), render the env-backed zone, then serve it.
set -eu
for name in IMS_UE_CIDR UPF_IP DNS_IP IMS_DOMAIN PCSCF_IP ICSCF_IP SCSCF_IP PYHSS_IP SIP_AS_IP RTPENGINE_IP VOICE_AGENT_IP ICSCF_SIP_PORT SCSCF_SIP_PORT LOOPBACK_IP DNS_UPSTREAM_PRIMARY DNS_UPSTREAM_SECONDARY; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || { echo "ERROR: missing $name" >&2; exit 2; }
done
ip route replace "$IMS_UE_CIDR" via "$UPF_IP"
cp /etc/dnsmasq.d/ims.conf /tmp/ims.conf
for name in DNS_IP IMS_DOMAIN PCSCF_IP ICSCF_IP SCSCF_IP PYHSS_IP SIP_AS_IP RTPENGINE_IP VOICE_AGENT_IP ICSCF_SIP_PORT SCSCF_SIP_PORT LOOPBACK_IP DNS_UPSTREAM_PRIMARY DNS_UPSTREAM_SECONDARY; do
    eval "value=\${$name}"
    sed "s|__${name}__|$value|g" /tmp/ims.conf > /tmp/ims.conf.next
    mv /tmp/ims.conf.next /tmp/ims.conf
done
if grep -q '__[A-Z0-9_][A-Z0-9_]*__' /tmp/ims.conf; then
    echo 'ERROR: unresolved IMS DNS placeholder' >&2
    exit 2
fi
exec dnsmasq -k --conf-file=/tmp/ims.conf
