# Сторонние компоненты и лицензии

Единая лицензия для собственного кода проекта пока не выбрана.
Сторонние файлы сохраняют исходные уведомления и условия; лицензия отдельного
компонента не распространяется автоматически на весь проект.

| Компонент | Где указаны версия и происхождение |
| --- | --- |
| OAI CN5G v2.2.1 и SQL-схема | [Происхождение](app/infrastructure/vendor/oai-cn5g/PROVENANCE.md), [лицензия](app/infrastructure/vendor/oai-cn5g/LICENSE) |
| Конфигурации и скрипты из docker_open5gs | [Происхождение](app/infrastructure/vendor/docker_open5gs/PROVENANCE.md), [лицензия](app/infrastructure/vendor/docker_open5gs/LICENSE) |
| Распознавание речи и модель | [Происхождение модели](app/services/ai-worker/MODEL_PROVENANCE.md), зависимости и Dockerfile сервиса |
| Qwen GGUF и альтернативные модели | URL и SHA-256 в `app/config/lab.env`; [руководство](docs/local-models.md) |
| Helsinki-NLP OPUS-MT RU→EN / EN→RU и SentencePiece | Закреплённые ревизии, заявленные CC-BY-4.0 / Apache-2.0 и конверсия: [CPU-профили](docs/cpu-ai-profiles.md); manifests создаются вместе с весами |
| Piper и русские/английские голоса | Закреплённые загрузки в сборке Voice Agent и общей конфигурации; [настройка](docs/configuration.md) |
| Образы инфраструктуры и Python-библиотеки | `app/config/lab.env`, Dockerfile и `requirements*.txt` |
| Дополнительные кодеки FFmpeg, OpenCORE AMR и VisualOn AMR-WB | Пакет Debian `libavcodec-extra59` и зависимости RTPengine; уведомления сохранены в `/usr/share/doc/` внутри образа |

Веса моделей и образы скачиваются при подготовке, а не хранятся в исходниках.
Их условия распространения учитываются отдельно. Перед передачей собранных
образов или весов нужно проверить исходные уведомления правообладателей.
Этот перечень фиксирует компоненты, но не является заключением о лицензировании.
