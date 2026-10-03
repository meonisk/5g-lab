#!/usr/bin/env bash
# Восстанавливаем маршруты при каждом запуске UPF, включая перезапуск Docker.
set -Eeuo pipefail
bash /lab/oai-upf-network.sh &
exec sh /openair-upf/bin/entrypoint.sh /openair-upf/bin/oai_upf -c /openair-upf/etc/config.yaml -o
