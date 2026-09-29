# Общие настройки

[Назад к карте app](../README.md).

| Файл | Что менять |
| --- | --- |
| [lab.env](lab.env) | Адреса и сети, IMS-домен, номера услуг, версии образов OAI, AI-модели, лимиты и таймауты |
| [ims.env.example](ims.env.example) | Шаблон секретных параметров; реальные значения сюда не записываются |

При инициализации рабочие ключи создаются в `local/secrets/ims.env` и не
попадают в Git. Генератор OAI читает настройки и формирует `local/oai/*.yaml`.
Эти файлы тоже приватные; вручную дублировать их в `app/` не нужно.

Запускайте Compose из корня через `scripts/compose.ps1` или `scripts/compose.sh`:
они подключают публичные параметры и локальные секреты. Полный запуск —
`scripts/start.ps1` или `scripts/start.sh`.

Описание параметров: [configuration.md](../../docs/configuration.md).
Для внешнего ядра: [partner-integration.md](../../docs/partner-integration.md).
