# Команды и служебные скрипты

Запускайте команды из корня репозитория. Обычный рабочий цикл:

```powershell
./scripts/start.ps1       # Полный запуск, подготовка данных и live-проверки
./scripts/start.sh        # Тот же полный запуск на Linux
./scripts/check.ps1       # Быстрые проверки кода, без перезапуска стенда
./scripts/compose.ps1 ps  # Состояние Docker-сервисов
```

## Команды разработчика

| Файл | Зачем нужен |
| --- | --- |
| `start.ps1`, `start.sh` | Windows/Linux точки входа в общий launcher |
| `start_lab.py` | Общий запуск, provisioning и последовательные live-проверки |
| `start-lab.ps1` | Обратная совместимость со старой командой Windows |
| `compose.ps1`, `compose.sh` | Compose с публичным ENV и локальными секретами |
| `check.ps1` | Запуск `quality/check.py` из правильного каталога |
| `research.ps1` | Подготовка, сбор и проверка исследовательских запусков |
| `generate-bilingual-dialogue.ps1`, `generate_dialogue.py` | Генерация приватных Piper WAV по JSON-сценарию |
| `run-interpreter-experiment.ps1` | Полный приватный эксперимент: входные и принятые WAV, логи, метаданные и задержки |

## Вызываются другими командами или контейнерами

| Файл | Кто использует |
| --- | --- |
| `initialize-local.ps1`, `initialize_local.py` | Создать/проверить локальные ключи без вывода значений |
| `prepare-host.ps1` | `start_lab.py`: загрузить SCTP в Docker Desktop |
| `app/tests/fixtures/render_dialogue.py` | Контейнерный рендер Piper WAV для Windows/Linux |
| `subscribers.js` | `start_lab.py`: заполнить абонентов Open5GS |
| `provision-ims-subscribers.sh` | `start_lab.py`: заполнить абонентов PyHSS |
| `load-lab-env.sh` | Shell-команды и live-тесты: чтение ENV, сетевые помощники |
| `sip-register.sh` | Тест IMS-регистрации: перезапуск клиента и проверка ответа |
| `sip-ue-run.sh` | Контейнеры SIP UE: транспорт через IMS PDU и запуск PJSUA |
| `dns-ims-run.sh` | Контейнер DNS: маршруты и шаблон зоны |
| `render-open5gs-config.sh` | SMF/UPF: подстановка ENV в конфигурации |
| `open5gs-config-run.sh` | SMF: рендеринг конфигурации перед entrypoint |
| `upf-ims-setup.sh` | UPF: конфигурация, TUN и маршруты IMS |
| `quality/check.py` | Единый offline-набор проверок |
| `quality/check_git.py` | Индекс Git, права shell-файлов, приватные файлы; `--history` проверяет все refs |
| `quality/check_docs.py` | Локальные цели Markdown-ссылок |
| `quality/check_layout.py` | Лимит 300 логических строк и синтаксис Python |
| `check-no-hardcoded-topology.py` | Проверка отсутствия зашитой топологии |
| `build-experiment-manifest.py` | Проверка WAV и формирование манифеста эксперимента |
| `transcribe_experiment.py` | Повторное локальное распознавание четырёх WAV: `python scripts/transcribe_experiment.py local/experiments/<run>` |
| `transcript_timeline.py` | Формирование транскрипции, общей шкалы событий и явно обозначенных восстановленных времён |

Это не каталог временных экспериментов. Live-тесты находятся в
`app/tests/integration/`, unit-тесты — в `app/tests/unit/`, текстовые сценарии —
в `app/tests/fixtures/`. Старые исследовательские дизайны сохраняются для
понимания предыдущих запусков; отсутствие вызова в `start.ps1` не делает их мусором.

Перед удалением файла проверьте ссылки в Compose, Dockerfile, shell/PowerShell,
тестах и документации. Короткие публичные обёртки оставлены намеренно:
они сохраняют команды пользователей. Локальные WAV, записи, модели и секреты
не относятся к чистке исходников.
