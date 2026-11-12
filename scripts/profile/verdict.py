"""Итог профилирования: какие настройки AI укладываются в 2 с и что сейчас узкое место.

Оценка задержки варианта = пауза конца фразы + распознавание + перевод + синтез +
очередь. Распознавание и перевод — из перебора на записанной фразе, синтез и очередь —
из сценариев со звонком. Вариант «укладывается», если оценка ≤ 2000 мс и качество не
хуже эталона compact (та же модель и потоки) более чем на 10 п.п.
"""

LIMIT_MS = 2000
MARGIN = 0.10
SILENCES_MS = (700, 500, 300)
STAGES = ("vad_wait_ms", "queue_wait_ms", "stt_ms", "translation_ms", "tts_synthesis_ms")


def _reference(rows, reference):
    for row in rows:
        if (row["model"], row["threads"], row["streaming"]) == (
            reference["model"], reference["threads"], 0,
        ):  # fmt: skip
            return row
    return None


def evaluate(rows, context, reference, silences=SILENCES_MS, limit_ms=LIMIT_MS, margin=MARGIN):
    """Кандидаты (вариант × пауза), до трёх укладывающихся — по возрастанию CPU."""
    load = "rfsim" if any(row["load"] == "rfsim" for row in rows) else "idle"
    rows = [row for row in rows if row["load"] == load]
    notes = [] if load == "rfsim" else ["rfsim недоступен: оценка при простое, без нагрузки rfsim"]
    base = _reference(rows, reference)
    if base is None or base.get("accuracy") is None:
        notes.append(f"нет эталона compact ({reference['model']}, {reference['threads']} потока)"
                     ": качество не с чем сравнить")  # fmt: skip

    candidates = []
    for row in rows:
        if row["streaming"] or row.get("stt_ms") is None:
            continue
        translation = row.get("translation_ms")
        if translation is None:
            translation = context.get("translation_ms") or 0
        for silence in silences:
            estimate = (silence + row["stt_ms"] + translation + (context.get("tts_ms") or 0)
                        + (context.get("queue_ms") or 0))  # fmt: skip
            drop = None
            if base and base.get("accuracy") is not None and row.get("accuracy") is not None:
                drop = round((base["accuracy"] - row["accuracy"]) * 100, 1)
            fits = estimate <= limit_ms and drop is not None and drop <= margin * 100
            candidates.append({**row, "silence_ms": silence, "estimate_ms": round(estimate, 1),
                               "quality_drop_pp": drop, "fits": fits})  # fmt: skip

    # Один вариант на (модель, потоки): самая длинная пауза, которая ещё укладывается, —
    # короткая пауза режет фразы на паузах дыхания.
    best = {}
    for candidate in candidates:
        key = (candidate["model"], candidate["threads"])
        if candidate["fits"] and (
            key not in best or candidate["silence_ms"] > best[key]["silence_ms"]
        ):
            best[key] = candidate
    fits = sorted(best.values(), key=lambda c: (c.get("cpu_ms") or 0, c["estimate_ms"]))[:3]
    return {
        "load": load,
        "limit_ms": limit_ms,
        "margin_pp": margin * 100,
        "reference": base,
        "candidates": candidates,
        "fits": fits,
        "note": "; ".join(notes),
    }


def bottleneck(stages, cpu):
    """Самый долгий этап (медианы сценария) и узлы CPU у предела лимита или хоста."""
    present = {name: stages[name] for name in STAGES if stages.get(name) is not None}
    total = sum(present.values())
    stage = max(present, key=present.get) if present else None
    messages = []
    nodes = (cpu or {}).get("nodes", {})
    for name, limit in sorted((cpu or {}).get("limits", {}).items()):
        p95 = (nodes.get(name) or {}).get("p95")
        if limit and p95 is not None and p95 >= 0.9 * limit:
            messages.append(f"{name}: p95 {p95} ядра при лимите {limit} — упирается в лимит CPU")
    host = (nodes.get("host") or {}).get("p95")
    if host is not None and cpu.get("ncpu") and host >= 0.9 * cpu["ncpu"]:
        messages.append(f"хост: p95 {host} из {cpu['ncpu']} ядер — CPU хоста насыщен")
    return {
        "stage": stage,
        "stage_ms": present.get(stage),
        "share": round(present[stage] / total, 2) if stage and total else None,
        "cpu": messages,
    }
