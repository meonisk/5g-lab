# Полный справочник lab.env

Источник значений: [app/config/lab.env](../app/config/lab.env), снимок 03.10.2026.
Ниже описаны все **246** параметров файла. Значения приведены буквально, включая
закреплённые URL/хэши и текстовые инструкции. Пустая ячейка отмечена как «пусто».
Это исходный профиль; [CPU-профили](../app/config/ai-profiles.json) переопределяют
часть значений. Порядок применения и секреты: [configuration.md](configuration.md).

## Как применять изменения

- Сеть, номера, модели и лимиты задавайте в `app/config/lab.env`; не редактируйте
  сгенерированные `local/oai/` и `local/ai-profiles/` вручную.
- Строки с пробелами берите в кавычки. `0/1` — флаги, время имеет указанные
  единицы. IPv4, CIDR, URL, номера портов и номера телефонов — разные типы значений.
- Изменение env требует пересоздания соответствующего контейнера через `up -d`,
  простого `restart` недостаточно. Build args (CUDA, Piper/голоса, базовые образы)
  требуют также `build`. При смене сети планируйте остановку и пересоздание сети.
- После изменения OAI-параметров повторно выполните `initialize_local.py`, затем
  пересоздайте затронутые функции ядра. Изменения identities/iFC требуют
  provisioning и повторной регистрации; не сбрасывайте SQN существующих абонентов.
- Для CPU-режима всегда вызывайте `compose_ai.py --mode <режим>`; иначе можно
  вернуть baseline. Увеличение лимита или таймаута не доказывает производительность.
- Значения `_IMAGE`, URL, SHA и ревизии меняются согласованно с provenance и
  проверками. `SIP_UE_CODEC` описывает контракт PCMU/8000, не свободный переключатель.

Внутренние HTTP API, Cx и NG не нужно открывать внешнему проекту ради интеграции.
Внешние потоки и интерфейсы: [контракт](integration-contract.md).


## Идентичность сети, пулы и абоненты

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `MCC` | `001` | Код страны PLMN, строка из трёх цифр; сохраняйте ведущие нули. |
| `MNC` | `01` | Код сети PLMN; ведущие нули значимы. В имени IMS-домена MNC дополняется до трёх цифр. |
| `IMS_DOMAIN` | `ims.mnc001.mcc001.3gppnetwork.org` | Домашний домен IMS для DNS, identities и SIP realm; согласовать с клиентами. |
| `LAB_NETWORK_CIDR` | `172.22.0.0/24` | IPv4-подсеть сервисов Docker; в partner это выделенная LAN macvlan. |
| `LAB_DYNAMIC_IP_RANGE` | `172.22.0.128/25` | Диапазон динамических адресов Docker внутри LAN, без статических service IP. |
| `INTERNET_DNN` | `internet` | Имя DNN интернет-сессии локальных UE/OAI. |
| `IMS_DNN` | `ims` | Имя DNN IMS-сессии; должно быть разрешено в ядре и на UE. |
| `UE_CLI_TIMEOUT_SECONDS` | `8` | Таймаут команды nr-cli, секунды. |
| `UE_PDU_RECOVERY_TIMEOUT_SECONDS` | `90` | Срок ожидания восстановления PDU в проверках, секунды. |
| `UE_PDU_SST` | `1` | Slice/Service Type локального S-NSSAI, целое; это не параметр SD. |
| `INTERNET_UE_CIDR` | `10.45.0.0/16` | IPv4-пул internet UE; также используется в обратных маршрутах IMS. |
| `INTERNET_UE_GATEWAY` | `10.45.0.1` | Шлюз internet-пула локального UPF, IPv4. |
| `INTERNET_UE_GATEWAY_CIDR` | `10.45.0.1/16` | Тот же шлюз с префиксом; держать согласованным с пулом. |
| `IMS_UE_CIDR` | `10.46.0.0/16` | IPv4-пул IMS UE; маршрутизируется без NAT. |
| `IMS_UE_GATEWAY` | `10.46.0.1` | Шлюз IMS-пула локального UPF, IPv4. |
| `IMS_UE_GATEWAY_CIDR` | `10.46.0.1/16` | Тот же шлюз с префиксом; держать согласованным с пулом. |
| `UE1_IMSI` | `001010000000001` | IMSI первого тестового абонента, строка цифр; согласовать с SIM/UE и базами. |
| `UE2_IMSI` | `001010000000002` | IMSI второго тестового абонента, строка цифр. |
| `UE1_MSISDN` | `1001` | Номер первого тестового IMS-абонента. |
| `UE2_MSISDN` | `1002` | Номер второго тестового IMS-абонента. |

