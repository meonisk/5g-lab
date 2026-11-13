# 1. Установка и запуск

Все команды выполняются из корня репозитория, от обычного пользователя в группе
`docker`.

## Что нужно

- Linux x86-64, Docker Engine 28+ с Compose 2.33+, Python 3.11+, `git`, `curl`.
- Ядро OAI CN5G уже запущено в Docker на этом же компьютере.
- Интернет при первом запуске: образы Docker и модели речи (несколько гигабайт).

## Шаг 1. Настроить ядро OAI

Скрипт меняет конфигурацию ядра так, чтобы телефоны попадали в наш IMS:

```bash
scripts/core-setup.sh check    # показать текущее состояние, ничего не меняя
scripts/core-setup.sh apply    # применить изменения
scripts/core-setup.sh revert   # вернуть исходные файлы ядра
```

| Что меняется | Зачем |
|---|---|
| UPF: `enable_snat: no` | UPF не подменяет адрес телефона. Адрес записан внутри SIP-сообщений; если его подменить, ответы уйдут не туда |
| UPF: правило `iptables ... MASQUERADE` для интернета | телефон по-прежнему выходит в интернет через NAT, а к IMS идёт со своим настоящим адресом |
| SMF: `ims.pcscf_ipv4` = `PCSCF_IP` | телефон при подключении получает адрес нашего входного SIP-сервера |
| SMF: `ue_dns.primary_ipv4` = `DNS_IP` | телефон получает наш DNS, который знает имена IMS |
| демонстрационный IMS из комплекта OAI выключен | чтобы телефоны не уходили в него |

Каталог ядра — `OAI_CORE_DIR` (по умолчанию `~/oai-cn5g`). Перед первой правкой
сохраняются копии `*.bak-ims`. При применении перезапускаются SMF и UPF, поэтому
мобильные сессии всех телефонов обрываются на несколько секунд.

В базе абонентов ядра (UDR) у каждой SIM должна быть разрешена сеть данных (DNN)
`ims`.

## Шаг 2. Проверить настройки

Все параметры стенда хранятся в одном файле [app/config/lab.env](../app/config/lab.env):
адреса контейнеров, номера, ключи SIM, модели, лимиты процессора и памяти. Сверьте с
ядром:

- `CORE_NETWORK_NAME` и `LAB_NETWORK_CIDR` — имя и подсеть Docker-сети ядра
  (`docker network ls`, `docker network inspect <имя>`);
- `UPF_IP`, `IMS_UE_CIDR` (адреса телефонов в сети `ims`), `INTERNET_UE_CIDR`;
- `UE1_*`, `UE2_*` — IMSI, номер и ключи K/OPc настоящих SIM.

```bash
python3 scripts/start.py --check
```

Ожидаемый результат: `CONFIG: VALID`. Скрипт сверяет файл с реальной сетью ядра:
подсеть совпадает, адреса стенда свободны.

## Шаг 3. Запустить

```bash
scripts/setup.sh
```

Скрипт один раз готовит модели перевода OPUS-MT в `local/models/` и запускает все
контейнеры через `scripts/start.py`. Повторный запуск ничего не скачивает заново и не
перезапускает работающие контейнеры без нужды. Ожидаемый результат:
`STARTED: IMS + AI (compact)`.

Режим AI задаёт `AI_MODE` в `lab.env`, разово — параметр `--mode`:

| Режим | Распознавание | Перевод | Для чего |
|---|---|---|---|
| `compact` (по умолчанию) | Whisper base | OPUS-MT | обычный процессор, без видеокарты |
| `minimal` | Whisper tiny | OPUS-MT | самый быстрый, хуже качество |
| `balanced` | Whisper small | OPUS-MT | лучше качество, медленнее |
| `baseline` | Whisper small | языковая модель Qwen | эталон качества, нужен мощный компьютер |

### Настройка AI

Параметры — в `lab.env`, применяются повторным `python3 scripts/start.py`:

| Что | Переменные |
|---|---|
| распознавание | `AI_MODEL_SIZE`, `AI_MODEL_REVISION`, `AI_STT_CPU_THREADS`, `AI_LANGUAGE` |
| конец фразы | `AI_UTTERANCE_SILENCE_MS` (пауза, по умолчанию 700 мс), `AI_VAD_RMS` |
| одновременная обработка | `AI_PROCESSING_WORKERS`, `AI_QUEUE_MAX` |
| языковая модель | `LLM_MODEL`, `LLM_GGUF_URL`, `LLM_GGUF_SHA256` |
| синтез речи | `TTS_BACKEND`, `TTS_VOICE`, `PIPER_*` (голос меняется только пересборкой образа `voice-agent`) |
| запись | `RECORDING_ENABLED`, `RECORDING_RETENTION_DAYS` |
| ресурсы | `*_CPU_LIMIT`, `*_MEMORY_LIMIT` |

