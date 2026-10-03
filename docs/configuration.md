# Настройка стенда

Значения, единицы измерения и назначение **всех 246 переменных**:
[полный справочник lab.env](lab-env-reference.md). Здесь описаны правила применения.

Все публичные значения по умолчанию находятся в `app/config/lab.env`. Он читается Compose,
контейнерами и проверками стенда. Для применения изменённого env пересоздайте
соответствующий контейнер через `scripts/compose.ps1 up -d <service>`.
Изменения адресов или сетей могут потребовать полного перезапуска стенда.

| Что менять | Переменные |
| --- | --- |
| Сети, адреса, DNS | `LAB_*`, `IMS_UE_*`, `INTERNET_UE_*`, `*_IP`, `DNS_*` |
| Сигнализация и порты | `*_PORT`, `RTPENGINE_QUERY_TIMEOUT_SECONDS`, `IMS_DOMAIN`, `UE*_IMSI`, `VOICE_*_MSISDN` |
| Версии образов | `OAI_*_IMAGE`, `UERANSIM_IMAGE`, `MYSQL_IMAGE`, `PYHSS_IMAGE`, `KAMAILIO_IMAGE`, `SCSCF_IMAGE`, `OLLAMA_IMAGE`, `CONTROL_INIT_IMAGE`; `OPEN5GS_IMAGE` и `MONGO_IMAGE` сохранены для отката |
| STT | `AI_MODEL_SIZE`, `AI_MODEL_REVISION`, `AI_DEVICE`, `AI_COMPUTE_TYPE`, `AI_LANGUAGE`, `AI_STT_*` |
| Границы обычных реплик | `AI_UTTERANCE_*`, `AI_VAD_RMS`, `AI_AUDIO_PREROLL_MS` |
| Границы исследовательского диалога | `AI_DIALOGUE_UTTERANCE_*`, `AI_DIALOGUE_EVENT_GAP_MS` |
| Очереди и параллельность | `AI_QUEUE_MAX`, `AI_UTTERANCE_QUEUE_MAX`, `AI_PROCESSING_WORKERS`, `VOICE_AGENT_REPLY_QUEUE_MAX`, `LLM_NUM_PARALLEL`, `SERVICE_HTTP_THREADS` |
| Защита полноты транскрипта | `LLM_NORMALIZATION_MIN_LENGTH_RATIO`, `TRANSCRIPT_NORMALIZED_MAX_CHARS` |
| LLM | `LLM_MODEL`, `LLM_GGUF_URL`, `LLM_GGUF_SHA256`, `LLM_*PROMPT`, `LLM_TIMEOUT_SECONDS`, `LLM_KEEP_ALIVE`, `LLM_NUM_PARALLEL`, `LLM_CONTAINER_RUNTIME`, `LLM_GPU_DEVICES` |
| Синтез речи | `TTS_BACKEND`, `TTS_VOICE`, `TTS_TRANSLATION_VOICE`, `TTS_RATE`, `PIPER_*` |
| Приватные записи | `RECORDING_*` |
| Нагрузка | `*_CPU_LIMIT`, `*_MEMORY_LIMIT`, `AI_QUEUE_MAX`, `CUSTOM_SERVICE_*` |
| HTTP AI Worker | `AI_WORKER_BIND`, `AI_WORKER_PORT`, `AI_REPLY_HTTP_TIMEOUT_SECONDS` |
| Исследовательские проверки | `RESEARCH_GATE_TIMEOUT_SECONDS`, `BILINGUAL_DIALOGUE_*` |
| Двусторонний перевод | `VOICE_INTERPRETER_*`, `INTERPRETER_DIALOGUE_*`, `REVERSE_TRANSLATION_*` |

CPU — публичный профиль по умолчанию. Локальные GPU overrides и смена LLM
описаны в [local-models.md](local-models.md), CUDA STT и экспериментальные
`AI_STREAM_*` — в [streaming.md](streaming.md). Streaming по умолчанию выключен.
`local/secrets/ims.env` загружается Compose после публичного env и может
содержать машинные overrides. Не все host-side скрипты читают этот файл:
публичную топологию и параметры проверок меняйте в `app/config/lab.env`.

### Приоритет и область действия

Для подстановки `${...}` Compose читает публичный env, затем secrets; обычное
окружение shell имеет более высокий приоритет. Но контейнерный `env_file` и
Compose `--env-file` — разные механизмы: наши сервисы читают публичный файл,
а `environment:` в YAML явно переопределяет только перечисленные там значения.
Поэтому перенос произвольного ключа в secrets не гарантирует, что его увидит
каждый контейнер. Перед изменением смотрите определение нужного сервиса.