## SIP, RTP и эмулированные клиенты

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `PCSCF_SIP_PORT` | `5060` | Порт SIP P-CSCF, внешний вход IMS для UE. |
| `PCSCF_UDP_MTU` | `65535` | Порог размера SIP UDP для Kamailio, байты; не MTU физического интерфейса. |
| `ICSCF_SIP_PORT` | `5060` | Внутренний SIP-порт I-CSCF. |
| `SCSCF_SIP_PORT` | `6060` | Внутренний SIP-порт S-CSCF. |
| `RTPENGINE_NG_PORT` | `2223` | UDP-порт управления RTPengine NG; только внутри нашей части. |
| `RTPENGINE_CLI_PORT` | `9901` | Порт CLI RTPengine; не порт абонентского звука. |
| `RTPENGINE_PORT_MIN` | `30000` | Начало UDP-диапазона медиареле; открыть маршрут от IMS UE. |
| `RTPENGINE_PORT_MAX` | `30100` | Конец UDP-диапазона медиареле, включительно. |
| `RTPENGINE_QUERY_TIMEOUT_SECONDS` | `0.5` | Таймаут запроса состояния медиасессии по NG, секунды. |
| `SIP_UE_AUTO_ANSWER` | `200` | Код автоматического ответа PJSUA на входящий звонок (200 = принять). |
| `SIP_UE_AUTO_CONFERENCE` | `1` | Флаг автоконференции лабораторного PJSUA, 0/1. |
| `SIP_CALL_DURATION_SECONDS` | `20` | Длительность тестового SIP-вызова, секунды. |
| `SIP_UE_TEST_UTTERANCE` | `"Привет, локальный голосовой агент. Сколько будет пять плюс семь?"` | Синтетическая русская фраза для тестового клиента. |
| `SIP_UE_PLAYBACK_FILE` | пусто | Файл воспроизведения клиента; пусто = стандартный сценарий скрипта. |
| `SIP_UE_CODEC` | `PCMU/8000` | Медиаконтракт клиента PCMU/8000; смена требует согласованной доработки и live-проверок. |
| `SIP_AKA_IMAGE` | `lab-sipp-aka:3.7.7-opc` | Образ SIPp с OPc; собрать по инструкции sipp-aka-provenance. |
| `SIP_AKA_PORT` | `5062` | Локальный SIP-порт тестового AKA-клиента. |
| `SIP_AKA_TIMEOUT_SECONDS` | `35` | Таймаут сценария AKA-регистрации, секунды. |
| `SIP_AKA_MEDIA_PORT` | `4000` | UDP-порт тестового медиапомощника в сети UE. |
| `SIP_AKA_CALL_SECONDS` | `20` | Длительность AKA-вызова, секунды. |
| `SIP_AKA_RESTORE_TIMEOUT_SECONDS` | `90` | Ожидание восстановления обычных клиентов после теста, секунды. |
| `SIP_AKA_LIFECYCLE_CHECKPOINT_SECONDS` | `20` | Пауза контрольной точки обновления регистрации, секунды. |
| `SIP_AKA_LIFECYCLE_FINAL_SECONDS` | `5` | Финальная пауза lifecycle-сценария, секунды. |
| `SIP_AKA_REGISTRAR_DELETE_TIMEOUT_SECONDS` | `210` | Ожидание удаления Contact после deregistration, секунды. |
| `SIP_AKA_INACTIVE_HOLD_SECONDS` | `600` | Удержание старого сокета неактивного абонента, секунды. |
| `SIP_AKA_PASSIVE_DELETE_TIMEOUT_SECONDS` | `390` | Ожидание пассивной очистки регистратора, секунды. |
| `SIP_AKA_EXPIRY_SECONDS` | `30` | Короткий срок регистрации для expiry-теста, секунды. |
| `SIP_AKA_REJECTION_INVITE_DELAY_MS` | `5000` | Задержка INVITE в отрицательном сценарии, миллисекунды. |
| `SIP_AKA_INACTIVE_STATUS` | `404` | Ожидаемый SIP-статус вызова неактивному абоненту; 408/500 не заменяют 404. |
| `SIP_AKA_MEDIA_IMAGE` | `python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1` | Закреплённый Python-образ медиапомощника AKA-тестов. |
| `BILINGUAL_DIALOGUE_UE1_FILE` | `fixtures/ue1-ru-RU.wav` | Путь WAV первого участника в сценарии bilingual; mount определяется fixture Compose. |
| `BILINGUAL_DIALOGUE_UE2_FILE` | `fixtures/ue2-en-US.wav` | Путь WAV второго участника в сценарии bilingual. |
| `BILINGUAL_DIALOGUE_PLAYBACK_SECONDS` | `40` | Окно воспроизведения bilingual-сценария, секунды. |
| `BILINGUAL_DIALOGUE_MIN_RTP_PACKETS` | `300` | Минимум RTP-пакетов для проверки, целое; не показатель качества речи. |
| `INTERPRETER_DIALOGUE_UE1_FILE` | `fixtures/ue1-ru-RU.wav` | Путь русской дорожки в сценарии двустороннего переводчика. |
| `INTERPRETER_DIALOGUE_UE2_FILE` | `fixtures/ue2-en-US.wav` | Путь английской дорожки в сценарии двустороннего переводчика. |
| `INTERPRETER_DIALOGUE_PLAYBACK_SECONDS` | `70` | Окно воспроизведения interpreter-сценария, секунды. |

