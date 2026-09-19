"""Join safe service events and file-relative speech intervals without inventing synchronization."""

import json
import re
from datetime import datetime


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def clock(seconds):
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes):02d}:{remainder:06.3f}"


def group_phrases(segments):
    """Combine adjacent ASR segments, not sentences separated by long fixture silence."""
    phrases = []
    for segment in segments:
        if phrases and segment["start"] - phrases[-1]["end"] <= 1:
            phrases[-1]["text"] += " " + segment["text"]
            phrases[-1]["end"] = segment["end"]
        else:
            phrases.append({key: segment[key] for key in ("start", "end", "text")})
    return phrases


def dialogue_summary(experiment, transcript, events):
    """Ordered association is valid only for this four-turn synthetic fixture."""
    result = json.loads((experiment / "metadata/test-result.json").read_text(encoding="utf-8-sig"))
    lines = [
        "## Разговор по репликам и этапам",
        "",
        "Текст ниже получен повторным ASR. Соответствие по порядку реплик, не по сохранённому reply_id.",
        "Общие времена с ≈ восстановлены из окончания TTS в логе и длительностей исходного отчёта.",
        "Это приближение с учётом задержки записи лога, не точный трассировочный журнал.",
        "",
    ]
    turns = []
    if result.get("fixture_id") != "interpreter-dialogue-v2":
        return lines + ["Для этого сценария автоматическое сопоставление не определено.", ""]
    for language, target, voice in (("ru", "en", "en-us"), ("en", "ru", "ru")):
        source = next(
            track
            for track in transcript["tracks"]
            if track["language"] == language and track["file"].startswith("input/")
        )
        output = next(
            track
            for track in transcript["tracks"]
            if track["language"] == target and track["file"].startswith("output/")
        )
        inputs, outputs = group_phrases(source["segments"]), group_phrases(output["segments"])
        metrics = [row for row in result["latency_by_turn"] if row["source_language"] == language]
        sent = [
            event
            for event in events
            if "reason=llm_reply state=sent" in event["message"]
            and f"voice={voice} " in event["message"]
        ]
        if not (len(inputs) == len(metrics) == len(sent) == 2 and len(outputs) == 3):
            lines.append(
                f"{language} → {target}: число сегментов не совпало; автоматическое сопоставление пропущено."
            )
            continue
        # Output phrase zero is the greeting, not a translation of the first input.
        for original, translated, metric, event in zip(inputs, outputs[1:], metrics, sent):
            first_rtp = event["seconds"] - metric["rtp_playout_ms"] / 1000
            source_end = first_rtp - metric["speech_end_to_first_rtp_ms"] / 1000
            sentence_ready = event["seconds"] - metric["sentence_to_audio_complete_ms"] / 1000
            stt_start = sentence_ready + metric["queue_wait_ms"] / 1000
            stt_end = stt_start + metric["stt_ms"] / 1000
            llm_end = stt_end + metric["llm_ms"] / 1000
            turns.append(
                (
                    source_end,
                    [
                        f"### {source['speaker']} → {output['speaker']}",
                        "",
                        f"**Сказано** ({clock(original['start'])}–{clock(original['end'])} входного WAV): {original['text']}",
                        "",
                        f"**Записано у собеседника** ({clock(translated['start'])}–{clock(translated['end'])} выходного WAV): {translated['text']}",
                        "",
                        "| Этап | Время от начала эксперимента |",
                        "| --- | --- |",
                        f"| Конец входной речи на захвате | ≈ {clock(source_end)} |",
                        f"| Реплика собрана, поставлена в очередь | ≈ {clock(sentence_ready)} |",
                        f"| STT | ≈ {clock(stt_start)}–{clock(stt_end)} |",
                        f"| LLM | ≈ {clock(stt_end)}–{clock(llm_end)} |",
                        f"| Доставка задания, очередь озвучки и TTS | ≈ {clock(llm_end)}–{clock(first_rtp)} |",
                        f"| Первый RTP перевода | ≈ {clock(first_rtp)} |",
                        f"| Отправка перевода завершена (лог) | {clock(event['seconds'])} |",
                        "",
                    ],
                )
            )
    for _, turn_lines in sorted(turns):
        lines.extend(turn_lines)
    return lines


