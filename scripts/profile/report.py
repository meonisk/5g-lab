"""Отчёт профилирования: report.json и report.md из файлов прогона local/profile/<UTC>/.

python3 scripts/profile/report.py DIR                 # отчёт
python3 scripts/profile/report.py DIR --meta --rounds N --options "..."   # meta.json
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts")]
from latency import summary  # noqa: E402
from verdict import STAGES, bottleneck, evaluate  # noqa: E402

SCENARIOS = ("S1", "S2", "S3", "S4", "S5")
STAGE_KEYS = ("vad_wait_ms", "speech_plus_pause_ms", "queue_wait_ms", "stt_ms",
              "translation_ms", "tts_synthesis_ms", "speech_end_to_reply_rtp_ms")  # fmt: skip
STAGE_NAMES = {
    "vad_wait_ms": "ожидание паузы (VAD)",
    "speech_plus_pause_ms": "речь + пауза",
    "queue_wait_ms": "очередь",
    "stt_ms": "распознавание",
    "translation_ms": "перевод",
    "tts_synthesis_ms": "синтез",
    "speech_end_to_reply_rtp_ms": "итог: конец речи -> первый RTP",
}


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def reference_profile():
    """Эталон качества — режим compact: его модель Whisper и потоки STT."""
    compact = json.loads((ROOT / "app/config/ai-profiles.json").read_text(encoding="utf-8"))
    compact = compact["compact"]
    return {"model": compact["AI_MODEL_SIZE"], "threads": int(compact["AI_STT_CPU_THREADS"])}


def scenario_entry(data, name):
    if data is None:
        return {"id": name, "status": "skip", "reason": "сценарий не запускался"}
    rounds = data.get("rounds") or []
    stages = {key: summary([row.get(key) for row in rounds]) for key in STAGE_KEYS}
    return {
        "id": name,
        "title": data.get("title", ""),
        "status": data.get("status", "fail"),
        "reason": data.get("reason", ""),
        "rounds": len(rounds),
        "errors": data.get("errors", []),
        "cpu": data.get("cpu"),
        "stages": {key: value for key, value in stages.items() if value},
    }


def build(folder, reference):
    meta = load(folder / "meta.json") or {}
    scenarios = {name: scenario_entry(load(folder / f"scenarios/{name}.json"), name)
                 for name in SCENARIOS}  # fmt: skip
    sweeps = {
        load_name: load(folder / f"sweep-{load_name}.json") for load_name in ("idle", "rfsim")
    }
    rows = [row for sweep in sweeps.values() if sweep for row in sweep.get("rows", [])]

    # Синтез и очередь — из звонка под той же нагрузкой, что и оцениваемый перебор.
    rfsim = any(row["load"] == "rfsim" for row in rows)
    order = ("S4", "S5", "S3") if rfsim else ("S3", "S4", "S5")
    source = next((n for n in order if scenarios[n]["status"] == "done" and scenarios[n]["stages"]),
                  None)  # fmt: skip
    medians = {}
    if source:
        medians = {key: value["median"] for key, value in scenarios[source]["stages"].items()}
    context = {"queue_ms": medians.get("queue_wait_ms"), "tts_ms": medians.get("tts_synthesis_ms"),
               "translation_ms": medians.get("translation_ms")}  # fmt: skip
    return {
        "meta": meta,
        "scenarios": scenarios,
        "sweep": sweeps,
        "verdict": {
            "source": source,
            "context": context,
            "bottleneck": bottleneck(medians, scenarios[source]["cpu"] if source else None),
            "evaluation": evaluate(rows, context, reference),
        },
    }


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + [
        "| " + " | ".join("—" if c is None else str(c) for c in row) + " |" for row in rows
    ]


def render_verdict(result):
    lines, choice = ["## Итог", ""], result["evaluation"]
    neck = result["bottleneck"]
    if neck["stage"]:
        lines.append(f"- Узкое место ({result['source']}): {STAGE_NAMES[neck['stage']]} — "
                     f"медиана {neck['stage_ms']} мс, {round(neck['share'] * 100)}% этапов.")  # fmt: skip
    else:
        lines.append("- Узкое место: нет сценария со звонком — этапы не измерены.")
    lines += [f"- CPU: {message}" for message in neck["cpu"]] or ["- CPU: узлов у предела нет."]
    load_name = "при работающем rfsim" if choice["load"] == "rfsim" else "при простое"
    lines.append(f"- Варианты ≤ {choice['limit_ms']} мс {load_name}, качество не хуже compact "
                 f"более чем на {choice['margin_pp']:g} п.п.:")  # fmt: skip
    context = result["context"]
    if result["source"]:
        lines.append(f"- Оценка = пауза + STT и перевод из перебора + синтез {context['tts_ms']} мс"
                     f" и очередь {context['queue_ms']} мс (медианы {result['source']}).")  # fmt: skip
    else:
        lines.append("- Оценка = пауза + STT и перевод из перебора; синтез и очередь не измерены "
                     "(нет сценария со звонком) — оценка занижена.")  # fmt: skip
    if choice["note"]:
        lines.append(f"- Примечание: {choice['note']}.")
    if not choice["candidates"]:
        return lines + ["", "**перебор не дал вариантов — оценить настройки нельзя.**", ""]
    if not choice["fits"]:
        return lines + ["", "**ни одна конфигурация не укладывается в 2000 мс.**", ""]
    rows = [(c["model"], c["threads"], c["silence_ms"], c["estimate_ms"], _pct(c["accuracy"]),
             c["quality_drop_pp"], c.get("cpu_ms")) for c in choice["fits"]]  # fmt: skip
    header = ("модель", "потоки STT", "пауза, мс", "оценка, мс", "качество, %", "−п.п.", "CPU, мс")
    return lines + [""] + table(header, rows) + [""]


def _pct(value):
    return "—" if value is None else round(value * 100, 1)


def render_cpu(scenarios):
    done = [s for s in scenarios.values() if s.get("cpu")]
    nodes = sorted(
        {node for s in done for node in s["cpu"]["nodes"]}, key=lambda n: (n != "host", n)
    )
    rows = []
    for node in nodes:
        cells = []
        for s in done:
            value = s["cpu"]["nodes"].get(node)
            cells.append(f"{value['mean']} / {value['p95']}" if value else "—")
        rows.append((node, *cells))
    lines = ["## CPU по сценариям", "", "Занятые ядра, среднее / p95 (1.0 = одно ядро).", ""]
    return lines + (table(("узел", *[s["id"] for s in done]), rows) if done else ["нет данных"])


def render_stages(scenarios):
    done = [s for s in scenarios.values() if s.get("stages")]
    rows = []
    for key in STAGE_KEYS:
        cells = []
        for s in done:
            value = s["stages"].get(key)
            cells.append(f"{value['median']} ({value['min']}–{value['max']})" if value else "—")
        rows.append((STAGE_NAMES[key], *cells))
    lines = ["", "## Задержка по этапам", "", "Медиана (мин–макс), мс, по раундам.", ""]
    return lines + (table(("этап", *[s["id"] for s in done]), rows) if done else ["нет данных"])


def render_sweep(sweeps):
    lines = ["", "## Перебор настроек AI", ""]
    for load_name, sweep in sweeps.items():
        if not sweep:
            lines.append(f"- {load_name}: не запускался.")
            continue
        if sweep.get("status") != "done":
            lines.append(f"- {load_name}: SKIP — {sweep.get('reason', '')}")
            continue
        for model, info in sorted(sweep.get("models", {}).items()):
            if info.get("status") != "ok":
                lines.append(f"- {load_name}, {model}: {info.get('reason', '')}")
        rows = [(r["model"], r["threads"], r["streaming"], r["stt_ms"], r["translation_ms"],
                 _pct(r["accuracy"]), r["cpu_ms"], r.get("first_partial_ms"))
                for r in sweep.get("rows", [])]  # fmt: skip
        header = ("модель", "потоки", "поток.", "STT, мс", "перевод, мс", "качество, %",
                  "CPU, мс", "1-й частичный, мс")  # fmt: skip
        lines += ["", f"### {load_name}", ""] + table(header, rows) + [""]
    return lines


def render(result):
    meta, lines = result["meta"], []
    lines.append(f"# Профиль стенда {meta.get('created', '')}")
    lines.append("")
    for key in ("host", "ncpu", "cgroup", "ai_mode", "commit", "rounds", "options"):
        if meta.get(key) not in (None, ""):
            lines.append(f"- {key}: {meta[key]}")
    lines.append("")
    lines += render_verdict(result["verdict"])
    lines += ["## Сценарии", ""]
    for s in result["scenarios"].values():
        status = s["status"].upper()
        detail = f" — {s['reason']}" if s.get("reason") else ""
        lines.append(f"- {s['id']} {s.get('title', '')}: {status}{detail}")
    lines.append("")
    lines += render_cpu(result["scenarios"])
    lines += render_stages(result["scenarios"])
    lines += render_sweep(result["sweep"])
    lines += ["", f"Этапы для оценки: {', '.join(STAGES)}; подробности — report.json."]
    return "\n".join(lines) + "\n"


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          check=False).stdout.strip()  # fmt: skip


def write_meta(folder, rounds, options):
    meta = {
        "created": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "ncpu": os.cpu_count(),
        "cgroup": "v2" if Path("/sys/fs/cgroup/cgroup.controllers").exists() else "v1",
        "ai_mode": os.environ.get("AI_MODE", ""),
        "commit": f"{git('rev-parse', '--abbrev-ref', 'HEAD')} {git('log', '-1', '--format=%h %s')}",
        "rounds": rounds,
        "options": options,
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    print(f"META: ncpu {meta['ncpu']}, cgroup {meta['cgroup']}, AI_MODE {meta['ai_mode']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--meta", action="store_true", help="записать meta.json и выйти")
    parser.add_argument("--rounds", type=int, default=0)
    parser.add_argument("--options", default="")
    args = parser.parse_args()
    if args.meta:
        return write_meta(args.folder, args.rounds, args.options)
    result = build(args.folder, reference_profile())
    text = json.dumps(result, ensure_ascii=False, indent=2)
    (args.folder / "report.json").write_text(text, encoding="utf-8")
    (args.folder / "report.md").write_text(render(result), encoding="utf-8")
    print(f"REPORT: {args.folder / 'report.md'}")


if __name__ == "__main__":
    main()