## Прикладные сервисы и распознавание

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `SIP_AS_PORT` | `5070` | Внутренний SIP-порт собственного Application Server (ISC/iFC). |
| `MEDIA_ADAPTER_PORT` | `8091` | HTTP-порт Media Adapter, в сетевом пространстве RTPengine. |
| `AI_WORKER_PORT` | `8092` | HTTP-порт AI Worker, внутренний интерфейс. |
| `AI_WORKER_BIND` | `0.0.0.0` | Адрес прослушивания HTTP внутри контейнера; 0.0.0.0 = все интерфейсы. |
| `MEDIA_OBSERVE_INTERVAL_SECONDS` | `0.1` | Интервал наблюдения медиасессий, секунды. |
| `MEDIA_SESSION_TTL_SECONDS` | `120` | Срок неактивного состояния медиасессии, секунды. |
| `MEDIA_AUDIO_MAX_BYTES` | `32000` | Максимум накопленного аудио Media Adapter, байты. |
| `AI_BACKEND` | `faster-whisper` | Backend распознавания; штатно faster-whisper. |
| `AI_TRANSLATION_BACKEND` | `llm` | Переводчик: llm или opus-mt; OPUS требует подготовленных двух моделей. |
| `AI_TRANSCRIPT_NORMALIZATION` | `llm` | Обработка транскрипции: llm или raw; raw сохраняет ASR без литературной очистки. |
| `AI_TRANSLATION_MODEL_ROOT` | `/translation-models` | Путь OPUS-каталогов внутри AI-контейнера; не путь хоста. |
| `AI_TRANSLATION_THREADS` | `2` | Вычислительные потоки OPUS CTranslate2, целое > 0. |
| `AI_TRANSLATION_BEAM_SIZE` | `4` | Ширина поиска OPUS; влияет на скорость и полноту перевода. |
| `AI_STT_CPU_THREADS` | `4` | Число вычислительных CPU-потоков Whisper. |
| `AI_MODEL_SIZE` | `small` | Размер Whisper; менять вместе с ревизией, используйте готовый CPU-профиль. |
| `AI_MODEL_REVISION` | `536b0662742c02347bc0e980a01041f333bce120` | Закреплённая ревизия модели Whisper в Hugging Face. |
| `AI_DEVICE` | `cpu` | Устройство Whisper: cpu либо cuda при подготовленном GPU-образе. |
| `AI_ENABLE_CUDA` | `0` | Build-флаг 0/1 включения CUDA-зависимостей AI Worker; требует пересборки. |
| `AI_CONTAINER_RUNTIME` | `runc` | Docker runtime AI Worker: runc для CPU; NVIDIA требует отдельной подготовки. |
| `AI_GPU_DEVICES` | `void` | Видимость NVIDIA GPU для AI-контейнера: void отключает GPU. |
| `AI_COMPUTE_TYPE` | `int8` | Тип вычислений CTranslate2; CPU-профили используют int8. |
| `AI_LANGUAGE` | `ru` | Исходный язык стандартного ASR; языковые входы переводчика выбирают ru/en отдельно. |
| `AI_VAD_RMS` | `350` | Порог активности речи на PCM16-шкале; не нормализованный float. |
| `AI_UTTERANCE_MIN_SECONDS` | `0.35` | Минимальная длительность реплики, секунды. |
| `AI_UTTERANCE_SILENCE_MS` | `700` | Тишина для завершения обычной реплики, миллисекунды. |
| `AI_UTTERANCE_MAX_SECONDS` | `5` | Максимальная длительность обычной реплики, секунды. |
| `AI_DIALOGUE_UTTERANCE_SILENCE_MS` | `600` | Тишина для границы реплики диалога, миллисекунды. |
| `AI_DIALOGUE_UTTERANCE_MAX_SECONDS` | `10` | Максимум фрагмента диалога, секунды; входит в задержку накопления. |
| `AI_DIALOGUE_EVENT_GAP_MS` | `1200` | Разрыв между событиями аудио для разделения диалога, миллисекунды. |
| `AI_AUDIO_PREROLL_MS` | `200` | Аудио перед обнаруженным началом речи, миллисекунды. |
| `AI_STT_MIN_RMS` | `0.005` | Минимальная энергия для STT на нормализованной float-шкале; не AI_VAD_RMS. |
| `AI_STT_BEAM_SIZE` | `1` | Ширина поиска Whisper; не ширина поиска переводчика. |

