# Приложение: OAI, IMS и AI

Здесь находятся исходники, настройки и проверки стенда. Начните с задачи:

| Что нужно найти | Куда перейти |
| --- | --- |
| **OAI CN5G — наше локальное тестовое ядро** | [core-oai.yml](infrastructure/compose/core-oai.yml), [как устроена интеграция](../docs/oai-migration.md) |
| **IMS — регистрация абонентов и звонки** | [ims.yml](infrastructure/compose/ims.yml), [карта инфраструктуры](infrastructure/README.md) |
| **AI — распознавание, перевод и голосовой ответ** | [наши сервисы](services/README.md), [ai.yml](infrastructure/compose/ai.yml) |
| **Передать IMS + AI партнёрам с их OAI** | [инструкция подключения](../docs/partner-integration.md), [compose.partner.yml](../compose.partner.yml) |
| **Адреса, номера услуг, модели и лимиты** | [настройки](config/README.md) |
| **Проверить работу** | [тесты](tests/README.md) |
| **Подключить настоящий телефон** | [требования и незакрытые проверки](../docs/native-phone.md) |
| **Исследования и измерения** | [research](research/README.md) |

## Пять разделов

```text
app/
├── config/          Общие настройки оператора и шаблон секретов
├── infrastructure/  Развёртывание OAI, IMS, эмуляторов и зависимостей
├── services/        Наш код: SIP AS, Media Adapter, AI Worker, Voice Agent
├── tests/           Проверки кода, стенда и синтетические сценарии
└── research/        Дизайны исследований и сбор результатов
```

В локальном стенде эмуляторы подключаются к OAI, затем к IMS. IMS управляет
звонками; RTPengine передаёт звук между абонентами и AI-сервисами. Для партнёров
запускается наша IMS + AI часть, подключённая к их ядру и радиосети.

## Почему здесь нет исходников всех компонентов OAI

OAI запускается из Docker-образов. Версии и digest закреплены в
[lab.env](config/lab.env). Его база описана в
[schema.sql](infrastructure/vendor/oai-cn5g/schema.sql), а конфигурации создаёт
[oai_config.py](../scripts/oai_config.py) в приватной папке `local/oai/`.
Схема БД и лицензия в `vendor/oai-cn5g/` — не полный исходный код ядра.

Папка `vendor/docker_open5gs/` названа по upstream-проекту: оттуда используются
конфигурации **IMS** (Kamailio, PyHSS, RTPengine). Это не означает, что активное
ядро — Open5GS. Его прежний Compose-файл сохранён отдельно для отката.

Команды запуска выполняются **из корня репозитория**, через
[scripts](../scripts/README.md). Подробная [карта проекта](../docs/project-layout.md)
и [статус проверок](../docs/status.md) находятся в `docs/`. Секреты, записи,
кэш моделей и результаты запусков остаются в игнорируемой папке `local/`.
