# Карта проекта

Пути в таблице указаны относительно `app/`. В корне репозитория остаются
README, CONTRIBUTING, CHANGELOG и три операторские команды в `scripts/`.

| Каталог / файл | Ответственность |
| --- | --- |
| `docker-compose.yml` | Короткая точка сборки стенда, сети и тома |
| `deploy/compose/core.yml` | Open5GS и база абонентов |
| `deploy/compose/access.yml` | gNB, UE и SIP-клиенты |
| `deploy/compose/ims.yml` | DNS, HSS, CSCF и RTPengine |
| `deploy/compose/ai.yml` | SIP AS, Media Adapter, AI Worker, LLM, Voice Agent |
| `docker-compose.dialogue.yml` | Подключение двух локальных WAV для теста |
| `docker-compose.interpreter.yml` | Два языковых входа и WAV полного перевода |
| `docker-compose.parallel.yml` | Одинаковые WAV для проверки параллельной обработки |
| `lab.env` | Публичные параметры, образы, лимиты, модели, топология |
| `secrets/` | Пример секретов и игнорируемый локальный env |
| `configs/` | Шаблоны конфигураций сетевых компонентов |
| `services/` | Собственные Python-сервисы и их Dockerfile |
| `images/` | Образы инфраструктурных утилит |
| `scripts/` | Запуск, provisioning и совместимые команды оператора |
| `tools/quality/` | Автоматические проверки правил разработки |
| `tests/unit/` | Быстрые проверки без контейнеров и скачивания моделей |
| `tests/integration/` | Проверки работающего IMS-стенда |
| `fixtures/` | Текстовые сценарии синтетических разговоров |
| `research/` | Дизайны, схемы и модульный сборщик evidence |
| `docs/` | Устройство проекта, настройка, перенос на физический стенд |
| `hardening/` | Модель развёртывания, решения по защите и масштабированию |
| `vendor/` | Сторонние файлы с отдельной лицензией и provenance |
| `private/` | Локальные WAV и записи, исключённые из Git |
| `evidence/` | Локальные результаты admission/research, исключённые из Git |

## Где менять поведение

AI Worker: `services/ai-worker/ims_ai/`.

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

SIP AS: `services/sip-as/ims_sip/`: сообщения, управление сервисами и маршрутизация.
Voice Agent: `services/voice-agent/ims_voice/`: синтез, RTP, HTTP-управление.
Media Adapter: `services/media-adapter/ims_media/`: захват RTP, публикация, API.
Файлы `worker.py`, `server.py`, `agent.py`, `adapter.py` — короткие точки входа.

Сборщик исследований: `research/tools/ims_research/`: CLI, общие функции,
инвентаризация, сбор, приватность и валидация. `research_run.py` сохраняет CLI.

Compose include использует корень проекта как `project_directory`: относительные
пути томов и `lab.env` не зависят от расположения фрагмента. Запускайте Compose
через `scripts/compose.ps1` или `scripts/compose.sh`, которые передают оба env.