## Очереди, контекст и экспериментальный streaming

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `AI_STREAMING_ENABLED` | `0` | 0/1, экспериментальная выдача промежуточного перевода; по умолчанию выключена. |
| `AI_STREAM_INTERVAL_MS` | `300` | Интервал промежуточной обработки, миллисекунды. |
| `AI_STREAM_MIN_WORDS` | `1` | Минимум слов для промежуточного фрагмента. |
| `AI_STREAM_HOLDBACK_WORDS` | `1` | Число удерживаемых последних слов нестабильного ASR-префикса. |
| `AI_STREAM_MAX_REPLIES_PER_CALL` | `24` | Ограничение числа streaming-ответов на вызов. |
| `AI_STREAM_START_DELAY_LIMIT_MS` | `3000` | Порог проверки задержки начала streaming-ответа, мс; не гарантированный SLA. |
| `INTERPRETER_MAX_RESPONSE_DELAY_MS` | `5000` | Порог проверок задержки переводчика, мс; не гарантированная задержка. |
| `TTS_AUDIBLE_RMS` | `100` | PCM16 RMS для обнаружения слышимого переведённого RTP в проверках. |
| `AI_QUEUE_MAX` | `8` | Максимум входных заданий AI-очереди. |
| `AI_UTTERANCE_QUEUE_MAX` | `8` | Максимум заданий выделенных реплик. |
| `AI_PROCESSING_WORKERS` | `2` | Число обработчиков реплик; рост увеличивает конкуренцию за CPU/RAM. |
| `SERVICE_HTTP_THREADS` | `4` | Потоки Waitress внутренних HTTP-сервисов. |
| `AI_REQUEST_MAX_BYTES` | `65536` | Предел размера HTTP-запроса сервисов, байты. |
| `AI_TRANSCRIPT_RETENTION_SECONDS` | `300` | Срок хранения транскрипций в оперативном состоянии, секунды; не срок WAV на диске. |
| `AI_STREAM_BUFFER_MAX` | `64` | Максимальное число буферов аудиопотоков. |
| `AI_STREAM_BUFFER_TTL_SECONDS` | `30` | Срок неактивного аудиобуфера, секунды. |
| `AI_MAX_REPLIES_PER_CALL` | `4` | Предел обычных AI-ответов на вызов; streaming имеет отдельный предел. |
| `AI_CONVERSATION_HISTORY_TURNS` | `4` | Количество сохраняемых ходов контекста LLM; OPUS историю не использует. |
| `AI_CONVERSATION_TTL_SECONDS` | `300` | Срок неактивного контекста диалога, секунды. |
| `AI_MIN_REPLIES_FOR_SMOKE` | `2` | Минимум ответов для smoke-проверки. |
| `AI_MODEL_CACHE` | `/models` | Путь кэша модели внутри контейнера, смонтирован именованный том. |
| `AI_HF_DISABLE_XET` | `1` | 0/1 для HF_HUB_DISABLE_XET при загрузке модели. |
| `AI_REPLY_HTTP_TIMEOUT_SECONDS` | `3` | Таймаут отправки ответа Voice Agent по HTTP, секунды. |
| `AI_EVENT_RETENTION` | `100` | Максимальное число диагностических AI-событий в памяти. |

