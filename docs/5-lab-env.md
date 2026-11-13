# 5. Файл настроек lab.env

[app/config/lab.env](../app/config/lab.env) — единственный файл настроек стенда. Его
читают Docker Compose (через `--env-file`) и все скрипты. Адресов, номеров и ключей в
коде нет: `check.py` это проверяет.

**Как применить изменения:** `python3 scripts/start.py`. Он проверит файл и пересоздаст
контейнеры, у которых изменились параметры. Если менялись услуги или абоненты —
затем `docker restart lab-scscf`. Команда `docker restart` без `start.py` новые
значения не подхватывает.

**Режим AI важнее файла.** Режим (`AI_MODE`, по умолчанию `compact`) заменяет часть
значений своими из [ai-profiles.json](../app/config/ai-profiles.json). Например, в
`compact` действуют `AI_MODEL_SIZE=base`, `AI_STT_CPU_THREADS=2`,
`AI_WORKER_CPU_LIMIT=2.0`, `AI_TRANSLATION_BACKEND=opus-mt`, хотя в `lab.env` записано
другое. Ниже такие переменные помечены «(режим)».

## Сеть

| Переменная | Значение | Что это |
|---|---|---|
| `MCC`, `MNC` | `001`, `01` | код страны и оператора, как в ядре и на SIM |
| `IMS_DOMAIN` | `ims.mnc001.mcc001.3gppnetwork.org` | домен IMS; строится из MCC и MNC по правилу 3GPP |
| `CORE_NETWORK_NAME` | `oai-cn5g-public-net` | Docker-сеть ядра (`docker network ls`) |
| `LAB_NETWORK_CIDR` | `192.168.70.128/26` | её подсеть; все адреса стенда внутри неё |
| `UPF_IP` | `.134` | UPF ядра; через него контейнеры отвечают телефонам |
| `IMS_UE_CIDR` | `10.0.9.0/24` | адреса телефонов в сети данных `ims` (из конфигурации SMF) |
| `INTERNET_UE_CIDR` | `10.0.0.0/16` | все адреса телефонов; для них UPF делает NAT в интернет |
| `IMS_DNN` | `ims` | имя сети данных для IMS |
| `DNS_IP` … `SIPUE2_IP` | `.160` … `.171` | постоянные адреса контейнеров стенда; должны быть свободны в сети ядра |
| `LLM_INIT_IP` | `.172` | адрес загрузчика модели Qwen, нужен только во время скачивания |
| `SCP_IP` | `.166` | заглушка для шаблонов P-CSCF, не используется |
| `DNS_UPSTREAM_PRIMARY`, `_SECONDARY` | `8.8.8.8`, `8.8.4.4` | куда наш DNS пересылает имена не из IMS |

## Абоненты

Четыре абонента; у каждого одинаковый набор переменных с префиксом `UE1_`, `UE2_`,
`SIPUE1_`, `SIPUE2_`.

| Переменная | Пример | Что это |
|---|---|---|
| `<П>_IMSI` | `001010000000001` | номер SIM; первые цифры — MCC и MNC |
| `<П>_MSISDN` | `1001` | телефонный номер |
| `<П>_IMS_K`, `<П>_IMS_OPC` | 32 hex-символа | секретные ключи SIM; у телефонов должны совпадать с картой и с базой ядра (UDR) |
| `<П>_IMS_AMF` | `8000` | служебное поле аутентификации; не менять |
| `<П>_SERVICES` | `translate,record` | услуги абонента через запятую; пусто — без услуг |
| `<П>_LANGUAGE` | `ru` | язык абонента: `ru` или `en` |
| `DEFAULT_LANGUAGE` | `ru` | язык, если у абонента он не указан |

`UE1`, `UE2` — настоящие телефоны (вход по ключам SIM). `SIPUE1`, `SIPUE2` — тестовые
клиенты: входят по паролю, пароль — их ключ K. Ключи в файле лабораторные. Если
записать ключи настоящих SIM, файл нельзя публиковать.

## Номера и тексты услуг

| Переменная | Значение | Что это |
|---|---|---|
| `VOICE_TRANSLATOR_MSISDN` (`VOICE_AGENT_MSISDN`) | `1003` | переводчик для звонящего |
| `VOICE_TRANSCRIBER_MSISDN` | `1004` | запись и расшифровка |
| `VOICE_INTERPRETER_RU_MSISDN`, `_EN_` | `1005`, `1006` | двусторонний перевод |
| `VOICE_*_SIP_USER` | `agent`, `transcriber`, ... | внутренние SIP-имена тех же услуг |
| `VOICE_*_GREETING` | текст | приветствие на номере услуги |
| `VOICE_AGENT_REPLY` | текст | ответ, если языковая модель выключена |
| `RECORDING_ANNOUNCEMENT_RU`, `_EN` | текст | уведомление перед записью; звук не длиннее 6 с |

## Порты

