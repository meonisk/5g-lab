# Команды и служебные скрипты

Запускайте команды из корня репозитория. Обычный рабочий цикл:

```powershell
./scripts/start.ps1       # Полный запуск, подготовка данных и live-проверки
./scripts/check.ps1       # Быстрые проверки кода, без перезапуска стенда
./scripts/compose.ps1 ps  # Состояние Docker-сервисов
```

## Команды разработчика

| Файл | Зачем нужен |
| --- | --- |
| `start.ps1` | Короткая совместимая точка входа в `start-lab.ps1` |
| `start-lab.ps1` | Полный сценарий запуска и последовательных live-проверок |
| `compose.ps1`, `compose.sh` | Compose с публичным ENV и локальными секретами |
| `check.ps1` | Запуск `quality/check.py` из правильного каталога |
| `research.ps1` | Подготовка, сбор и проверка исследовательских запусков |
| `generate-bilingual-dialogue.ps1` | Генерация синтетических WAV по JSON-сценарию |

## Вызываются другими командами или контейнерами

| Файл | Кто использует |
| --- | --- |
| `initialize-local.ps1` | `start-lab.ps1`: создать/проверить локальные ключи |
| `prepare-host.ps1` | `start-lab.ps1`: загрузить SCTP в Docker Desktop |
| `subscribers.js` | `start-lab.ps1`: заполнить абонентов Open5GS |
| `provision-ims-subscribers.sh` | `start-lab.ps1`: заполнить абонентов PyHSS |
| `load-lab-env.sh` | Shell-команды и live-тесты: чтение ENV, сетевые помощники |
| `sip-register.sh` | Тест IMS-регистрации: перезапуск клиента и проверка ответа |
| `sip-ue-run.sh` | Контейнеры SIP UE: транспорт через IMS PDU и запуск PJSUA |
| `dns-ims-run.sh` | Контейнер DNS: маршруты и шаблон зоны |
| `render-open5gs-config.sh` | SMF/UPF: подстановка ENV в конфигурации |
| `open5gs-config-run.sh` | SMF: рендеринг конфигурации перед entrypoint |
| `upf-ims-setup.sh` | UPF: конфигурация, TUN и маршруты IMS |
| `quality/check.py` | Единый offline-набор проверок |
| `quality/check_layout.py` | Лимит 300 логических строк и синтаксис Python |
| `check-no-hardcoded-topology.py` | Проверка отсутствия зашитой топологии |

Это не каталог временных экспериментов. Live-тесты находятся в
`app/tests/integration/`, unit-тесты — в `app/tests/unit/`, текстовые сценарии —
в `app/tests/fixtures/`. Старые исследовательские дизайны сохраняются для
понимания предыдущих запусков; отсутствие вызова в `start.ps1` не делает их мусором.

Перед удалением файла проверьте ссылки в Compose, Dockerfile, shell/PowerShell,
тестах и документации. Короткие публичные обёртки оставлены намеренно:
они сохраняют команды пользователей. Локальные WAV, записи, модели и секреты
не относятся к чистке исходников.