## Qwen / Ollama и барьеры текста

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `LLM_MODEL` | `unsloth-qwen3-4b-instruct:q4_k_m` | Имя модели в Ollama; должно совпадать с подготовленным загрузчиком. |
| `LLM_GGUF_URL` | `https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | URL закреплённого GGUF для загрузчика; менять вместе с SHA-256. |
| `LLM_GGUF_SHA256` | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` | Ожидаемый SHA-256 GGUF; не отключать проверку при смене модели. |
| `LLM_CONTAINER_RUNTIME` | `runc` | Docker runtime Ollama; CPU = runc. |
| `LLM_GPU_DEVICES` | `void` | Видимость NVIDIA GPU для Ollama; void = CPU. |
| `LLM_CONTEXT_LENGTH` | `2048` | Окно контекста Ollama в токенах. |
| `LLM_WARMUP_TIMEOUT_SECONDS` | `180` | Таймаут прогрева модели, секунды; launcher дополнительно имеет своё окно ожидания. |
| `LLM_URL` | `http://llm-worker:11434/api/chat` | Внутренний Ollama chat endpoint; не внешний облачный API. |
| `LLM_TIMEOUT_SECONDS` | `45` | Таймаут запроса LLM, секунды. |
| `LLM_MAX_TOKENS` | `64` | Максимум генерируемых токенов обычного ответа/перевода. |
| `LLM_TEMPERATURE` | `0` | Температура генерации; 0 уменьшает случайность. |
| `TRANSLATION_MIN_LATIN_CHARS` | `3` | Минимум латинских букв в RU→EN результате; барьер также применяется к OPUS. |
| `TRANSLATION_MAX_CYRILLIC_CHARS` | `0` | Допустимый максимум кириллицы в RU→EN результате. |
| `REVERSE_TRANSLATION_MIN_CYRILLIC_CHARS` | `3` | Минимум кириллицы в EN→RU результате. |
| `REVERSE_TRANSLATION_MAX_LATIN_CHARS` | `0` | Максимум латиницы в EN→RU результате; имена/аббревиатуры могут вызвать отказ. |
| `LLM_SYSTEM_PROMPT` | `"Ты локальный голосовой помощник IMS. Отвечай по-русски одним коротким предложением без Markdown. Учитывай предыдущие реплики текущего звонка."` | Системная инструкция голосового помощника; только LLM-режим. |
| `LLM_TRANSLATION_PROMPT` | `"Translate the user's Russian speech into natural English. Return only the English translation in one short plain sentence. Do not explain, quote the source, or use Markdown. Use prior turns only to resolve context."` | Системная инструкция перевода RU→EN; OPUS её не использует. |
| `LLM_REVERSE_TRANSLATION_PROMPT` | `"Переведи английскую речь на естественный русский язык. Верни только перевод кириллицей одним коротким предложением, без пояснений, кавычек и Markdown. Имена и аббревиатуры передавай кириллицей. Предыдущие реплики используй только для контекста."` | Системная инструкция перевода EN→RU; OPUS её не использует. |
| `LLM_TRANSCRIPTION_PROMPT` | `"Ты выполняешь детерминированную постобработку ASR. Перепиши расшифровку грамотным русским письменным текстом. Обязательно удали междометия и заполнители пауз (а-а, э, э-э, эм, ну), бессодержательные вводные а/но, повторы слов, заикания и оборванные ложные начала. Сохрани итоговый смысл, факты, имена, числа и порядок законченных мыслей. Не отвечай на содержание, не сокращай смысловые фразы и не переводи. Верни только готовый текст без кавычек, заголовка, пояснений и Markdown. Пример: Вход: «А... э-э... я, я хотел сказать, ну, встреча в пять. Но... а... лучше в шесть.» Выход: «Я хотел сказать: встреча в пять. Лучше в шесть.»"` | Правила LLM-очистки русской расшифровки; raw-режим их не применяет. |
| `LLM_ENGLISH_TRANSCRIPTION_PROMPT` | `"You perform deterministic ASR post-processing. Return only polished English transcript text without quotes, headings, explanations, or Markdown. Fix capitalization, punctuation, and obvious recognition errors. Remove hesitation sounds, filler words, stutters, duplicated words, and abandoned false starts only when they add no meaning. Preserve names, numbers, facts, meaning, and utterance order. Do not answer, summarize, or translate the content."` | Правила LLM-очистки английской расшифровки. |
| `LLM_NORMALIZATION_MAX_TOKENS` | `256` | Лимит токенов LLM при нормализации транскрипции. |
| `LLM_NORMALIZATION_MIN_LENGTH_RATIO` | `0.65` | Минимальная доля длины нормализованного текста от исходного, защита от потери содержания. |
| `TRANSCRIPT_NORMALIZED_MAX_CHARS` | `2000` | Ограничение длины нормализованного текста, символы. |
| `LLM_WORKER_CPU_LIMIT` | `4.0` | Квота Docker Ollama в единицах CPU; не резервирование ядер. |
| `LLM_WORKER_MEMORY_LIMIT` | `6g` | Лимит памяти Ollama, синтаксис Docker m/g. |
| `LLM_KEEP_ALIVE` | `-1` | Время удержания модели Ollama; -1 = держать загруженной. |
| `LLM_NUM_PARALLEL` | `1` | Параллельные запросы Ollama; увеличение требует проверки памяти. |

