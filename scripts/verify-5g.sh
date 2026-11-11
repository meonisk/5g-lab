#!/usr/bin/env bash
# Проверка через 5G одной командой: радио OAI rfsim, тест verify-5g-ue.sh, затем
# радио останавливается всегда, даже если тест упал. Стенд должен быть запущен
# (scripts/setup.sh). Журналы — в local/rfsim/.
set -uo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

"$root/scripts/rfsim.sh" up && bash "$root/app/tests/integration/verify-5g-ue.sh"
status=$?
"$root/scripts/rfsim.sh" down
exit "$status"
