# Карта проекта

Пути указаны относительно корня репозитория. В `app/` ровно пять разделов:
`services`, `infrastructure`, `tests`, `research`, `config`.
Команды находятся в `scripts/`, документация в `docs/`, локальные данные в `local/`.

| Каталог / файл | Ответственность |
| --- | --- |
| `docker-compose.yml` | Короткая точка сборки стенда, сети и тома |
| `app/infrastructure/compose/core.yml` | Open5GS и база абонентов |
| `app/infrastructure/compose/access.yml` | gNB, UE и SIP-клиенты |
| `app/infrastructure/compose/ims.yml` | DNS, HSS, CSCF и RTPengine |
| `app/infrastructure/compose/ai.yml` | SIP AS, Media Adapter, AI Worker, LLM, Voice Agent |
| `app/tests/fixtures/docker-compose.dialogue.yml` | Подключение двух локальных WAV для теста |
| `app/tests/fixtures/docker-compose.interpreter.yml` | Два языковых входа и WAV полного перевода |
| `app/tests/fixtures/docker-compose.parallel.yml` | Одинаковые WAV для проверки параллельной обработки |
| `app/config/lab.env` | Публичные параметры, образы, лимиты, модели, топология |
| `app/config/ims.env.example`, `local/secrets/` | Шаблон и игнорируемые локальные ключи |
| `app/infrastructure/configs/` | Шаблоны конфигураций сетевых компонентов |
| `app/services/` | Собственные Python-сервисы и их Dockerfile |
| `app/infrastructure/images/` | Образы инфраструктурных утилит |
| `scripts/` | Запуск, provisioning и совместимые команды оператора |
| `scripts/quality/` | Автоматические проверки правил разработки |
| `app/tests/unit/` | Быстрые проверки без контейнеров и скачивания моделей |
| `app/tests/integration/` | Проверки работающего IMS-стенда |
| `app/tests/fixtures/` | Текстовые сценарии синтетических разговоров |
| `app/research/` | Дизайны, схемы и модульный сборщик evidence |
| `docs/` | Устройство проекта, настройка, перенос на физический стенд |
| `docs/hardening/` | Модель развёртывания, решения по защите и масштабированию |
| `app/infrastructure/vendor/` | Сторонние файлы с отдельной лицензией и provenance |
| `local/private/` | Локальные WAV и записи, исключённые из Git |
| `local/evidence/` | Локальные результаты admission/research, исключённые из Git |

## Где менять поведение

AI Worker: `app/services/ai-worker/ims_ai/`.

- `settings.py`: параметры из env с единицами измерения.
- `runtime.py`: очередь, блокировка, буферы, модель, контекст звонков.
- `audio.py`: декодирование PCMU и энергия кадра.
- `segmentation.py`: границы реплик по тишине и промежуткам RTP.
- `models.py`: загрузка фиксированной версии Whisper.
- `utterances.py`: STT → нормализация/ответ → сохранение или доставка.
- `llm.py`: запросы к локальной LLM и проверки текста.
- `recording.py`: приватные WAV, транскрипция и manifest.
- `lifecycle.py`: очередь обработки и сохранение хвоста при BYE.
- `maintenance.py`: удаление устаревшего состояния из памяти.
- `api.py`: HTTP-аутентификация, приём аудио и статус.
- `app.py`: запуск потоков и HTTP-сервера.

SIP AS: `app/services/sip-as/ims_sip/`: сообщения, управление сервисами и маршрутизация.
Voice Agent: `app/services/voice-agent/ims_voice/`: синтез, RTP, HTTP-управление.
Media Adapter: `app/services/media-adapter/ims_media/`: захват RTP, публикация, API.
Файлы `worker.py`, `server.py`, `agent.py`, `adapter.py` — короткие точки входа.

Сборщик исследований: `app/research/tools/ims_app/research/`: CLI, общие функции,
инвентаризация, сбор, приватность и валидация. `research_run.py` сохраняет CLI.

Compose include использует корень проекта как `project_directory`: относительные
пути томов и `app/config/lab.env` не зависят от расположения фрагмента. Запускайте Compose
через `scripts/compose.ps1` или `scripts/compose.sh`, которые передают оба env.
