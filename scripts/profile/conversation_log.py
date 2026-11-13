"""Разбор длинного разговора: числа по направлениям и журнал всех событий по времени.

Чистые функции без стенда. Источники:
- timeline сценария (dialogue.render_conversation): когда в WAV звучит каждое предложение;
- timeline.jsonl записи звонка (AI Worker): по фразе — когда пришёл первый и последний
  голосовой пакет, почему фраза закончилась, очередь, распознавание, перевод, тексты;
- события Voice Agent: синтез, первый звук перевода в RTP, длительность, прерывание.
Время в журнале — секунды от начала WAV. Начало WAV на стенде = первый голосовой пакет
первой фразы минус начало первого предложения; моменты слов внутри предложения —
оценка пропорционально числу букв (Piper не отдаёт время слов).
"""

from collections import Counter

from latency import summary
from quality import accuracy

TARGET_MS = 2000


def word_times(sentence):
    """[(слово, мс от начала WAV)] — середина слова, оценка по доле букв в предложении."""
    words, position, total = [], 0, len(sentence["text"])
    span = sentence["end_ms"] - sentence["start_ms"]
    for word in sentence["text"].split():
        middle = position + len(word) / 2
        words.append((word, sentence["start_ms"] + span * middle / max(total, 1)))
        position += len(word) + 1
    return words


def words_between(sentences, start_ms, end_ms):
    return " ".join(w for s in sentences for w, at in word_times(s) if start_ms <= at <= end_ms)


def wav_start(phrases, sentences):
    """Момент начала WAV по часам стенда (по первой фразе первого говорящего)."""
    first = min((p for p in phrases if p.get("first_voice_packet_at")),
                key=lambda p: p["first_voice_packet_at"], default=None)  # fmt: skip
    if first is None:
        return None
    return first["first_voice_packet_at"] - min(s["start_ms"] for s in sentences) / 1000


