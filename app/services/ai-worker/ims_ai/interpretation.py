"""Language and destination rules for the two-leg interpreter room."""

from . import runtime, settings

INTERPRETER_MODES = {"interpret_ru", "interpret_en"}


def source_language(service_mode):
    return {"interpret_ru": "ru", "interpret_en": "en"}.get(service_mode)


def prompt_for(service_mode):
    suffix = ""
    if settings.streaming_enabled and service_mode in INTERPRETER_MODES:
        suffix = (
            " The input is a stable fragment of ongoing speech. Translate only this fragment."
            " Do not invent its continuation or repeat previous translations."
        )
    if service_mode in {"translate", "interpret_ru"}:
        return settings.llm_translation_prompt + suffix
    if service_mode == "interpret_en":
        return settings.llm_reverse_translation_prompt + suffix
    return settings.llm_system_prompt


def output_voice(service_mode):
    if service_mode in {"translate", "interpret_ru"}:
        return settings.translation_voice
    return settings.default_voice


def delivery_call(source_call_id, service_mode):
    """Route interpreter output to the only active opposite-language leg."""
    if service_mode not in INTERPRETER_MODES:
        return source_call_id
    opposite = "interpret_en" if service_mode == "interpret_ru" else "interpret_ru"
    with runtime.lock:
        candidates = [
            call_id
            for call_id, state in runtime.active_calls.items()
            if call_id != source_call_id and state.get("service_mode") == opposite
        ]
    if len(candidates) != 1:
        raise RuntimeError("interpreter counterpart is not uniquely available")
    return candidates[0]


def validate_output(text, service_mode, cyrillic_count):
    latin_count = sum(char.isascii() and char.isalpha() for char in text)
    # A valid streaming acknowledgement can be just "I" or "Да".
    streaming = settings.streaming_enabled and service_mode in INTERPRETER_MODES
    minimum_latin = 1 if streaming else settings.translation_min_latin
    minimum_cyrillic = 1 if streaming else settings.reverse_translation_min_cyrillic
    if service_mode in {"translate", "interpret_ru"} and (
        latin_count < minimum_latin or cyrillic_count > settings.translation_max_cyrillic
    ):
        raise ValueError("English translation output language mismatch")
    if service_mode == "interpret_en" and (
        cyrillic_count < minimum_cyrillic or latin_count > settings.reverse_translation_max_latin
    ):
        raise ValueError("Russian translation output language mismatch")
    return latin_count
