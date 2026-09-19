"""Language and destination rules for the two-leg interpreter room."""

from . import runtime, settings

INTERPRETER_MODES = {"interpret_ru", "interpret_en"}


def source_language(service_mode):
    return {"interpret_ru": "ru", "interpret_en": "en"}.get(service_mode)


def prompt_for(service_mode):
    if service_mode in {"translate", "interpret_ru"}:
        return settings.llm_translation_prompt
    if service_mode == "interpret_en":
        return settings.llm_reverse_translation_prompt
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
    if service_mode in {"translate", "interpret_ru"} and (
        latin_count < settings.translation_min_latin
        or cyrillic_count > settings.translation_max_cyrillic
    ):
        raise ValueError("English translation output language mismatch")
    if service_mode == "interpret_en" and (
        cyrillic_count < settings.reverse_translation_min_cyrillic
        or latin_count > settings.reverse_translation_max_latin
    ):
        raise ValueError("Russian translation output language mismatch")
    return latin_count
