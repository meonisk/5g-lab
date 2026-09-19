# Настройка стенда

Все публичные значения по умолчанию находятся в `app/config/lab.env`. Он читается Compose,
контейнерами и проверками стенда. Для применения изменённого env пересоздайте
соответствующий контейнер через `scripts/compose.ps1 up -d <service>`.
Изменения адресов или сетей могут потребовать полного перезапуска стенда.

| Что менять | Переменные |
| --- | --- |
| Сети, адреса, DNS | `LAB_*`, `IMS_UE_*`, `INTERNET_UE_*`, `*_IP`, `DNS_*` |
| Сигнализация и порты | `*_PORT`, `RTPENGINE_QUERY_TIMEOUT_SECONDS`, `IMS_DOMAIN`, `UE*_IMSI`, `VOICE_*_MSISDN` |
| Версии образов | `OPEN5GS_IMAGE`, `UERANSIM_IMAGE`, `MONGO_IMAGE`, `MYSQL_IMAGE`, `PYHSS_IMAGE`, `KAMAILIO_IMAGE`, `OLLAMA_IMAGE`, `CONTROL_INIT_IMAGE` |
| STT | `AI_MODEL_SIZE`, `AI_MODEL_REVISION`, `AI_DEVICE`, `AI_COMPUTE_TYPE`, `AI_LANGUAGE`, `AI_STT_*` |
| Границы обычных реплик | `AI_UTTERANCE_*`, `AI_VAD_RMS`, `AI_AUDIO_PREROLL_MS` |
| Границы исследовательского диалога | `AI_DIALOGUE_UTTERANCE_*`, `AI_DIALOGUE_EVENT_GAP_MS` |
| Очереди и параллельность | `AI_QUEUE_MAX`, `AI_UTTERANCE_QUEUE_MAX`, `AI_PROCESSING_WORKERS`, `VOICE_AGENT_REPLY_QUEUE_MAX`, `LLM_NUM_PARALLEL`, `SERVICE_HTTP_THREADS` |
| Защита полноты транскрипта | `LLM_NORMALIZATION_MIN_LENGTH_RATIO`, `TRANSCRIPT_NORMALIZED_MAX_CHARS` |
| LLM | `LLM_MODEL`, `LLM_MODEL_DIGEST`, `LLM_*PROMPT`, `LLM_TIMEOUT_SECONDS`, `LLM_KEEP_ALIVE`, `LLM_NUM_PARALLEL` |
| Синтез речи | `TTS_BACKEND`, `TTS_VOICE`, `TTS_TRANSLATION_VOICE`, `TTS_RATE`, `PIPER_*` |
| Входные тестовые голоса Windows | `DIALOGUE_RU_WINDOWS_VOICE`, `DIALOGUE_EN_WINDOWS_VOICE` |
| Приватные записи | `RECORDING_*` |
| Нагрузка | `*_CPU_LIMIT`, `*_MEMORY_LIMIT`, `AI_QUEUE_MAX`, `CUSTOM_SERVICE_*` |
| HTTP AI Worker | `AI_WORKER_BIND`, `AI_WORKER_PORT`, `AI_REPLY_HTTP_TIMEOUT_SECONDS` |
| Исследовательские проверки | `RESEARCH_GATE_TIMEOUT_SECONDS`, `BILINGUAL_DIALOGUE_*` |
| Двусторонний перевод | `VOICE_INTERPRETER_*`, `INTERPRETER_DIALOGUE_*`, `REVERSE_TRANSLATION_*` |

Пароли и ключи абонентов находятся в `local/secrets/ims.env`. Токен внутренних API
создаётся в приватном Docker-томе; в публичный env он не попадает.

### Локальные голоса

`TTS_BACKEND=piper` использует русскую модель Denis medium и английскую
LJ Speech medium. Обе загружаются при сборке образа с проверкой SHA-256,
а затем работают без внешнего TTS API. Модели остаются в памяти процесса;
`PIPER_THREADS` ограничивает CPU-потоки синтеза. Инференс сериализован,
поэтому при нагрузке возможна очередь, а не гарантированный real-time.

`PIPER_LENGTH_SCALE` и `PIPER_EN_LENGTH_SCALE` задают длительность речи:
1.0 — штатная скорость, больше — медленнее. `TTS_RATE` относится только к espeak.
Пути, URL и контрольные суммы русской модели задаются через `PIPER_MODEL_*`,
английской — через `PIPER_EN_MODEL_*`; JSON имеет отдельный `*_CONFIG_SHA256`.
После смены модели выполните `scripts/compose.ps1 build voice-agent`, затем
`scripts/compose.ps1 up -d --no-deps --force-recreate voice-agent`.
Для сравнения со старым голосом установите `TTS_BACKEND=espeak-ng` и пересоздайте сервис.

Движок [Piper](https://github.com/OHF-Voice/piper1-gpl) распространяется по GPL-3.0.
Карточки моделей указывают CC0 для датасета
[Denis](https://huggingface.co/rhasspy/piper-voices/blob/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/MODEL_CARD)
и public domain для датасета
[LJ Speech](https://huggingface.co/rhasspy/piper-voices/blob/c10ece1aade47bb51c153c893d14e5bf8e5b7117/en/en_US/ljspeech/medium/MODEL_CARD).
Это сведения о происхождении, а не замена проверки лицензий при распространении образов.
Исходный синтез — 22050 Гц; телефонный тракт пока PCMU/8000 и ограничивает полосу речи.

Сравнение одинаковых фраз старым и новым голосом (PowerShell из корня):

```powershell
New-Item -ItemType Directory -Force local/private/tts-comparison | Out-Null
docker run --rm --network none --cpus 1 --memory 512m `
  --env-file app/config/lab.env -e VOICE_AGENT_IP=0.0.0.0 -e VOICE_AGENT_RTP_PORT=0 `
  -e SERVICE_CONTROL_TOKEN_FILE=/dev/null -e PYTHONPATH=/app `
  -v "${PWD}/app/tests/integration/compare_tts.py:/compare_tts.py:ro" `
  -v "${PWD}/local/private/tts-comparison:/comparison" `
  --entrypoint python lab-voice-agent /compare_tts.py --output /comparison
```

Результат: восемь WAV (два языка × два движка × исходный/телефонный звук)
и `comparison.json` с временем синтеза без загрузки модели. Это не измерение
задержки всего звонка и не автоматическая оценка естественности голоса.

Текст, голоса и расписание синтетического разговора описаны в
`app/tests/fixtures/bilingual-dialogue-v1.json`. Это входные данные теста. После изменения
запустите `scripts/generate-bilingual-dialogue.ps1`; продолжительность воспроизведения
в `app/config/lab.env` должна покрывать все реплики и не достигать повторного начала WAV.

Полудуплексный тест полного перевода описан отдельно в
`app/tests/fixtures/interpreter-dialogue-v2.json`. Паузы являются частью
CPU-профиля: следующий синтетический собеседник начинает только после полного
STT, LLM и TTS-проигрывания предыдущей реплики.

Версии образов сохранены прежними. При изменении версии модели меняйте также её
revision/digest и запускайте admission. PCMU/8000, структура RTP и формат SIP
остаются протокольными контрактами: произвольное изменение частоты через env
без изменения всей цепочки не поддерживается.
