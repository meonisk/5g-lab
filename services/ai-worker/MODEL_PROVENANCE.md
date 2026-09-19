# Local STT model provenance

- Backend package: `faster-whisper==1.2.1`
- Model repository: `Systran/faster-whisper-base`
- Model revision: `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`
- Repository-declared license: MIT
- Runtime profile: CPU, int8, Russian, VAD-bounded PCMU utterances resampled
  from 8 kHz to 16 kHz in memory
- Storage: Docker volume configured by `AI_MODEL_CACHE`

The revision is fixed in `lab.env` and passed to the model downloader. The
complete Python dependency set is fixed in `requirements.txt`. A different
model revision, compute type, language, device, turn segmentation, or decoder setting
is a different experimental condition and must receive a new design version.

This model is an integration and small-model research baseline. Its successful
transcript is not evidence of accuracy; WER/CER requires a fixed licensed
corpus and frozen reference transcripts.