## Услуги и Voice Agent

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `VOICE_AGENT_MSISDN` | `1003` | Номер голосового агента; в стандартной конфигурации совпадает с номером переводчика. |
| `VOICE_TRANSLATOR_MSISDN` | `1003` | Номер услуги RU→EN; менять согласованно с provisioning/iFC. |
| `VOICE_TRANSCRIBER_MSISDN` | `1004` | Номер записи и транскрипции после уведомления. |
| `VOICE_INTERPRETER_RU_MSISDN` | `1005` | Номер русского участника двустороннего перевода; он слышит русский результат. |
| `VOICE_INTERPRETER_EN_MSISDN` | `1006` | Номер английского участника; он слышит английский результат. |
| `VOICE_AGENT_SIP_USER` | `agent` | SIP user голосового агента. |
| `VOICE_TRANSCRIBER_SIP_USER` | `transcriber` | SIP user услуги записи. |
| `VOICE_INTERPRETER_RU_SIP_USER` | `interpreter-ru` | SIP user русского входа переводчика. |
| `VOICE_INTERPRETER_EN_SIP_USER` | `interpreter-en` | SIP user английского входа переводчика. |
| `VOICE_AGENT_HTTP_PORT` | `8093` | Внутренний HTTP-порт Voice Agent. |
| `VOICE_AGENT_RTP_PORT` | `41000` | UDP-порт Voice Agent для медиатракта через RTPengine. |
| `VOICE_AGENT_GREETING` | `"Здравствуйте. Говорите по-русски. Перевод прозвучит на английском языке."` | Начальное звуковое уведомление услуги RU→EN. |
| `VOICE_TRANSCRIBER_GREETING` | `"Внимание. После сигнала разговор записывается для локальной транскрипции."` | Уведомление о локальной записи перед транскрипцией. |
| `VOICE_INTERPRETER_RU_GREETING` | `"Русский канал переводчика подключён. Вы услышите собеседника по-русски."` | Приветствие русского участника. |
| `VOICE_INTERPRETER_EN_GREETING` | `"English interpreter channel connected. You will hear the other speaker in English."` | Приветствие английского участника. |
| `VOICE_AGENT_REPLY` | `"Я вас слышу. Медиатракт IMS работает."` | Статический тестовый ответ при соответствующем режиме агента. |
| `VOICE_AGENT_REPLY_MAX_CHARS` | `240` | Максимальная длина реплики озвучки, символы. |
| `VOICE_AGENT_LLM_MODE` | `1` | 0/1, режим динамического ответа Voice Agent вместо статического; сохраняется 1 и при OPUS, не выбирает backend перевода. |
| `VOICE_AGENT_VAD_RMS` | `350` | PCM16 RMS-порог активности речи Voice Agent. |
| `VOICE_AGENT_SILENCE_MS` | `700` | Порог тишины Voice Agent, миллисекунды. |
| `VOICE_AGENT_CALL_TIMEOUT` | `300` | Срок жизни вызова Voice Agent, секунды. |
| `VOICE_AGENT_MAX_CALLS` | `100` | Лимит активных голосовых вызовов, не доказанная ёмкость; в лёгких профилях 2. |
| `VOICE_AGENT_REPLY_QUEUE_MAX` | `16` | Лимит очереди озвучки одного вызова. |
| `VOICE_AGENT_EVENT_RETENTION` | `100` | Количество диагностических событий Voice Agent в памяти. |

## Синтез речи

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `TTS_BACKEND` | `piper` | piper или espeak-ng; Piper естественнее, eSpeak требует меньше RAM. |
| `PIPER_VERSION` | `1.8.0` | Версия Piper при сборке образа, требует пересборки Voice Agent. |
| `PIPER_MODEL_URL` | `https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/ru/ru_RU/denis/medium/ru_RU-denis-medium.onnx` | Закреплённый URL русской ONNX-модели; конфигурация берётся рядом с моделью. |
| `PIPER_MODEL_SHA256` | `15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a` | SHA-256 русской ONNX-модели при сборке. |
| `PIPER_CONFIG_SHA256` | `831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8` | SHA-256 JSON-конфигурации русского голоса. |
| `PIPER_MODEL_PATH` | `/opt/tts/ru_RU-denis-medium.onnx` | Путь русской модели внутри образа; согласовать с build args. |
| `PIPER_LENGTH_SCALE` | `1.0` | Множитель длительности русского голоса; больше = медленнее. |
| `PIPER_THREADS` | `1` | Вычислительные потоки Piper/ONNX Runtime; синтез голосов сериализован. |
| `PIPER_CPU_MEM_ARENA` | `1` | 0/1, CPU memory arena ONNX; 0 уменьшил память в измеренных CPU-профилях. |
| `PIPER_EN_MODEL_URL` | `https://huggingface.co/rhasspy/piper-voices/resolve/c10ece1aade47bb51c153c893d14e5bf8e5b7117/en/en_US/ljspeech/medium/en_US-ljspeech-medium.onnx` | Закреплённый URL английской ONNX-модели. |
| `PIPER_EN_MODEL_SHA256` | `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22` | SHA-256 английской ONNX-модели. |
| `PIPER_EN_CONFIG_SHA256` | `141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860` | SHA-256 JSON-конфигурации английского голоса. |
| `PIPER_EN_MODEL_PATH` | `/opt/tts/en_US-ljspeech-medium.onnx` | Путь английской модели внутри образа. |
| `PIPER_EN_LENGTH_SCALE` | `1.0` | Множитель длительности английского голоса. |
| `TTS_VOICE` | `ru` | Русский голос eSpeak; Piper выбирается ONNX-файлом. |
| `TTS_TRANSLATION_VOICE` | `en-us` | Английский голос eSpeak. |
| `TTS_RATE` | `145` | Темп eSpeak, слов/мин; не управляет скоростью Piper. |

