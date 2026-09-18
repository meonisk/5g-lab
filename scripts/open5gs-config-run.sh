#!/bin/sh
set -eu

source_config=$1
rendered_config=$2
shift 2
/lab/render-open5gs-config.sh "$source_config" "$rendered_config"
exec /entrypoint.sh "$@"
