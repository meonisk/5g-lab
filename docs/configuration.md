# Настройка стенда

Все публичные значения по умолчанию находятся в `lab.env`. Он читается Compose,
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
| LLM | `LLM_MODEL`, `LLM_MODEL_DIGEST`, `LLM_*PROMPT`, `LLM_TIMEOUT_SECONDS`, `LLM_KEEP_ALIVE`, `LLM_NUM_PARALLEL` |
| Синтез речи | `TTS_BACKEND`, `TTS_VOICE`, `TTS_TRANSLATION_VOICE`, `TTS_RATE` |
| Приватные записи | `RECORDING_*` |
| Нагрузка | `*_CPU_LIMIT`, `*_MEMORY_LIMIT`, `AI_QUEUE_MAX`, `CUSTOM_SERVICE_*` |
| HTTP AI Worker | `AI_WORKER_BIND`, `AI_WORKER_PORT`, `AI_REPLY_HTTP_TIMEOUT_SECONDS` |
| Исследовательские проверки | `RESEARCH_GATE_TIMEOUT_SECONDS`, `BILINGUAL_DIALOGUE_*` |

Пароли и ключи абонентов находятся в `secrets/ims.env`. Токен внутренних API
создаётся в приватном Docker-томе; в публичный env он не попадает.

Текст, голоса и расписание синтетического разговора описаны в
`fixtures/bilingual-dialogue-v1.json`. Это входные данные теста. После изменения
запустите `scripts/generate-bilingual-dialogue.ps1`; продолжительность воспроизведения
в `lab.env` должна покрывать все реплики и не достигать повторного начала WAV.

Версии образов сохранены прежними. При изменении версии модели меняйте также её
revision/digest и запускайте admission. PCMU/8000, структура RTP и формат SIP
остаются протокольными контрактами: произвольное изменение частоты через env
без изменения всей цепочки не поддерживается.
