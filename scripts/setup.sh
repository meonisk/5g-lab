#!/usr/bin/env bash
# Установка и запуск одной командой: модели OPUS-MT для CPU-режима (один раз),
# затем scripts/start.py. Режим — AI_MODE из lab.env или --mode в аргументах;
# все аргументы передаются start.py как есть.
#   scripts/setup.sh                  # режим из lab.env (compact)
#   scripts/setup.sh --mode baseline  # Qwen, модели OPUS-MT не нужны
# Системный Python не меняется: uv и конвертер живут в игнорируемом local/.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
set -a
# shellcheck source=../app/config/lab.env
source app/config/lab.env
set +a

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

mode=${AI_MODE:-baseline}
previous=''
for argument in "$@"; do
    [[ $previous == --mode ]] && mode=$argument
    [[ $argument == --mode=* ]] && mode=${argument#--mode=}
    previous=$argument
done

command -v docker >/dev/null || die "нет docker"
docker info >/dev/null 2>&1 || die "docker недоступен этому пользователю: docker info"
command -v python3 >/dev/null || die "нет python3"

models=local/models/opus-mt
have_models() { [[ -f $models/ru-en/manifest.json && -f $models/en-ru/manifest.json ]]; }

# baseline переводит через Qwen; остальные режимы — через две модели OPUS-MT.
# Конвертер требует PyTorch и Python 3.11: uv ставит их отдельно от системы
# (PEP 668 запрещает pip install --user в системный Python Ubuntu).
if [[ $mode != baseline ]] && ! have_models; then
    echo "OPUS-MT для режима $mode: подготовка (один раз, нужен интернет)"
    uv=local/uv-venv/bin/uv
    if [[ ! -x $uv ]]; then
        python3 -m venv local/uv-venv || die "python3 -m venv не работает: sudo apt install python3-venv"
        local/uv-venv/bin/python -m pip install --quiet uv==0.9.5
    fi
    [[ -x local/opus-venv/bin/python ]] || "$uv" venv --python 3.11 local/opus-venv
    "$uv" pip install --python local/opus-venv/bin/python ctranslate2==4.8.2 \
        transformers==4.57.6 sentencepiece==0.2.2 torch==2.10.0 --torch-backend cpu
    local/opus-venv/bin/python scripts/prepare_translation_models.py
    have_models || die "модели OPUS-MT не появились в $models"
fi

exec python3 scripts/start.py "$@"