## Хранение, доступ и ограничения контейнеров

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `RECORDING_ENABLED` | `1` | 0/1, разрешение услуги записи; обычные звонки не становятся записываемыми автоматически. |
| `RECORDING_ROOT` | `/recordings` | Корень записей внутри AI-контейнера; на хосте local/private/recordings. |
| `RECORDING_MAX_BYTES_PER_CALL` | `16000000` | Лимит записываемого аудио одного вызова, байты. |
| `RECORDING_RETENTION_DAYS` | `7` | Срок хранения записей, дни; удаление оператором, не фоновая гарантия очистки. |
| `SERVICE_CONTROL_TOKEN_FILE` | `/run/lab-control/token` | Путь общего токена внутренних HTTP API внутри контейнеров. |
| `SERVICE_CONTROL_TOKEN_BYTES` | `32` | Число случайных байт нового токена до base64; существующий токен не ротируется. |
| `CUSTOM_SERVICE_CPU_LIMIT` | `1.0` | Общая CPU-квота собственных сервисов, если сервис не переопределяет её. |
| `CUSTOM_SERVICE_MEMORY_LIMIT` | `256m` | Общий Docker-лимит памяти собственных сервисов, если нет отдельного. |
| `AI_WORKER_CPU_LIMIT` | `4.0` | CPU-квота AI Worker; согласовать с числом вычислительных потоков. |
| `AI_WORKER_MEMORY_LIMIT` | `2g` | Лимит памяти AI Worker, синтаксис Docker m/g. |
| `VOICE_AGENT_MEMORY_LIMIT` | `512m` | Лимит памяти Voice Agent; учесть оба голоса и FFmpeg, не только ONNX-веса. |
| `CUSTOM_SERVICE_PIDS_LIMIT` | `128` | Максимум процессов/потоков контейнера по Docker pids limit. |
| `CUSTOM_SERVICE_LOG_MAX_SIZE` | `10m` | Размер одного файла json-file Docker-журнала, например 10m. |
| `CUSTOM_SERVICE_LOG_MAX_FILES` | `3` | Число файлов ротации Docker-журнала. |
| `PYHSS_API_BIND` | `127.0.0.1` | Адрес публикации PyHSS API на хосте; по умолчанию только loopback. |
| `PYHSS_API_PORT` | `8080` | Порт PyHSS API на хосте для provisioning. |
| `PYHSS_API_CONTAINER_PORT` | `8080` | Внутренний порт REST PyHSS. |
| `LOOPBACK_IP` | `127.0.0.1` | Loopback для служебных проверок/конфигураций. |
| `DNS_UPSTREAM_PRIMARY` | `8.8.8.8` | Первый внешний DNS для запросов вне IMS-зоны. |
| `DNS_UPSTREAM_SECONDARY` | `8.8.4.4` | Резервный внешний DNS. |
| `INTERNET_PROBE_IP` | `8.8.8.8` | Адрес проверки internet-доступа; не сервис IMS. |

## Статические адреса и Diameter

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `UPF_IP` | `172.22.0.3` | Адрес UPF в LAN; локальный next hop IMS при пустом IMS_ROUTE_GATEWAY. |
| `SCP_IP` | `172.22.0.5` | Legacy Open5GS SCP/N5 placeholder; не означает включённую policy-интеграцию OAI. |
| `DNS_IP` | `172.22.0.100` | Адрес DNS IMS; передать ядру для выдачи UE. |
| `RTPENGINE_IP` | `172.22.0.101` | Адрес медиареле и сетевого пространства Media Adapter. |
| `MYSQL_IP` | `172.22.0.102` | Адрес IMS MySQL; не база OAI UDR. |
| `PYHSS_IP` | `172.22.0.103` | Адрес IMS HSS для Diameter Cx. |
| `PYHSS_BIND_PORT` | `3868` | Порт Diameter PyHSS. |
| `ICSCF_IP` | `172.22.0.104` | Статический адрес I-CSCF. |
| `ICSCF_BIND_PORT` | `3869` | Локальный Diameter-порт I-CSCF; не SIP-порт. |
| `SCSCF_IP` | `172.22.0.105` | Статический адрес S-CSCF. |
| `SCSCF_BIND_PORT` | `3870` | Локальный Diameter-порт S-CSCF. |
| `PCSCF_IP` | `172.22.0.106` | Адрес P-CSCF, выдаваемый UE для IMS-регистрации. |
| `PCSCF_BIND_PORT` | `3871` | Diameter-порт P-CSCF в vendor-конфигурации; не доказательство активного Rx. |
| `SIP_AS_IP` | `172.22.0.107` | Адрес собственного SIP Application Server. |
| `AI_WORKER_IP` | `172.22.0.109` | Адрес AI Worker во внутренней сервисной LAN. |
| `VOICE_AGENT_IP` | `172.22.0.110` | Адрес Voice Agent во внутренней сервисной LAN. |
| `PCRF_BIND_PORT` | `3873` | Legacy vendor placeholder PCRF/Rx; policy в текущем профиле не включена. |

## Образы, OAI и внешний стенд