| Переменная | Значение | Что это |
|---|---|---|
| `PCSCF_SIP_PORT`, `ICSCF_SIP_PORT`, `SCSCF_SIP_PORT` | 5060, 5060, 6060 | SIP-порты серверов IMS |
| `*_BIND_PORT` | 3868–3873 | порты Diameter (обмен CSCF с HSS) |
| `PYHSS_API_BIND`, `PYHSS_API_PORT` | `127.0.0.1`, 8088 | REST API базы абонентов на компьютере (только локально) |
| `RTPENGINE_PORT_MIN`, `_MAX` | 30000, 30100 | диапазон портов для звука |
| `RTPENGINE_NG_PORT` | 2223 | порт управления RTPengine |
| `SIP_AS_PORT` | 5070 | сервер услуг |
| `MEDIA_ADAPTER_PORT`, `AI_WORKER_PORT`, `VOICE_AGENT_HTTP_PORT` | 8091, 8092, 8093 | внутренние HTTP-порты сервисов AI |
| `VOICE_AGENT_RTP_PORT` | 41000 | с этого порта Voice Agent отправляет звук |

`PCRF_BIND_PORT`, `PCSCF_UDP_MTU`, `RTPENGINE_CLI_PORT`, `LOOPBACK_IP` — служебные
значения шаблонов Kamailio; менять не нужно.

## Распознавание речи

| Переменная | Значение | Что это |
|---|---|---|
| `AI_MODEL_SIZE` (режим) | `base` в compact | модель Whisper: `tiny`, `base`, `small` — больше значит точнее и медленнее |
| `AI_MODEL_REVISION` (режим) | хеш | точная версия модели; модель скачивается именно эта |
| `AI_STT_CPU_THREADS` (режим) | 2 в compact | потоков распознавания; больше лимита процессора контейнера — медленнее |
| `AI_LANGUAGE` | `ru` | язык распознавания для переводчика 1003 |
| `AI_STT_BEAM_SIZE` | 1 | ширина поиска Whisper; 1 — быстрее всего |
| `AI_STT_MIN_RMS` | 0.005 | слишком тихий звук не распознаётся |
| `AI_DEVICE`, `AI_COMPUTE_TYPE` | `cpu`, `int8` | на чём и с какой точностью считать |
| `AI_ENABLE_CUDA`, `AI_CONTAINER_RUNTIME`, `AI_GPU_DEVICES` | `0`, `runc`, `void` | видеокарта выключена |
| `AI_MODEL_CACHE`, `AI_HF_DISABLE_XET` | `/models`, `1` | где хранить модели в контейнере, способ скачивания |

## Деление речи на фразы

| Переменная | Значение | Что это |
|---|---|---|
| `AI_VAD_RMS` | 350 | порог громкости: тише — считается тишиной |
| `AI_UTTERANCE_SILENCE_MS` | 700 | сколько тишины означает конец фразы. Меньше — быстрее ответ, но фраза может оборваться на вдохе |
| `AI_UTTERANCE_MIN_SECONDS` | 0.35 | короче — не фраза, а шум |
| `AI_UTTERANCE_MAX_SECONDS` | 5 | длинная речь без пауз режется на куски по 5 с |
| `AI_DIALOGUE_UTTERANCE_*`, `AI_DIALOGUE_EVENT_GAP_MS` | 600 мс, 10 с, 1200 мс | то же для двустороннего перевода 1005/1006 и услуги translate; на пределе 10 с фраза режется по самой длинной паузе внутри неё |
| `AI_DIALOGUE_SHORT_PAUSE_MS`, `AI_DIALOGUE_SHORT_PAUSE_AFTER_SECONDS` | 250 мс, 2,5 с | в переводе фраза длиннее 2,5 с заканчивается уже на паузе 250 мс — обычно это граница предложения |
| `AI_AUDIO_PREROLL_MS` | 200 | сколько звука до начала речи добавить к фразе |
| `AI_STREAMING_ENABLED`, `AI_STREAM_*` | `0` | потоковый перевод до конца фразы; экспериментальный, выключен |
| `INTERPRETER_MAX_RESPONSE_DELAY_MS` | 5000 | предел задержки в тесте `verify_interpreter.py` |
| `TTS_AUDIBLE_RMS` | 100 | с какой громкости пакет считается «первым звуком перевода» в замерах |

## Перевод и языковая модель

