#!/usr/bin/env bash
# Compatibility entry point; edit tests/integration instead.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec bash "$root/tests/integration/verify-ims.sh" "$@"
