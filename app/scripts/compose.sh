#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec docker compose --env-file "$root/lab.env" --env-file "$root/secrets/ims.env" -f "$root/docker-compose.yml" "$@"