Значения режимов (`compact` и другие) берутся из
[ai-profiles.json](../app/config/ai-profiles.json) и заменяют значения `lab.env`.
Число потоков распознавания больше лимита процессора контейнера не ускоряет, а
замедляет.

Видеокарта NVIDIA (нужен NVIDIA Container Toolkit), только для режима `baseline`:
`AI_ENABLE_CUDA=1`, `AI_CONTAINER_RUNTIME=nvidia`, `AI_GPU_DEVICES=all`,
`AI_DEVICE=cuda`, `AI_COMPUTE_TYPE=int8_float16`, `LLM_CONTAINER_RUNTIME=nvidia`,
`LLM_GPU_DEVICES=all`, `AI_WORKER_MEMORY_LIMIT=4g`.

Важно: запускайте стенд только через `scripts/start.py` (или `setup.sh`). Если поднять
AI-контейнер напрямую через `docker compose up`, он не запустится и напишет в журнал
`AI startup_refused`.

## Шаг 4. Проверить

```bash
scripts/verify-all.sh
```

Скрипт по очереди проверяет запуск, абонентов, IMS, все услуги, отказ сервера услуг
и, если на компьютере есть эмулятор радио OAI, звонки через 5G. В конце печатает
таблицу PASS/FAIL/SKIP по шагам, полный журнал — в `local/verify-all/<время>.log`.
Проверки звонят через общий стенд, поэтому не запускайте их во время звонков с
настоящих телефонов.

## Шаг 5. Позвонить с телефона

Нужен телефон с 5G SA и VoNR и программируемая SIM, ключи которой записаны в
`lab.env` (`UE1_*` или `UE2_*`). После включения 5G телефон регистрируется в IMS сам.
Номера услуг описаны в [«Как устроено»](2-architecture.md#номера-и-услуги).

Записи разговоров лежат в `local/private/recordings/`. Каталоги принадлежат
пользователю контейнера, читать их — через `sudo` или
`docker exec lab-ai-worker ls /recordings`.

## Обновление, остановка, сервер

```bash
git pull && python3 scripts/start.py                       # обновить и перезапустить
docker compose --env-file app/config/lab.env --profile test down   # остановить всё
```

Остановка не трогает сеть и контейнеры ядра. Данные (база абонентов, модели)
остаются в томах Docker. `down -v` удаляет и их.

Изменения `lab.env` применяет `scripts/start.py`: он пересоздаёт контейнеры, у которых
поменялись параметры. `docker restart` старые параметры не обновляет.

На сервере стенда нужны только код, конфигурация, тесты и скрипты. Документация
остаётся в git. Один раз после клонирования:

```bash
git sparse-checkout set --no-cone --stdin < scripts/server-sparse-checkout.txt
```

## Частые ошибки

| Симптом | Причина и что делать |
|---|---|
| `start.py --check`: сеть не найдена или подсеть не совпадает | ядро не запущено или `CORE_NETWORK_NAME`/`LAB_NETWORK_CIDR` не совпадают с `docker network inspect` |
| «адрес уже занят контейнером» | адрес из `lab.env` занят контейнером ядра — выберите свободный |
| модели не скачиваются: `Network is unreachable` | на компьютере нет маршрута IPv6. Добавьте в `/etc/gai.conf` строку `precedence ::ffff:0:0/96  100` |
| телефон бесконечно повторяет регистрацию | ответы не доходят до телефона: проверьте `docker exec lab-pcscf ip route get <адрес телефона>` — должен быть `via <UPF_IP>` |
| регистрация: много раз `401`, потом отказ | ключи K/OPc в `lab.env` не совпадают с SIM. Не сбрасывайте счётчик SQN и не отключайте проверку ключей |
| в журнале S-CSCF адрес UPF вместо адреса телефона | на UPF остался NAT: `scripts/core-setup.sh check` |
| ключи в `lab.env` изменились, запуск остановился | заменить ключи явно: `python3 scripts/provision.py --apply --replace-keys` |
| звонок есть, звука нет или он в одну сторону | обратный путь к телефону через UPF не работает или включён NAT; сравните адреса в `docker logs lab-rtpengine` |
| на номере услуги нет приветствия | `docker logs lab-sip-as`: нет строки `AS terminated INVITE` — S-CSCF не отправил звонок серверу услуг |
| приветствие есть, перевода нет | по порядку: `docker logs lab-media-adapter` (пришёл ли звук), `lab-ai-worker` (распознана ли фраза), `lab-voice-agent` (озвучен ли ответ) |
| контейнер перезапускается | не хватает памяти: `docker inspect --format '{{.State.OOMKilled}}' <контейнер>`, лимиты `*_MEMORY_LIMIT` в `lab.env` |