| Параметр | Значение в lab.env | Назначение и ограничения |
| --- | --- | --- |
| `CONTROL_INIT_IMAGE` | `alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` | Закреплённый образ генератора внутреннего токена. |
| `KAMAILIO_IMAGE` | `ghcr.io/herlesupreeth/docker_kamailio@sha256:efc9df818c239d28cd61a822d62ce0201b6ca3047f6fa653233bfa84498510de` | Закреплённый базовый образ Kamailio. |
| `SCSCF_IMAGE` | `lab-kamailio-scscf:987459-expiry-v1` | Имя собираемого S-CSCF образа с локальными исправлениями. |
| `MONGO_IMAGE` | `mongo:8.0` | Legacy Mongo/Open5GS образ; не используется активным OAI compose. |
| `MYSQL_IMAGE` | `ghcr.io/herlesupreeth/docker_mysql@sha256:a03ac89dbc7de0b0d75e5600ae6542ad9abb620a3c71848ba715a0a5926f81fc` | Закреплённый образ IMS MySQL. |
| `OLLAMA_IMAGE` | `ollama/ollama@sha256:da6e0dc5651df159e45686fd663c4dbe1624a52c44d7280eeac1551d8f865532` | Закреплённый образ Ollama, только LLM-профиль. |
| `OPEN5GS_IMAGE` | `gradiant/open5gs:2.7.7` | Legacy образ Open5GS для отката; смена одной переменной не переключает ядро. |
| `PYHSS_IMAGE` | `ghcr.io/herlesupreeth/docker_pyhss@sha256:67876ced93002181933d706cb047ffee9f855f3f61a43b184a01981987853a82` | Закреплённый образ IMS HSS. |
| `UERANSIM_IMAGE` | `gradiant/ueransim:3.2.6` | Образ локальных эмуляторов RAN/UE. |
| `INTERNET_UE_IPV6_GATEWAY_CIDR` | `2001:db8:cafe::1/48` | Legacy IPv6 internet-шлюз; не подтверждает IPv6-профиль текущего OAI. |
| `RESEARCH_GATE_TIMEOUT_SECONDS` | `300` | Таймаут исследовательского гейта, секунды. |
| `CORE_IMPLEMENTATION` | `oai` | Метка текущего ядра oai; состав задаётся compose include, не этим значением в одиночку. |
| `OAI_TAC` | `1` | Tracking Area Code локальной сети; согласовать с gNB. |
| `OAI_HTTP_PORT` | `8080` | Внутренний HTTP-порт SBI функций OAI. |
| `OAI_HTTP_TIMEOUT_MS` | `10000` | Таймаут HTTP OAI, миллисекунды. |
| `OAI_MYSQL_IMAGE` | `mysql:8.0.43@sha256:3e646bcda0d9448ffa3d2024eef04e1bca95528ec19b9e8b76749da9d97d4a10` | Закреплённая отдельная база OAI UDR. |
| `OAI_NRF_IMAGE` | `oaisoftwarealliance/oai-nrf:v2.2.1@sha256:5b8da12e26b703adaafc422aa1a77736fa1b16f3b340fa8f0f5034da0cc796de` | Закреплённый образ OAI NRF. |
| `OAI_UDR_IMAGE` | `oaisoftwarealliance/oai-udr:v2.2.1@sha256:c9aaa39f0b0b96969fe968fd2c3e84ad7dcd4a50fcee83bd5abde6d6d4a31695` | Закреплённый образ OAI UDR. |
| `OAI_UDM_IMAGE` | `oaisoftwarealliance/oai-udm:v2.2.1@sha256:464d5183034983e9bed47f591b6b03a7374a0aef8a7c84b48a437141bb3ee798` | Закреплённый образ OAI UDM. |
| `OAI_AUSF_IMAGE` | `oaisoftwarealliance/oai-ausf:v2.2.1@sha256:ff3fe0537f05de798519ba303a40ed0a0284da5ddd265d8392e8fd7a3afef3cc` | Закреплённый образ OAI AUSF. |
| `OAI_AMF_IMAGE` | `oaisoftwarealliance/oai-amf:v2.2.1@sha256:c6dee19b65b2bf29b73e6647f98e0381d96a2eb4c6f9a68f5c3bc70534afa14c` | Закреплённый образ OAI AMF. |
| `OAI_SMF_IMAGE` | `oaisoftwarealliance/oai-smf:v2.2.1@sha256:c1f1452edfc835c36aa96a2efca337da0149212a6561bbb5f9b1994356beee24` | Закреплённый образ OAI SMF. |
| `OAI_UPF_IMAGE` | `oaisoftwarealliance/oai-upf:v2.2.1@sha256:03985036c2477a75755ded9b7fe9508b62f49e4ce9e9f059bbb68af63932e7f7` | Закреплённый образ OAI UPF. |
| `UPF_INTERNET_TUN` | `tun0` | Имя TUN UPF для internet-маршрутов; в OAI оба DNN используют tun0. |
| `UPF_IMS_TUN` | `tun0` | Имя TUN UPF для IMS-маршрутов; не имя интерфейса на UE. |
| `IMS_ROUTE_GATEWAY` | пусто | Для partner обязателен IPv4 next hop в IMS LAN к UE-пулам; локально пусто = UPF_IP. |
| `IMS_PARENT_INTERFACE` | пусто | Для partner обязателен Linux-интерфейс macvlan, например ens192; локально пусто. |
