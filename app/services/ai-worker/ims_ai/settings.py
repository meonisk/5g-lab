"""Worker configuration loaded once from app/config/lab.env; durations use explicit units."""

import os
from pathlib import Path

queue_max = int(os.environ["AI_QUEUE_MAX"])
utterance_queue_max = int(os.environ["AI_UTTERANCE_QUEUE_MAX"])
processing_workers = int(os.environ["AI_PROCESSING_WORKERS"])
reply_http_timeout = float(os.environ["AI_REPLY_HTTP_TIMEOUT_SECONDS"])
stt_min_rms = float(os.environ["AI_STT_MIN_RMS"])
stt_beam_size = int(os.environ["AI_STT_BEAM_SIZE"])

event_retention = int(os.environ["AI_EVENT_RETENTION"])

retention_seconds = int(os.environ["AI_TRANSCRIPT_RETENTION_SECONDS"])

buffer_max = int(os.environ["AI_STREAM_BUFFER_MAX"])

buffer_ttl = int(os.environ["AI_STREAM_BUFFER_TTL_SECONDS"])

max_replies_per_call = int(os.environ["AI_MAX_REPLIES_PER_CALL"])

history_turns = int(os.environ["AI_CONVERSATION_HISTORY_TURNS"])

conversation_ttl = int(os.environ["AI_CONVERSATION_TTL_SECONDS"])

request_max_bytes = int(os.environ["AI_REQUEST_MAX_BYTES"])

vad_rms = int(os.environ["AI_VAD_RMS"])

min_utterance_bytes = int(float(os.environ["AI_UTTERANCE_MIN_SECONDS"]) * 8000)

silence_bytes_required = int(float(os.environ["AI_UTTERANCE_SILENCE_MS"]) / 1000 * 8000)

max_utterance_bytes = int(float(os.environ["AI_UTTERANCE_MAX_SECONDS"]) * 8000)

dialogue_silence_bytes_required = int(
    float(os.environ["AI_DIALOGUE_UTTERANCE_SILENCE_MS"]) / 1000 * 8000
)

dialogue_max_utterance_bytes = int(float(os.environ["AI_DIALOGUE_UTTERANCE_MAX_SECONDS"]) * 8000)

dialogue_event_gap_seconds = float(os.environ["AI_DIALOGUE_EVENT_GAP_MS"]) / 1000

preroll_bytes = int(float(os.environ["AI_AUDIO_PREROLL_MS"]) / 1000 * 8000)

backend = os.environ["AI_BACKEND"]

model_size = os.environ["AI_MODEL_SIZE"]

model_revision = os.environ["AI_MODEL_REVISION"]

device = os.environ["AI_DEVICE"]

compute_type = os.environ["AI_COMPUTE_TYPE"]

language = os.environ["AI_LANGUAGE"]

llm_url = os.environ["LLM_URL"]

llm_model = os.environ["LLM_MODEL"]

llm_timeout = float(os.environ["LLM_TIMEOUT_SECONDS"])

llm_max_tokens = int(os.environ["LLM_MAX_TOKENS"])

llm_temperature = float(os.environ["LLM_TEMPERATURE"])

llm_system_prompt = os.environ["LLM_SYSTEM_PROMPT"]

llm_translation_prompt = os.environ["LLM_TRANSLATION_PROMPT"]
llm_reverse_translation_prompt = os.environ["LLM_REVERSE_TRANSLATION_PROMPT"]

llm_transcription_prompt = os.environ["LLM_TRANSCRIPTION_PROMPT"]

llm_english_transcription_prompt = os.environ["LLM_ENGLISH_TRANSCRIPTION_PROMPT"]

llm_normalization_max_tokens = int(os.environ["LLM_NORMALIZATION_MAX_TOKENS"])

llm_normalization_min_length_ratio = float(os.environ["LLM_NORMALIZATION_MIN_LENGTH_RATIO"])

normalized_transcript_max_chars = int(os.environ["TRANSCRIPT_NORMALIZED_MAX_CHARS"])

llm_response_max_chars = int(os.environ["VOICE_AGENT_REPLY_MAX_CHARS"])

translation_voice = os.environ["TTS_TRANSLATION_VOICE"]

default_voice = os.environ["TTS_VOICE"]

translation_min_latin = int(os.environ["TRANSLATION_MIN_LATIN_CHARS"])

translation_max_cyrillic = int(os.environ["TRANSLATION_MAX_CYRILLIC_CHARS"])

reverse_translation_min_cyrillic = int(os.environ["REVERSE_TRANSLATION_MIN_CYRILLIC_CHARS"])

reverse_translation_max_latin = int(os.environ["REVERSE_TRANSLATION_MAX_LATIN_CHARS"])

service_modes = {
    "observe",
    "translate",
    "transcribe",
    "assistant",
    "bilingual_test",
    "interpret_ru",
    "interpret_en",
}

voice_agent_url = os.environ["VOICE_AGENT_URL"].rstrip("/")

recording_enabled = os.environ["RECORDING_ENABLED"] == "1"

recording_root = Path(os.environ["RECORDING_ROOT"])

recording_max_bytes = int(os.environ["RECORDING_MAX_BYTES_PER_CALL"])

recording_retention_days = int(os.environ["RECORDING_RETENTION_DAYS"])