`compose_ai.py` добавляет `local/ai-profiles/<режим>/profile.env` и overlay
`compose.yml`, а также задаёт выбранные значения для Compose в окружении процесса.
У AI Worker и Voice Agent этот профиль добавляется к контейнерному env_file.
Он принудительно включает CPU и отключает streaming. Сгенерированные файлы
перезаписываются скриптом; исходник вариантов — [ai-profiles.json](../app/config/ai-profiles.json).
Сам `lab.env` при переключении не меняется. Профиль указывайте каждый раз.

### Что находится вне lab.env

| Настройка | Где и как используется |
| --- | --- |
| `UE1_5GS_K`, `UE2_5GS_K` | Secrets, K доступа 5GS, по 32 hex-символа; только наш локальный OAI |
| `UE1_5GS_OPC`, `UE2_5GS_OPC` | Secrets, OPc доступа 5GS, по 32 hex-символа |
| `UE1_5GS_AMF`, `UE2_5GS_AMF` | Secrets, поле Milenage AMF по 4 hex-символа; не адрес функции AMF |
| `UE1_IMS_K`, `UE2_IMS_K` | Secrets, IMS AKA K, по 32 hex-символа |
| `UE1_IMS_OPC`, `UE2_IMS_OPC` | Secrets, IMS AKA OPc, по 32 hex-символа |
| `UE1_IMS_AMF`, `UE2_IMS_AMF` | Secrets, поле IMS AKA AMF, по 4 hex-символа |
| `IMS_DIGEST_PASSWORD` | Secrets, лабораторный fallback Digest; не применять production Ki как Digest-пароль |
| `SUBSCRIBER_K`, `SUBSCRIBER_OPC`, `SUBSCRIBER_AMF` | Полный legacy fallback 32/32/4 hex; не смешивать неполный набор с новыми ключами |
| `OAI_DB_PASSWORD`, `OAI_DB_ROOT_PASSWORD` | Secrets, автоматически создаваемые пароли по 48 hex; не требуются partner `--ims-only` |
| `MEDIA_ADAPTER_URL`, `AI_WORKER_URL`, `VOICE_AGENT_URL` | Формируются в Compose из адресов/портов; не отдельные операторские ключи lab.env |
| Внутренний control token | Генерируется один раз в Docker volume; публичный файл задаёт только путь/размер |
| Настройки OAI | `local/oai/`, генерируются из публичных настроек и secrets |
| Весовые файлы OPUS | `local/models/opus-mt/`, оба направления и SHA manifests |

Шаблон секретов: [ims.env.example](../app/config/ims.env.example). Для нового
стенда используйте генератор, а не значения `replace-*`. `--ims-only` создаёт
только IMS-часть; дальнейший локальный OAI потребует отдельного полного набора
5GS-ключей. Значения секретов, токена и полный `compose config` не публикуйте.

Пароли и ключи абонентов находятся в `local/secrets/ims.env`. Токен внутренних API
создаётся в приватном Docker-томе; в публичный env он не попадает.

Новые профили имеют отдельные `UE1/2_5GS_K/OPC/AMF` и `UE1/2_IMS_K/OPC/AMF`.
Существующие БД не перезаписываются при provisioning: несовпадение ключей требует
явной миграции с backup. `scripts/migrate_subscriber_keys.py` относится только
к прежнему Open5GS, его нельзя использовать для текущего OAI UDR.
OAI имеет отдельную SQL-базу и приватные конфиги `local/oai/`; после изменения
публичных параметров выполните `python scripts/initialize_local.py` и
перезапустите соответствующие NFs. Параметры подключения внешнего ядра описаны
в [partner-integration.md](partner-integration.md).
В закреплённом PyHSS Digest использует AuC `ki` как пароль. Поэтому Compose
передаёт каждому PJSUA его `UE*_IMS_K` в качестве `IMS_DIGEST_PASSWORD` внутри
контейнера. Общий `IMS_DIGEST_PASSWORD` из файла остаётся fallback для legacy
профиля. Это ограничение лабораторной Digest-регрессии, не IMS AKA.

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
синтетического сценария с фиксированным расписанием. Они не подстраиваются
под фактическую скорость STT/LLM/TTS: на медленном хосте реплики могут перекрываться.

Версии и digest образов заданы в публичном env и Dockerfile. При изменении модели меняйте также её
revision/digest и запускайте admission. PCMU/8000, структура RTP и формат SIP
остаются протокольными контрактами: произвольное изменение частоты через env
без изменения всей цепочки не поддерживается.