def service_events(experiment, origin):
    events = []
    for name in ("lab-voice-agent", "lab-ai-worker", "lab-sip-as"):
        for line in (
            (experiment / "logs" / f"{name}.log").read_text(encoding="utf-8-sig").splitlines()
        ):
            if not re.search(
                r"VOICE (call_started|call_ended|tts )|LLM timing|AI utterance_processed|SIP_AS",
                line,
            ):
                continue
            instant, _, message = line.partition(" ")
            try:
                elapsed = timestamp(instant) - origin
            except ValueError:
                continue
            events.append({"seconds": elapsed, "utc": instant, "service": name, "message": message})
    return sorted(events, key=lambda event: event["seconds"])


def write_reports(experiment, transcript):
    manifest = json.loads((experiment / "manifest.json").read_text(encoding="utf-8-sig"))
    origin = timestamp(manifest["started_at"])
    events = service_events(experiment, origin)
    lines = [
        "# Транскрипция и временная шкала эксперимента",
        "",
        f"Эксперимент: `{manifest['experiment_id']}`. Ноль журнала: **{manifest['started_at']} UTC**.",
        "",
        "## Что доказано и чего нет",
        "",
        "Ниже — повторное локальное распознавание **фактических WAV**, а не текст сценария.",
        "Вход — файл, подключённый к проигрывателю SIP-клиента; это не отдельная запись",
        "того, что дошло до STT. Выход — запись принимающей стороны, включая приветствие.",
        "Роли назначены по дорожкам/направлению звонка, не по биометрическому распознаванию голоса.",
        "Слова и границы ASR могут быть ошибочны; для проверки приложены исходные записи.",
        "",
        "**Пробел исходного прогона:** точные тексты STT → LLM и LLM → TTS не сохранялись.",
        "Повторный ASR выхода не является точным сохранённым ответом LLM.",
        "Времена WAV ниже отсчитываются от начала каждого файла. Это разные часы,",
        "их нельзя напрямую вычитать между входом и выходом. Журнал сервисов имеет общую UTC-шкалу.",
        "",
    ]
    lines.extend(dialogue_summary(experiment, transcript, events))
    lines.extend(["## Реальные аудиодорожки", ""])
    for track in transcript["tracks"]:
        lines.extend(
            [
                f"### {track['speaker']}",
                "",
                f"[Открыть WAV](../{track['file']}) · {track['duration_seconds']:.3f} с · "
                f"{track['sample_rate']} Гц · RMS {track['rms']:.5f} · "
                f"ненулевых отсчётов: {track['nonzero_samples']}",
                "",
                "| Время в WAV | Кто / направление | Распознано из аудио |",
                "| --- | --- | --- |",
            ]
        )
        for segment in track["segments"]:
            text = segment["text"].replace("|", "\\|")
            lines.append(
                f"| {clock(segment['start'])}–{clock(segment['end'])} | {track['speaker']} | {text} |"
            )
        if not track["segments"]:
            lines.append("| — | — | ASR не обнаружил речь: требуется проверка WAV |")
        lines.append("")
    lines.extend(
        [
            "## Общая временная шкала обработки",
            "",
            "Время ниже — от запуска эксперимента. `tts … state=sent` означает конец",
            "отправки RTP, а не начало фразы; `utterance_processed` — завершение обработки.",
            "Детальные времена этапов — [исходный отчёт](../metadata/test-result.json).",
            "Все сетевые/пакетные события остаются в [каталоге логов](../logs/).",
            "",
            "| От начала | Сервис | Подтверждённое событие |",
            "| --- | --- | --- |",
        ]
    )
    for event in events:
        message = event["message"].replace("|", "\\|")
        lines.append(f"| {clock(event['seconds'])} | {event['service']} | `{message}` |")
    lines.extend(["", "Полные слова и временные метки: [transcript.json](transcript.json).", ""])
    (experiment / "analysis/timeline.md").write_text("\n".join(lines), encoding="utf-8")
    (experiment / "analysis/service-timeline.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
