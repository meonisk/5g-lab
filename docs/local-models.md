# Локальные модели и задержка

Рабочая конфигурация — `app/config/lab.env`. LLM: **Unsloth
Qwen3-4B-Instruct-2507 Q4_K_M**, без thinking; inference выполняет Ollama.
Unsloth здесь поставщик квантованных весов, не отдельный inference-сервер.
STT: faster-whisper; TTS: Piper RU/EN. Модели не отправляют речь в облако.

## Запуск и GPU

`python scripts/start_lab.py` скачивает GGUF по неизменяемой ревизии,
проверяет полный SHA-256 и импортирует его в постоянный Docker volume.
Initializer имеет доступ в Интернет; Ollama runtime находится только во
внутренней сети, без опубликованного порта. Повторный запуск проверяет кэш.
Первое скачивание требует Интернета и примерно 2.5 ГБ для GGUF.

CPU — переносимый режим по умолчанию (`runc`, `LLM_GPU_DEVICES=void`).
Для NVIDIA задайте в **локальном** `local/secrets/ims.env` (этот файл также
принимает машинные overrides Compose; не коммитится):

```dotenv
LLM_CONTAINER_RUNTIME=nvidia
LLM_GPU_DEVICES=all
```

На Linux нужен настроенный NVIDIA Container Toolkit; на Windows — Docker
Desktop/WSL2 и совместимый драйвер. Apple/AMD GPU этим профилем не поддерживаются;
CPU остаётся доступен. Не обещается одинаковая скорость на любой машине.
Минимальные ресурсы следует проверять для выбранного размера модели.

STT делает пробный inference, LLM генерирует один токен до готовности `/healthz`.
`LLM_KEEP_ALIVE=-1` сохраняет LLM в памяти, `LLM_CONTEXT_LENGTH=2048` ограничивает
KV-кэш. Проверка: `docker exec lab-llm-worker ollama ps` — модель должна быть
резидентной, для GPU-профиля ожидается `100% GPU`. После смены модели пересоздайте
initializer, LLM и AI Worker; после перезапуска LLM также перезапустите AI Worker,
чтобы повторить прогрев. Readiness — стартовый барьер, не гарантия отсутствия
последующего отказа/OOM сервера.

## Смена семейства

Менять нужно **три** значения в `app/config/lab.env`: `LLM_MODEL`,
`LLM_GGUF_URL`, `LLM_GGUF_SHA256`. Для Unsloth Gemma 3 4B IT Q4_K_M:

```dotenv
LLM_MODEL=unsloth-gemma3-4b-it:q4_k_m
LLM_GGUF_URL=https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/5a3566e716d80f709ed7b79817eaf7733d2a1fce/gemma-3-4b-it-Q4_K_M.gguf
LLM_GGUF_SHA256=04a43a22e8d2003deda5acc262f68ec1005fa76c735a9962a8c77042a74a7d19
```

Qwen выбран как основной; Gemma — альтернативная конфигурация, не заявленный
пройденный голосовой benchmark. Проверьте условия лицензии каждой модели:
Qwen3 Apache-2.0, Gemma — собственные условия Google. Большая модель не обязательно
даёт меньшую задержку: сравнивайте смысл перевода, пропуски, память и время на
одном наборе WAV. Лимит `LLM_MAX_TOKENS` также может обрезать длинный перевод.

## Что измеряется

Media Adapter отправляет окна каждые 100 мс. VAD завершает реплику по тишине;
при подавлении RTP клиентом assembler использует таймер отсутствия аудио.
`AI_DIALOGUE_EVENT_GAP_MS` должен превышать интервал публикации с запасом
на сетевой jitter; он не является лингвистическим детектором конца предложения.

Эксперимент `scripts/run-interpreter-experiment.ps1` сохраняет четыре полных WAV,
логи и `latency_by_turn`. `speech_end_to_first_rtp_ms` — от последнего кадра,
сочтённого речью на захвате, до отправки первого RTP перевода. Это **не** время
до динамика телефона: jitter buffer/воспроизведение UE не включены. Метрика
предполагает синхронизированные часы (один Docker host; на физическом стенде NTP/PTP).
`speech_end_to_audible_rtp_ms` исключает начальную тишину TTS по `TTS_AUDIBLE_RMS`.
Гейт требует ровно четыре переведённые реплики и для каждой задержку не выше
`INTERPRETER_MAX_RESPONSE_DELAY_MS` (5000 мс). Это всё ещё граница отправки:
приёмный jitter buffer и динамик телефона требуют отдельной проверки.
`sentence_to_audio_complete_ms` включает длительность озвучки и не заменяет её.
STT/LLM/TTS, ожидание очереди и сборка реплики отчётны отдельно.

Это пофразовый перевод, не одновременный streaming-перевод по токенам. Следующие
шаги при неудовлетворительной задержке: streaming ASR, устойчивый endpointing,
проверяемые короткие смысловые сегменты, incremental TTS. Нельзя просто сокращать
все таймеры: это обрежет фразы и ухудшит перевод.

Источники: [Unsloth Qwen](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF),
[Unsloth Gemma](https://huggingface.co/unsloth/gemma-3-4b-it-GGUF),
[Ollama GGUF import](https://docs.ollama.com/import),
[Ollama memory/context](https://docs.ollama.com/faq).
