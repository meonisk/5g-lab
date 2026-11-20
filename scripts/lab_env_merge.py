"""Перенос локальных правок app/config/lab.env в версию из Git.

На стенде lab.env правят руками (интерфейс, шлюз, адреса партнёрской сети),
а ветка тоже меняет этот файл. Перед переключением ветки сохраните две копии:
исходную из Git (base) и локальную (mine). После переключения:

  python3 scripts/lab_env_merge.py local/lab.env.base local/lab.env.mine

Слияние по ключам: локальное значение переносится, если ветка этот ключ не
меняла; если меняли обе стороны, остаётся значение ветки (например, PLMN SIM)
и печатается предупреждение. Значения не печатаются.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app/config/lab.env"


def parse(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value
    return values


def merge(base: str, mine: str, theirs: str) -> tuple[str, list[str], list[str]]:
    """Вернуть новый текст, перенесённые ключи и конфликты (ключи обеих сторон)."""
    base_values, mine_values, their_values = parse(base), parse(mine), parse(theirs)
    local = {k: v for k, v in mine_values.items() if base_values.get(k) != v}

    carried, conflicts, lines = [], [], []
    for line in theirs.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("#") else ""
        if key in local and their_values[key] != local[key]:
            if their_values[key] != base_values.get(key, their_values[key]):
                conflicts.append(key)
            else:
                line = f"{key}={local[key]}"
                carried.append(key)
        lines.append(line)

    # Ключи, добавленные только на стенде, сохраняются в конце файла.
    added = [k for k in local if k not in their_values and k not in base_values]
    if added:
        lines += ["", "# Local stand settings carried over by scripts/lab_env_merge.py"]
        lines += [f"{key}={local[key]}" for key in added]
        carried += added
    return "\n".join(lines) + "\n", carried, conflicts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("base", type=Path, help="lab.env из Git до переключения ветки")
    parser.add_argument("mine", type=Path, help="локальный lab.env до переключения ветки")
    args = parser.parse_args(argv)

    base = args.base.read_text(encoding="utf-8")
    mine = args.mine.read_text(encoding="utf-8")
    theirs = TARGET.read_text(encoding="utf-8")
    text, carried, conflicts = merge(base, mine, theirs)

    TARGET.write_bytes(text.encode("utf-8"))
    print(f"lab.env: перенесено локальных значений: {len(carried)} ({', '.join(carried) or '—'})")
    for key in conflicts:
        print(f"WARN: {key} изменён и на стенде, и в ветке; оставлено значение ветки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
