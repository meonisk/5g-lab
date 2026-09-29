#!/usr/bin/env bash
# Reapply routing on every UPF boot, including docker restart and daemon recovery.
set -Eeuo pipefail
bash /lab/oai-upf-network.sh &
exec sh /openair-upf/bin/entrypoint.sh /openair-upf/bin/oai_upf -c /openair-upf/etc/config.yaml -o