| Переменная | Значение | Что это |
|---|---|---|
| `AI_MODE` | `compact` | режим AI по умолчанию: `compact`, `minimal`, `balanced`, `baseline` |
| `AI_TRANSLATION_BACKEND` (режим) | `opus-mt` в compact | чем переводить: `opus-mt` или `llm` (Qwen) |
| `AI_TRANSCRIPT_NORMALIZATION` (режим) | `raw` в compact | чистить ли текст записи языковой моделью |
| `AI_TRANSLATION_THREADS`, `AI_TRANSLATION_BEAM_SIZE` | 2, 4 | потоки и ширина поиска OPUS-MT |
| `AI_TRANSLATION_MODEL_ROOT` | `/translation-models` | где модели OPUS-MT в контейнере |
| `LLM_MODEL`, `LLM_GGUF_URL`, `LLM_GGUF_SHA256` | Qwen3-4B | модель для `baseline`; меняются все три вместе |
| `LLM_*_PROMPT` | текст | инструкции модели для ответа, перевода и чистки текста |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE` | 45, 64, 0 | ожидание ответа, длина, случайность (0 — без случайности) |
| `LLM_CONTEXT_LENGTH`, `LLM_KEEP_ALIVE`, `LLM_NUM_PARALLEL` | 2048, -1, 1 | размер контекста, держать модель в памяти, параллельных запросов |
| `LLM_CONTAINER_RUNTIME`, `LLM_GPU_DEVICES` | `runc`, `void` | видеокарта для модели выключена |
| `TRANSLATION_*`, `REVERSE_TRANSLATION_*` | числа | проверка, что перевод на нужном алфавите (латиница/кириллица) |

## Синтез речи

| Переменная | Значение | Что это |
|---|---|---|
| `TTS_BACKEND` | `piper` | синтезатор; `espeak` — запасной |
| `TTS_VOICE`, `TTS_TRANSLATION_VOICE` | `ru`, `en-us` | голос для русского и английского |
| `TTS_RATE` | 145 | скорость речи тестовых клиентов (espeak-ng) |
| `PIPER_MODEL_URL`, `PIPER_*_SHA256`, `PIPER_MODEL_PATH` | ссылка, хеши, путь | русский голос Piper; меняется только пересборкой образа `voice-agent` |
| `PIPER_EN_*` | то же | английский голос |
| `PIPER_LENGTH_SCALE` | 1.0 | темп: больше 1 — медленнее |
| `PIPER_THREADS` | 1 | потоков синтеза |

## Голосовой агент, очереди, запись

| Переменная | Значение | Что это |
|---|---|---|
| `VOICE_AGENT_MAX_CALLS` (режим) | 2 в compact | сколько звонков на услуги одновременно |
| `VOICE_AGENT_CALL_TIMEOUT` | 300 | максимальная длина звонка на услугу, с |
| `VOICE_AGENT_REPLY_QUEUE_MAX` | 16 | очередь озвучки на один звонок |
| `AI_PROCESSING_WORKERS` (режим) | 1 в compact | сколько фраз распознаётся одновременно |
| `AI_QUEUE_MAX`, `AI_UTTERANCE_QUEUE_MAX` | 8, 8 | размер очередей; лишнее отбрасывается |
| `AI_MAX_REPLIES_PER_CALL`, `AI_CONVERSATION_*` | 4, 4, 300 | ответы агента 1003 за звонок и история разговора для языковой модели |
| `AI_INTERPRETER_MAX_REPLIES_PER_CALL` | 2000 | переводов за звонок (1005/1006, услуга translate); предел только от зацикливания |
| `AI_*_RETENTION*`, `AI_EVENT_RETENTION` | числа | сколько хранить события в памяти для тестов и замеров |
| `MEDIA_OBSERVE_INTERVAL_SECONDS` | 0.1 | звук идёт в AI кусками по 100 мс |
| `MEDIA_SESSION_TTL_SECONDS` | 120 | забыть звонок, если от него долго нет звука |
| `RECORDING_ENABLED` | 1 | разрешить запись |
| `RECORDING_RETENTION_DAYS` | 7 | через сколько дней удалять записи |
| `RECORDING_MAX_BYTES_PER_CALL` | 16000000 | предел размера одной записи |

## Ресурсы, безопасность, образы

| Переменная | Значение | Что это |
|---|---|---|
| `AI_WORKER_CPU_LIMIT` (режим) | 2.0 в compact | сколько ядер процессора может занять AI Worker |
| `*_MEMORY_LIMIT` | `256m` … `6g` | предел памяти контейнера; при превышении он перезапускается |
| `CUSTOM_SERVICE_CPU_LIMIT`, `_PIDS_LIMIT` | 1.0, 128 | пределы для остальных наших сервисов |
| `CUSTOM_SERVICE_LOG_MAX_SIZE`, `_FILES` | `10m`, 3 | размер и число файлов журнала |
| `SERVICE_CONTROL_TOKEN_*` | путь, 32 | внутренний токен, которым сервисы подтверждают HTTP-запросы друг к другу |
| `SIP_UE_*`, `INTERPRETER_DIALOGUE_*` | — | параметры тестовых клиентов: автоответ, фраза, кодек, файлы диалога |
| `SIP_AS_LEG_B_ROUTE` | `isc` | как второй звонок переводчика возвращается в S-CSCF; не менять |
| `*_IMAGE` | имя@sha256 | закреплённые версии сторонних образов; после смены повторить все проверки |
