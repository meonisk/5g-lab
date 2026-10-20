# Развёртывание локального OAI + IMS + AI

Все команды выполняются из корня репозитория. Этот сценарий включает собственные
OAI CN5G, UERANSIM gNB, две UE, IMS и AI. Для существующего ядра другого проекта
используйте [партнёрский вариант](partner-integration.md), без второго OAI.
Если термины незнакомы, сначала прочитайте [что делает стенд](first-use.md).

## 1. Подготовить машину и исходники

### Установить инструменты

На Windows установите [Python](https://www.python.org/downloads/), Git for Windows
с Git Bash и [Docker Desktop с WSL2](https://docs.docker.com/desktop/setup/install/windows-install/).
После установки откройте новый PowerShell и запустите Docker Desktop; дождитесь
готовности движка. Доступ к GitLab нужен для клонирования, но не для локальных звонков.

На Linux установите Git, Python с модулем venv и Docker Engine с Compose plugin.
Для Ubuntu используйте [официальную инструкцию Docker](https://docs.docker.com/engine/install/ubuntu/).
Команда `docker info` должна работать из того же терминала, где запускается
Python launcher. Если Docker доступен только через `sudo`, сначала настройте
доступ по инструкции Docker; не запускайте весь проект через `sudo python`.

Нужны Git, Python 3.12+, Docker Engine 28+ и Compose 2.33.1+ с Linux-контейнерами.
Конфигурация использует `include`, `!override` и `gw_priority`. На Windows нужны
Docker Desktop/WSL2 и Git for Windows с Bash; на Linux — Bash и ядро с SCTP.
Текущий launcher не поддерживает macOS. Проверенный CPU-хост — Linux x86-64
в Docker Desktop/WSL2 на i5-12400F; перенос на ARM не проверен.

```bash
git clone --branch master https://github.com/meonisk/5g-lab.git
cd 5g-lab
docker info --format '{{.OSType}}'
docker compose version
```

Ожидается `linux`. На ВМ установите Docker внутри Linux. Для локального
UERANSIM не нужны физическая базовая станция, SDR или GPU. Радиотракт настоящего
телефона — [отдельный сценарий](physical-5g-stand.md).

**Неизвестное железо:** сначала выясните архитектуру CPU, число доступных ядер,
RAM, свободный диск и лимиты ВМ/WSL2. Общий минимум RAM для OAI + IMS + AI пока
не измерен. Квоты контейнеров и размер файлов моделей не равны потреблению всей ВМ.
Измерения компонентов: [CPU-профили](cpu-ai-profiles.md). Первая сборка требует
интернет для образов, пакетов и моделей; подготовка OPUS может выполняться
на другой машине. После прогрева разговор обрабатывается локально.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/quality/check.py
```

Если PowerShell блокирует `Activate.ps1`, не меняйте системную политику ради
проекта: вызывайте интерпретатор напрямую, например
`.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` и
`.\.venv\Scripts\python.exe scripts/quality/check.py`. Так же заменяйте `python`
в последующих командах. После успешной offline-проверки ожидается
`TEAM OFFLINE CHECKS: PASS`.

Linux Bash:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/quality/check.py
```

## 2. Настроить сеть и секреты

Проверьте [lab.env](../app/config/lab.env) по [полному справочнику](lab-env-reference.md).
Подсети Docker, IMS UE и internet UE не должны пересекаться с LAN/VPN машины.
При смене LAN меняйте все статические адреса сервисов и динамический диапазон
согласованно. `IMS_ROUTE_GATEWAY` и `IMS_PARENT_INTERFACE` для локального bridge
остаются пустыми. Не используйте реальные SIM-ключи для первого эмулированного стенда.

```bash
python scripts/initialize_local.py
```

Создаются недостающие лабораторные ключи в `local/secrets/ims.env` и конфигурации
OAI в `local/oai/`; существующие ключи сохраняются. Проверка Compose:

```powershell
./scripts/compose.ps1 config --quiet
```

На Linux: `./scripts/compose.sh config --quiet`. Не публикуйте полный вывод
`compose config`: он может включать секреты. Модель конфигурации и изменение
существующей базы описаны в [configuration.md](configuration.md).
Успешный `config --quiet` обычно ничего не печатает. При ошибке дальше не переходите.
Для первого изолированного локального запуска стандартные параметры подходят,
если их подсети не пересекаются с вашими LAN/VPN; менять все 246 ключей не требуется.

## 3. Выбрать один способ запуска

Для первого знакомства можно сначала проверить только сеть и телефонию:

```bash
python scripts/start_lab.py --base-only
```

Ожидаемый итог — `LOCAL 5G IMS BASE: READY`. Это ещё не запуск перевода:
после успешной базы выберите один из двух вариантов ниже. Если база не поднялась,
сначала разберите её ошибку по [диагностике](running.md#диагностика-и-перенос).

### А. Исходный режим с Qwen

Windows: `./scripts/start.ps1`. Linux: `./scripts/start.sh`.
Он собирает образы, загружает Qwen (GGUF около 2,5 ГБ) и Whisper, подготавливает
синтетические WAV, настраивает абонентов, запускает сеть и последовательные
проверки звонков. По умолчанию используется CPU. Вызов с `-SkipVerify` на
Windows или `--skip-verify` в Bash пропускает live-проверки и даёт `UNVERIFIED`.

### Б. Облегчённый режим без Qwen

Для начала сравнения выберите `compact`. На новой машине сначала подготовьте
два OPUS-MT по [инструкции подготовки моделей](cpu-ai-profiles.md#подготовка-и-переключение).
Конвертер использует отдельное окружение Python 3.11; оно не заменяет окружение
оператора Python 3.12+. Переносите оба каталога `ru-en`, `en-ru` с manifests
в `local/models/opus-mt/` целевой машины.

Если модели ещё не подготовлены, команды для новой машины приведены ниже.
Установите `uv` в активное окружение оператора: `python -m pip install uv`;
другие способы — [в документации uv](https://docs.astral.sh/uv/getting-started/installation/).

Windows PowerShell:

```powershell
uv venv --python 3.11 local/benchmarks/cpu-ai/.venv
uv pip install --python local/benchmarks/cpu-ai/.venv/Scripts/python.exe ctranslate2==4.8.2 transformers==4.57.6 sentencepiece==0.2.2 torch==2.10.0 --torch-backend cpu
local/benchmarks/cpu-ai/.venv/Scripts/python.exe scripts/prepare_translation_models.py
```

Linux Bash:

```bash
uv venv --python 3.11 local/benchmarks/cpu-ai/.venv
uv pip install --python local/benchmarks/cpu-ai/.venv/bin/python ctranslate2==4.8.2 transformers==4.57.6 sentencepiece==0.2.2 torch==2.10.0 --torch-backend cpu
local/benchmarks/cpu-ai/.venv/bin/python scripts/prepare_translation_models.py
```

Ожидаются `OPUS MODEL READY: ru-en` и `OPUS MODEL READY: en-ru` при первой
подготовке. Не активируйте окружение конвертера вместо основного `.venv`.
Если модели перенесены с другой машины, этот шаг можно пропустить; оба каталога
должны содержать `manifest.json` и перечисленные в нём файлы.

Одинаково в PowerShell и Bash, из активированного окружения оператора:

```bash
python scripts/start_lab.py --base-only
python scripts/compose_ai.py --mode compact config --quiet
python scripts/compose_ai.py --mode compact build ai-worker voice-agent
python scripts/compose_ai.py --mode compact up -d --build
python scripts/compose_ai.py --mode compact ps
python scripts/compose_ai.py --mode compact logs --tail 100 ai-worker voice-agent
```

`--base-only` запускает и проверяет OAI/IMS без загрузки Qwen. Используйте именно
Python-команду: PowerShell-обёртка `start.ps1` не предоставляет этот параметр.
Этот флаг не останавливает AI, оставшийся от предыдущего запуска. При переходе
на лёгкий профиль `compose_ai.py ... up` отдельно остановит прежний Ollama.
Последующая команда `up` включает AS, Media Adapter и AI. Она не запускает
полный набор приёмочных звонков. Первый запуск Whisper требует загрузки весов;
дождитесь `healthy` у AI Worker и Voice Agent, затем проверяйте услуги.

Заменой `compact` выбираются `balanced` или `minimal`. Последний экспериментальный:
Whisper tiny ошибался в русской речи, eSpeak звучит менее естественно. Лёгкие
режимы сохраняют RU ↔ EN и raw-транскрипцию, но не LLM-очистку текста/ассистента.
Они допускают два голосовых вызова — одну двустороннюю пару.

Профиль указывается **в каждой** команде `compose_ai.py`. Обычный полный `start`
снова применяет конфигурацию Qwen. При переключении прерываются активные звонки;
используйте свободный стенд. Сеть, тома и имена общие: режимы не запускаются рядом.

## 4. Проверить результат

| Этап | Критерий |
| --- | --- |
| Исходники | `TEAM OFFLINE CHECKS: PASS`; не проверяет сеть |
| База | `LOCAL 5G IMS BASE: READY`: UE/PDU, DNS, маршруты, IMS-регистрация |
| Обычный звонок | SIP-диалог и звук в обе стороны, в том числе без AI |
| AI | RU → EN и EN → RU на двух языковых номерах, звук у слушателя |
| Транскрипция | Уведомление о записи, WAV и текст в `local/private/recordings/` |
| Нагрузка | Нет OOM/restart, измерены RAM/CPU и очереди во время разговора |

Номера по умолчанию: 1001/1002 — тестовые абоненты, 1003 — RU → EN,
1004 — запись/транскрипция, 1005 — русский и 1006 — английский участник
двустороннего перевода. Последняя услуга требует двух звонков к двум входам.
Проверки и их побочные действия: [running.md](running.md).
Практические команды первого вызова и чтение результатов: [first-use.md](first-use.md).

Старые проверки нормализованной транскрипции требуют LLM и не являются приёмкой
raw-режима. Успех CPU-компонентов не переносится на весь SIP-звонок. Задержку
1–3 секунды нужно измерять от начала речи до слышимого звука второго участника.

## 5. Обслуживание, повторный запуск и перенос

Для `compact`:

```bash
python scripts/compose_ai.py --mode compact logs --tail 100 sip-as media-adapter
docker stats --no-stream
python scripts/compose_ai.py --mode compact down
```

`down` сохраняет тома. Не добавляйте `-v`: там базы и кэши моделей. При повторном
запуске повторите базовый launcher и `up` нужного профиля. Для Qwen используйте
обычные Compose-обёртки. Диагностика и резервное копирование — в
[руководстве оператора](running.md#диагностика-и-перенос).

На одной Linux ВМ локальный состав разворачивается теми же командами. Если OAI
уже поднят другим проектом на этой ВМ, используйте [внешний контракт](integration-contract.md)
и `compose.partner.yml`; не запускайте второе ядро поверх него.
