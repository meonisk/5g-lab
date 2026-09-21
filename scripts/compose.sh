#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec docker compose --env-file "$root/app/config/lab.env" --env-file "$root/local/secrets/ims.env" -f "$root/docker-compose.yml" "$@"
