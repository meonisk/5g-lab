#!/bin/bash
# lab-docker UPF entrypoint wrapper: create the second tunnel device for the
# env-defined ims DNN on ogstun2 before delegating to the gradiant entrypoint,
# which handles the internet DNN, forwarding and its NAT rule.
# The ims pool deliberately has NO NAT and no Internet path.
set -e
: "${IMS_UE_GATEWAY_CIDR:?IMS_UE_GATEWAY_CIDR is required}"

/lab/render-open5gs-config.sh /opt/open5gs/etc/open5gs/upf.yaml /tmp/upf.yaml

ip tuntap add name ogstun mode tun 2>/dev/null || true
ip tuntap add name ogstun2 mode tun 2>/dev/null || true
ip addr replace "$IMS_UE_GATEWAY_CIDR" dev ogstun2
ip link set ogstun2 up

exec /entrypoint.sh open5gs-upfd -c /tmp/upf.yaml
