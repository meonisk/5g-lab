# Local STT model provenance

Дополнительные CPU-профили используют OPUS-MT int8 и закреплённые Whisper
base/tiny: [режимы AI](../../../docs/guide-2-ims-ai.md#4-режимы-ai).
Параметры — `app/config/ai-profiles.json`; это отдельные экспериментальные условия.

The current translation profile uses Unsloth Qwen3-4B-Instruct-2507 Q4_K_M
through Ollama. `app/config/lab.env` pins the GGUF URL/revision and full SHA-256;
the model initializer verifies the file before importing the configured tag.
See [AI settings](../../../docs/guide-2-ims-ai.md#7-настройка-ai) for GPU and alternatives.
Older Qwen2.5 experiments are historical and do not define the default profile.

- Backend package: `faster-whisper==1.2.1`
- Model repository: `Systran/faster-whisper-small`
- Model revision: `536b0662742c02347bc0e980a01041f333bce120`
- Repository-declared license: MIT
- Runtime profile: CPU, int8, Russian-forced service calls or automatic
  Russian/English detection for the bilingual research fixture; VAD/RTP-gap
  bounded PCMU utterances are resampled from 8 kHz to 16 kHz in memory
- Storage: `ai-model-cache` Docker volume mounted at `AI_MODEL_CACHE`
- Optional CUDA STT is a separate execution profile; see
  [AI settings](../../../docs/guide-2-ims-ai.md#7-настройка-ai)

The revision is fixed in `app/config/lab.env` and passed to the model downloader. The
complete Python dependency set is fixed in `requirements.txt`. A different
model revision, compute type, language, device, turn segmentation, or decoder setting
is a different experimental condition and must receive a new design version.

This model is an integration and small-model research baseline. Its successful
transcript is not evidence of accuracy; WER/CER requires a fixed licensed
corpus and frozen reference transcripts.