def direction_metrics(phrases, tts, sentences):
    """Числа одного направления; phrases — строки timeline.jsonl одной ноги."""
    phrases = sorted(phrases, key=lambda p: p.get("last_voice_packet_at") or 0)
    spoken = [p for p in phrases if p.get("transcript")]
    pairs = [(p, tts[p["reply_id"]]) for p in spoken if p.get("reply_id") in tts]
    heard = [(p, t) for p, t in pairs if t.get("first_voice_rtp_at")]
    lags = [round((t["first_voice_rtp_at"] - p["last_voice_packet_at"]) * 1000) for p, t in heard]
    third = max(1, len(lags) // 3)
    ends = [t["first_voice_rtp_at"] + t.get("rtp_playout_ms", 0) / 1000 for _, t in heard]
    speech_end = max((p.get("last_voice_packet_at") or 0 for p in spoken), default=0)
    reference = " ".join(s["text"] for s in sentences)
    return {
        "sentences": len(sentences),
        "speech_s": round(sum(s["end_ms"] - s["start_ms"] for s in sentences) / 1000, 1),
        "phrases": len(phrases),
        "phrases_with_text": len(spoken),
        "end_reasons": dict(Counter(p.get("utterance_end_reason") for p in phrases)),
        "phrase_s": summary([p.get("audio_duration_seconds") for p in phrases]),
        "translated": sum(1 for p in spoken if p.get("translation")),
        "voiced": sum(1 for _, t in pairs if t.get("event") == "tts_sent"),
        "interrupted": sum(1 for _, t in pairs if t.get("event") == "tts_interrupted"),
        "accuracy": round(accuracy(reference, " ".join(p["transcript"] for p in spoken)), 3),
        "lag_ms": summary(lags),
        "lag_by_phrase_ms": lags,
        "within_target": sum(lag <= TARGET_MS for lag in lags),
        # Медиана последней трети фраз минус медиана первой: > 0 — перевод отстаёт всё больше.
        "lag_growth_ms": round(summary(lags[-third:])["median"] - summary(lags[:third])["median"])
        if lags
        else None,
        "tail_s": round(max(ends) - speech_end, 1) if ends else None,
        "reply_audio_s": round(sum(t.get("rtp_playout_ms", 0) for _, t in pairs) / 1000, 1),
        "queue_wait_max_ms": round(max((p.get("queue_wait_ms") or 0 for p in phrases), default=0)),
    }


def problems(directions, min_accuracy):
    found = []
    for name, data in directions.items():
        if not data["phrases_with_text"] or data["translated"] < data["phrases_with_text"]:
            found.append(f"{name}: переведено {data['translated']} из "
                         f"{data['phrases_with_text']} фраз")  # fmt: skip
        if data["interrupted"]:
            found.append(f"{name}: озвучка перевода прервана {data['interrupted']} раз "
                         "(собеседник заговорил, перевод не дослушан)")  # fmt: skip
        if data["accuracy"] < min_accuracy:
            found.append(f"{name}: точность {data['accuracy']:.0%} < {min_accuracy:.0%}")
    return found


def _ms(value):
    return "—" if value is None else f"{value:.0f}"


def journal(sentences, legs, tts):
    """Строки журнала по времени. legs: {направление: (говорящий, фразы этой ноги)}."""
    everything = [p for _, phrases in legs.values() for p in phrases]
    start = wav_start(everything, sentences)
    if start is None:
        return ["нет ни одной фразы с голосовыми пакетами: журнал не построить"]
    rows = []

    def at(moment):
        return moment - start

    for number, s in enumerate(sentences, 1):
        rows.append((s["start_ms"] / 1000, f"{s['speaker']} говорит   предложение {number}, "
                     f"до +{s['end_ms'] / 1000:.2f}: «{s['text']}»"))  # fmt: skip
    for direction, (speaker, phrases) in legs.items():
        spoken = [s for s in sentences if s["speaker"] == speaker]
        ordered = sorted(phrases, key=lambda p: p.get("first_voice_packet_at") or 0)
        for number, p in enumerate(ordered, 1):
            tag = f"{direction} фраза {number}"
            first, last = p.get("first_voice_packet_at"), p.get("last_voice_packet_at")
            if not (first and last):
                continue
            words = words_between(spoken, at(first) * 1000 - 150, at(last) * 1000 + 150)
            ready = p.get("sentence_ready_at") or last
            rows.append((at(ready), f"сервер     {tag}: речь +{at(first):.2f}…+{at(last):.2f} "
                         f"({p.get('audio_duration_seconds', 0):.1f} с), закрыта: "
                         f"{p.get('utterance_end_reason')} через {_ms((ready - last) * 1000)} мс "
                         f"после последнего голоса; слова ≈ «{words}»"))  # fmt: skip
            stt_done = (p.get("ai_started_at") or ready) + (p.get("stt_processing_ms") or 0) / 1000
            rows.append((at(stt_done), f"распознано {tag}: очередь {_ms(p.get('queue_wait_ms'))} мс, "
                         f"STT {_ms(p.get('stt_processing_ms'))} мс: «{p.get('transcript', '')}»"))  # fmt: skip
            if p.get("translation"):
                rows.append((at(p.get("processed_at") or stt_done),
                             f"переведено {tag}: {_ms(p.get('llm_processing_ms'))} мс: "
                             f"«{p['translation']}»"))  # fmt: skip
            t = tts.get(p.get("reply_id"))
            if t and t.get("first_voice_rtp_at"):
                state = "ПРЕРВАН" if t.get("event") == "tts_interrupted" else "доигран"
                rows.append((at(t["first_voice_rtp_at"]),
                             f"звучит     {tag}: через {_ms((t['first_voice_rtp_at'] - last) * 1000)} мс "
                             f"после конца речи, синтез {_ms(t.get('synthesis_ms'))} мс, звучал "
                             f"{(t.get('rtp_playout_ms') or 0) / 1000:.1f} с, {state}"))  # fmt: skip
            elif p.get("translation"):
                rows.append((at(p.get("processed_at") or stt_done),
                             f"не озвучен  {tag}: Voice Agent не сообщил об отправке"))  # fmt: skip
    return [f"{moment:+9.2f}  {text}" for moment, text in sorted(rows, key=lambda r: r[0])]
