"""Локальный двусторонний OPUS-MT: без Ollama, PyTorch и доступа в сеть при звонке."""

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from . import settings

_models = {}
_lock = threading.Lock()


def split_sentences(text):
    # OPUS обучен на предложениях: длинный абзац может потерять целые предложения.
    # Не разрываем наиболее распространённые сокращения и инициалы.
    result, start = [], 0
    abbreviations = {"mr.", "mrs.", "ms.", "dr.", "prof.", "г.", "ул.", "т.д.", "т.п."}
    for match in re.finditer(r"[.!?][\"»”']?\s+", text):
        candidate = text[start : match.end()].strip()
        last_word = candidate.split()[-1].lower()
        if last_word in abbreviations or re.fullmatch(r"[^\W\d_]\.", last_word):
            continue
        result.append(candidate)
        start = match.end()
    if text[start:].strip():
        result.append(text[start:].strip())
    return result


def load_translation_models():
    import ctranslate2
    import sentencepiece

    for direction in ("ru-en", "en-ru"):
        path = Path(settings.translation_model_root) / direction
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if manifest["quantization"] != "int8":
            raise ValueError("OPUS-MT требует подготовленные int8 модели")
        for name, digest in manifest["files"].items():
            asset = (path / name).resolve()
            if not asset.is_relative_to(path.resolve()):
                raise ValueError("Некорректный путь модели")
            if hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
                raise ValueError(f"OPUS-MT SHA256 mismatch: {direction}/{name}")
        _models[direction] = (
            ctranslate2.Translator(
                str(path),
                device="cpu",
                compute_type="int8",
                inter_threads=1,
                intra_threads=settings.translation_threads,
            ),
            sentencepiece.SentencePieceProcessor(model_file=str(path / "source.spm")),
            sentencepiece.SentencePieceProcessor(model_file=str(path / "target.spm")),
        )
    # Готовность означает проверку обоих направлений, включая реальный inference.
    translate("Проверка перевода.", "interpret_ru")
    translate("Translation test.", "interpret_en")


def translate(text, service_mode):
    if service_mode not in {"translate", "interpret_ru", "interpret_en"}:
        raise ValueError("OPUS-MT поддерживает только перевод RU/EN")
    direction = "en-ru" if service_mode == "interpret_en" else "ru-en"
    started = time.perf_counter()
    with _lock:
        translator, source, target = _models[direction]
        sentences = split_sentences(text)
        tokens = [source.encode(sentence, out_type=str) + ["</s>"] for sentence in sentences]
        if not tokens or sum(map(len, tokens)) > 512:
            raise ValueError("Слишком длинный вход OPUS-MT; текст не обрезан")
        results = translator.translate_batch(
            tokens,
            beam_size=settings.translation_beam_size,
            max_input_length=512,
            max_decoding_length=256,
        )
        translated_parts = []
        for result in results:
            hypothesis = result.hypotheses[0]
            if len(hypothesis) >= 256:
                raise ValueError("Достигнут предел перевода; неполный текст не отправлен")
            part = target.decode(hypothesis).strip()
            if not part:
                raise ValueError("Пустой перевод предложения")
            translated_parts.append(part)
        translated = " ".join(translated_parts)
        if len(translated) > settings.llm_response_max_chars:
            raise ValueError("Перевод превышает лимит TTS; текст не обрезан")
    return translated, (time.perf_counter() - started) * 1000
