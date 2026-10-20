# Туториал 3. Установка и настройка SIP-серверов и клиентов

SIP-часть стенда: серверы Kamailio P/I/S-CSCF, PyHSS, RTPengine, DNS; клиенты PJSUA
(Digest) и SIPp (IMS AKA); внешний клиент и настоящий телефон.
Связь IMS с ядром 5G — [туториал 1](guide-1-ims-core.md), AI-услуги — [туториал 2](guide-2-ims-ai.md).

Команды — из корня репозитория в активированном `.venv`. Требования к машине —
[туториал 1](guide-1-ims-core.md#а-локальный-стенд-наше-ядро-oai--ims). На Windows
`bash ...` запускайте в Git Bash, вместо `./scripts/compose.sh` — `./scripts/compose.ps1`.

# Часть 1. Быстрый запуск

## А. Поднять SIP-серверы

**Локальный стенд** (ядро OAI + IMS + клиенты PJSUA):

```bash
python scripts/initialize_local.py
python scripts/start_lab.py --base-only
```

Результат: `LOCAL 5G IMS BASE: READY`.

**Только IMS у ядра партнёров** (Linux; `lab.env` заполнен по
[туториалу 1, вариант Б](guide-1-ims-core.md#б-ядро-уже-работает-у-партнёров-ставим-только-ims--ai)).
Ключи IMS готовит сам `--check`, отдельный `initialize_local.py` не нужен.

```bash
python3 scripts/start_partner.py --check
python3 scripts/start_partner.py --ims-only
```

Результат: `PARTNER CONFIG: VALID`, затем `PARTNER SERVICES: STARTED` (регистрация
внешних UE и вызов при этом не проверены).

## Б. Убедиться, что серверы работают

```bash
./scripts/compose.sh ps
./scripts/compose.sh logs --tail 50 pcscf icscf scscf pyhss rtpengine dns
```

У партнёров:

```bash
docker compose --env-file app/config/lab.env --env-file local/secrets/ims.env -f compose.partner.yml ps
```

Результат: `lab-pcscf`, `lab-icscf`, `lab-scscf`, `lab-pyhss`, `lab-mysql`,
`lab-rtpengine`, `lab-dns` — `Up`.

## В. Регистрация и звонок между клиентами PJSUA (локальный стенд)

**1. Регистрация**

```bash
bash app/tests/integration/verify-ims-registration.sh
```

Результат: `PHASE 4B (DOCKER): PASS` — 1001 и 1002 зарегистрированы.

**2. Звонок 1001 → 1002 вручную**

```bash
docker exec lab-sipue1 sh -lc 'printf "m\nsip:1002@%s\n" "$IMS_DOMAIN" > /tmp/pjsua-control'
sleep 10
docker logs --tail 40 lab-sipue1
docker logs --tail 40 lab-sipue2
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control'
```

Результат: у `lab-sipue1` — `200 OK` на INVITE, у `lab-sipue2` — входящий вызов с автоответом.

**3. Автоматическая проверка вызова**

```bash
bash app/tests/integration/verify-ims-call.sh
```

Результат: `PHASE 4C/4D (DOCKER): PASS`.

**4. После перезапуска радиочасти** (`gnb ue1 ue2`)

```bash
./scripts/compose.sh up -d --force-recreate sipue1 sipue2
```

Результат: клиенты заново регистрируются с новых IMS-адресов (повторите шаг 1).

## Г. Проверки IMS AKA с SIPp

**1. Собрать SIPp**

```bash
docker build -f app/infrastructure/images/sipp-aka/Dockerfile -t lab-sipp-aka:3.7.7-opc .
docker run --rm lab-sipp-aka:3.7.7-opc -v
```

Результат: `SIPp v3.7.7-TLS-SCTP-PCAP-SHA256` (код выхода 1 для `-v` — норма).

**2. Остановить AS/AI, если запущены**

```bash
docker stop lab-sip-as lab-ai-worker lab-media-adapter lab-voice-agent
```

**3. Проверки** — строго по одной, на свободном стенде без активных RTP-сессий

```bash
python app/tests/integration/verify_plain_call.py
python app/tests/integration/verify_plain_call.py --caller 2
python app/tests/integration/verify_aka_registration.py
python app/tests/integration/verify_aka_registration.py --bad-response
python app/tests/integration/verify_aka_call.py
python app/tests/integration/verify_aka_call.py --caller 2
python app/tests/integration/verify_aka_lifecycle.py
python app/tests/integration/verify_aka_inactive_call.py --mode deregister
python app/tests/integration/verify_aka_inactive_call.py --mode expire
```

Результат: каждая печатает `...: PASS; evidence: <каталог>` (`Plain-call result`,
`AKA registration probe`, `Continuous AKA call`, `AKA lifecycle`, `AKA inactive call`);
в `result.json` каталога — `status` и `cleanup` равны `PASS`.

**4. Вернуть AS/AI**

```bash
./scripts/compose.sh up -d --no-deps --force-recreate sip-as ai-worker media-adapter voice-agent
```

## Д. Транскодирование кодеков телефона

```bash
python app/tests/integration/verify_phone_codecs.py
```

Результат: строки `PASS: <AMR|AMR-WB> octet-align=<0|1> <-> PCMU, ...`.

## Е. Пересобрать сервер после изменения конфигурации

```bash
./scripts/compose.sh build scscf rtpengine
./scripts/compose.sh up -d --force-recreate pcscf icscf scscf rtpengine
```

Результат: контейнеры пересозданы с новой конфигурацией; повторите шаги Б и В.

# Часть 2. Как устроено

## 1. Состав

### SIP-серверы

| Сервер | Реализация | Контейнер, адрес, порт | Роль |
| --- | --- | --- | --- |
| P-CSCF | Kamailio (образ `docker_kamailio`, закреплён по digest) | `lab-pcscf`, `172.22.0.106:5060` | Вход UE в IMS; привязка медиа к RTPengine; удаление непроверенных идентификаторов |
| I-CSCF | Kamailio (тот же образ) | `lab-icscf`, `172.22.0.104:5060` | Запрос к HSS при регистрации, выбор S-CSCF |
| S-CSCF | Kamailio с патчем регистратора (`lab-kamailio-scscf:987459-expiry-v1`) | `lab-scscf`, `172.22.0.105:6060` | Регистратор, аутентификация Digest/AKA, маршрутизация, вызов AS по iFC |
| HSS | PyHSS + MySQL | `lab-pyhss`, `172.22.0.103`; `lab-mysql`, `172.22.0.102` | Абоненты IMS, ключи AuC, iFC; Diameter Cx к I/S-CSCF |
| Медиа | RTPengine 26.0.1.23 + `libavcodec-extra59` | `lab-rtpengine`, `172.22.0.101`; NG 2223, RTP UDP 30000–30100 | Ретрансляция RTP, транскодирование AMR/AMR-WB ↔ PCMU |
| DNS | dnsmasq | `lab-dns`, `172.22.0.100:53` | Зона IMS-домена и SRV-записи SIP |
| SIP AS | Наш Python-сервис | `lab-sip-as`, `172.22.0.107:5070` | AI-услуги по номерам ([туториал 2](guide-2-ims-ai.md)) |

### SIP-клиенты

| Клиент | Где | Аутентификация | Назначение |
| --- | --- | --- | --- |
| PJSUA (pjproject 2.14.1, только аудио) | `lab-sipue1`, `lab-sipue2` | Digest (лабораторная регрессия) | Постоянные абоненты 1001 и 1002, ручные вызовы |
| SIPp 3.7.7 с патчами AKA/OPc | Образ `lab-sipp-aka:3.7.7-opc`, временные контейнеры | IMS AKA (AKAv1-MD5, Milenage) | Проверки AKA-регистрации и вызова |
| Настоящий телефон / ISIM | У партнёров | IMS AKA | Целевой сценарий, не проверен |

## 2. Установка серверов

Отдельно SIP-серверы не ставятся: их собирает и запускает launcher (часть 1, шаг А).
Фрагменты Compose самостоятельно не запускайте — сети, тома и пути задаёт главная
конфигурация ([docker-compose.yml](../../docker-compose.yml) или
[compose.partner.yml](../../compose.partner.yml)). `start_partner.py --ims-only`
поднимает `dns mysql pyhss icscf scscf rtpengine pcscf`, а `--check` только проверяет
конфигурацию и не запускает контейнеры.

Локально собираемые образы:

| Образ | Откуда | Пересборка |
| --- | --- | --- |
| S-CSCF | `app/infrastructure/images/kamailio-scscf/`: базовый Kamailio по digest + однострочный патч `lookup()` в `ims_registrar_scscf` (не маршрутизировать на истёкший Contact) | `./scripts/compose.sh build scscf` |
| RTPengine | `app/infrastructure/vendor/docker_open5gs/rtpengine/`, добавлено кодирование AMR/AMR-WB | `./scripts/compose.sh build rtpengine` |
| DNS | `app/infrastructure/images/dnsmasq/` | `./scripts/compose.sh build dns` |
| PJSUA | `app/infrastructure/images/pjsua/` (pjproject 2.14.1 из исходников) | `./scripts/compose.sh build sipue1` |
| SIPp AKA | `app/infrastructure/images/sipp-aka/` | часть 1, шаг Г.1 |

Dockerfile S-CSCF до применения патча проверяет коммит Kamailio `9874599e…` и SHA-256
исходного `lookup.c` и патча. Происхождение и лицензии —
[kamailio-scscf-provenance.md](../kamailio-scscf-provenance.md),
[THIRD_PARTY.md](../../THIRD_PARTY.md).

## 3. Настройка серверов

### 3.1. Параметры в `app/config/lab.env`

| Параметр | По умолчанию | Смысл |
| --- | --- | --- |
| `IMS_DOMAIN` | `ims.mnc001.mcc001.3gppnetwork.org` | Домашний домен и realm |
| `PCSCF_IP`, `PCSCF_SIP_PORT` | `172.22.0.106`, `5060` | P-CSCF |
| `ICSCF_IP`, `ICSCF_SIP_PORT` | `172.22.0.104`, `5060` | I-CSCF |
| `SCSCF_IP`, `SCSCF_SIP_PORT` | `172.22.0.105`, `6060` | S-CSCF |
| `PCSCF_UDP_MTU` | `65535` | Порог UDP для P-CSCF |
| `RTPENGINE_IP`, `RTPENGINE_NG_PORT` | `172.22.0.101`, `2223` | RTPengine и управляющий порт NG |
| `RTPENGINE_PORT_MIN`, `RTPENGINE_PORT_MAX` | `30000`, `30100` | Диапазон RTP |
| `SIP_AS_IP`, `SIP_AS_PORT` | `172.22.0.107`, `5070` | Прикладной сервер |
| `KAMAILIO_IMAGE`, `SCSCF_IMAGE`, `PYHSS_IMAGE`, `MYSQL_IMAGE` | закреплены по digest | Версии образов |

Изменения применяются пересозданием сервиса
(`./scripts/compose.sh up -d --force-recreate <сервис>`); `restart` новое окружение
не применяет. Смена адресов или сетей может потребовать полного перезапуска стенда.

### 3.2. Файлы конфигурации

| Сервер | Файлы |
| --- | --- |
| P-CSCF | `app/infrastructure/vendor/docker_open5gs/pcscf/`: `kamailio_pcscf.cfg`, `pcscf.cfg` (defines, в т.ч. `WITH_IPSEC`), `route/` (исходящие/входящие маршруты), `pcscf_init.sh` |
| I-CSCF | `app/infrastructure/vendor/docker_open5gs/icscf/` |
| S-CSCF | `app/infrastructure/vendor/docker_open5gs/scscf/`: `kamailio_scscf.cfg` (`route[REGISTER]`, `WITH_AUTH`), `scscf.cfg`, `scscf_init.sh` |
| PyHSS | `app/infrastructure/vendor/docker_open5gs/pyhss/`: `config.yaml`, `default_ifc.xml`, `default_sh_user_data.xml`; профиль без AS — `app/infrastructure/configs/pyhss/baseline_ifc.xml` |
| RTPengine | `app/infrastructure/vendor/docker_open5gs/rtpengine/` |
| DNS | `app/infrastructure/configs/dns/ims-dnsmasq.conf` — шаблон с подстановкой из `lab.env` |

Конфигурации CSCF взяты из docker_open5gs (отсюда имя папки); активное ядро — OAI.
Vendor-файлы правьте только с обоснованием и записью происхождения.

### 3.3. DNS-зона IMS

| Имя | Куда |
| --- | --- |
| `<IMS_DOMAIN>`, `icscf.<домен>` | I-CSCF (REGISTER по домену) |
| `pcscf.`, `scscf.`, `hss.`, `as.`, `media.`, `voice-agent.<домен>` | Адреса соответствующих сервисов |
| SRV `_sip._udp` / `_sip._tcp.<домен>` | I-CSCF:`ICSCF_SIP_PORT` |
| SRV `_sip._udp` / `_sip._tcp.scscf.<домен>` | S-CSCF:`SCSCF_SIP_PORT` |

### 3.4. iFC: когда S-CSCF вызывает AS

[default_ifc.xml](../../app/infrastructure/vendor/docker_open5gs/pyhss/default_ifc.xml)
применяется к каждому абоненту при provisioning: исходящий (`SessionCase 0`) `INVITE`,
приоритет 30, сервер `sip:as.<домен>:<SIP_AS_PORT>;transport=udp`, `DefaultHandling 0`
(при недоступности AS вызов продолжается). `verify_plain_call.py` временно убирает AS
из iFC и затем восстанавливает.

## 4. Абоненты в HSS

[provision-ims-subscribers.sh](../../scripts/provision-ims-subscribers.sh) (вызывают
`start_lab.py` и `start_partner.py`) работает через REST API PyHSS по отдельной
management-сети и создаёт: APN (если нет) → AuC (IMSI, IMS K, OPc, AMF) → subscriber →
IMS subscriber (MSISDN, домен, `ifc_path: default_ifc.xml`). Существующие записи
обновляются, ключи молча не перезаписываются, **SQN не сбрасывается**.

| Данные | Откуда |
| --- | --- |
| `UE1_IMSI`, `UE1_MSISDN`, `UE2_IMSI`, `UE2_MSISDN` | `app/config/lab.env` |
| `UE<n>_IMS_K`, `UE<n>_IMS_OPC`, `UE<n>_IMS_AMF` | `local/secrets/ims.env` (в документацию и Git не попадают) |

| Идентификатор | Формат | Пример UE1 |
| --- | --- | --- |
| IMPI (username) | `<IMSI>@<домен>` | `001010000000001@ims.mnc001.mcc001.3gppnetwork.org` |
| IMPU | `sip:<MSISDN>@<домен>`, `tel:<MSISDN>`, `sip:<IMSI>@<домен>` | `sip:1001@ims.mnc001.mcc001.3gppnetwork.org` |
| Realm | `<IMS_DOMAIN>` | `ims.mnc001.mcc001.3gppnetwork.org` |

**Ограничение: provisioning поддерживает только двух абонентов, UE1 и UE2.**
Третьего абонента скрипт не создаёт. Заменить абонента: измените `UE<n>_IMSI`/`UE<n>_MSISDN`
и ключи, затем повторите запуск (шаг А). Смена ключей в существующей базе — только
явной миграцией с backup.

**Digest-пароль PJSUA.** Закреплённый PyHSS использует AuC `ki` как Digest-пароль,
поэтому Compose передаёт клиенту `IMS_DIGEST_PASSWORD = UE<n>_IMS_K`. Общий
`IMS_DIGEST_PASSWORD` из `local/secrets/ims.env` — только запасное значение, если
`UE<n>_IMS_K` не задан. Это ограничение регрессионного Digest-клиента, не IMS AKA;
production Ki как Digest-пароль не применять.

## 5. SIP-клиент PJSUA

### 5.1. Запуск

`lab-sipue1`/`lab-sipue2` (образ `lab-pjsua`) делят сетевое пространство с
эмулированными UE (`network_mode: service:ue1`). [sip-ue-run.sh](../../scripts/sip-ue-run.sh):

1. ждёт TUN UERANSIM с адресом из `IMS_UE_CIDR`;
2. ставит маршруты `/32` к `PCSCF_IP` и `RTPENGINE_IP` через этот TUN — SIP и RTP идут
   через IMS PDU-сессию, а не через Docker bridge;
3. готовит WAV: `SIP_UE_PLAYBACK_FILE` или синтез eSpeak фразы `SIP_UE_TEST_UTTERANCE`;
4. создаёт FIFO `/tmp/pjsua-control` и запускает PJSUA;
5. каждые 2 с проверяет TUN, адрес и маршруты; при изменении завершается, Docker
   перезапускает клиент с новой регистрацией.

Команда PJSUA:

```bash
pjsua --null-audio --no-tcp --use-compact-form \
  --clock-rate=8000 --snd-clock-rate=8000 \
  --dis-codec='*' --add-codec="$SIP_UE_CODEC" \
  --play-file="$playback" --auto-conf \
  --auto-answer="$SIP_UE_AUTO_ANSWER" \
  --id "sip:${IMSI}@${IMS_DOMAIN}" \
  --registrar "sip:${IMS_DOMAIN}" \
  --proxy "sip:${PCSCF_IP}:${PCSCF_SIP_PORT};transport=udp;lr" \
  --realm "$IMS_DOMAIN" \
  --username "${IMSI}@${IMS_DOMAIN}" \
  --password "$IMS_DIGEST_PASSWORD" \
  --reg-timeout=3600 --ip-addr="$ue_ip"
```

Звуковая карта не используется (`--null-audio`): в динамиках компьютера звука нет,
принятый звук можно записать в WAV (`SIP_UE_RECORD_FILE`).

### 5.2. Параметры клиента

| Параметр | По умолчанию | Смысл |
| --- | --- | --- |
| `SIP_UE_CODEC` | `PCMU/8000` | Единственный разрешённый кодек |
| `SIP_UE_AUTO_ANSWER` | `200` | Автоответ на входящий вызов |
| `SIP_UE_AUTO_CONFERENCE` | `1` | Подключать проигрыватель к вызову |
| `SIP_UE_TEST_UTTERANCE` | русская фраза | Текст для синтеза тестового WAV |
| `SIP_UE_PLAYBACK_FILE` | пусто | Готовый WAV вместо синтеза |
| `SIP_UE_RECORD_FILE` | пусто (нет в `lab.env`, задаётся окружением контейнера) | Запись принятого звука |
| `SIP_CALL_DURATION_SECONDS` | `20` | Длительность тестового вызова |

### 5.3. Управление через FIFO

Команды — `docker exec lab-sipue1 sh -lc 'printf "<команда>" > /tmp/pjsua-control'`
(Git Bash или Linux Bash); ответ — в `docker logs --tail 80 lab-sipue1`.

| Действие | `<команда>` |
| --- | --- |
| Позвонить | `m\nsip:1002@%s\n` с аргументом `"$IMS_DOMAIN"` (часть 1, шаг В.2) |
| Список аудиопортов | `cl\n` |
| Подключить порт 1 к порту 4 | `cc\n1\n4\n` |
| Отключить | `cd\n1\n4\n` |
| Завершить все вызовы | `ha\n` |

Звонок на AI-номер из PowerShell, номер и домен — из `lab.env`:

```powershell
$number = (Select-String '^VOICE_TRANSLATOR_MSISDN=' app/config/lab.env).Line.Split('=', 2)[1]
$domain = (Select-String '^IMS_DOMAIN=' app/config/lab.env).Line.Split('=', 2)[1]
docker exec lab-sipue1 sh -lc "printf 'm\nsip:${number}@${domain}\n' > /tmp/pjsua-control"
```

После перезапуска радиочасти клиенты пересоздаются (часть 1, шаг В.4), чтобы сокеты
привязались к новым IMS-адресам.

## 6. SIP-клиент SIPp для IMS AKA

PJSUA проверяет только Digest; IMS AKA — SIPp, собранный из исходников с двумя
лабораторными патчами: бинарно-безопасная передача `aka_K`, `aka_OP`, `aka_AMF` и новый
параметр `aka_OPc` (прямой ввод OPc для Milenage). Сборка прогоняет синтетический тест
кодирования и тест 3GPP TS 35.208 Test Set 1. Происхождение и контрольные суммы —
[sipp-aka-provenance.md](../sipp-aka-provenance.md).

Схема AKA-вызова:

- один процесс SIPp **на каждое UE**, один UDP-сокет (`-t u1 -users 1 -m 2`);
- первый «вызов» сценария — REGISTER с AKA, второй — INVITE с новым Call-ID и маршрутом
  из Service-Route;
- вызываемая сторона принимает INVITE тем же сокетом через `-oocsf`;
- RTP передаёт отдельный помощник в сети UE (`SIP_AKA_MEDIA_IMAGE`);
- ключи попадают только в приватные сгенерированные XML — не в командную строку и не в трассы.

Подробности — [aka-continuous-client-spike.md](../aka-continuous-client-spike.md).

| Параметр `lab.env` | По умолчанию |
| --- | --- |
| `SIP_AKA_IMAGE` | `lab-sipp-aka:3.7.7-opc` |
| `SIP_AKA_PORT` | `5062` |
| `SIP_AKA_MEDIA_PORT` | `4000` |
| `SIP_AKA_CALL_SECONDS` | `20` |
| `SIP_AKA_TIMEOUT_SECONDS` | `35` |
| `SIP_AKA_EXPIRY_SECONDS` | `30` |
| `SIP_AKA_*_TIMEOUT_SECONDS` и прочие `SIP_AKA_*` | таймауты восстановления и сценариев жизненного цикла |

## 7. Внешний SIP-клиент и настоящий телефон

Настройка ядра партнёров, чтобы их UE дошли до нашего P-CSCF, —
[туториал 1, раздел 6](guide-1-ims-core.md#6-вариант-б-подключение-ims--ai--sip-к-уже-работающему-ядру).

Клиент должен быть **в IMS-пуле UE** (IMS PDU-сессия через ядро) либо иметь маршрут к
P-CSCF и RTPengine без NAT. Софтфон из LAN в обход ядра не проверялся.

| Поле | Значение |
| --- | --- |
| Outbound proxy | `sip:<PCSCF_IP>:<PCSCF_SIP_PORT>;transport=udp;lr` |
| Registrar / домен | `sip:<IMS_DOMAIN>` |
| SIP URI | `sip:<IMSI>@<IMS_DOMAIN>` (или IMPU с MSISDN) |
| Имя пользователя | `<IMSI>@<IMS_DOMAIN>` |
| Realm | `<IMS_DOMAIN>` |
| Аутентификация | IMS AKA с K/OPc/AMF абонента; Digest — только лабораторная регрессия |
| Кодек | PCMU/8000; AMR/AMR-WB транскодирует RTPengine; EVS не поддержан |
| Транспорт | UDP/TCP, без TLS/IPsec (Gm security не принята) |

Ограничения:

- SIP AS отклоняет вызовы с обязательными `100rel`/`precondition`; для таких телефонов
  нужна реализация PRACK/UPDATE и согласования QoS.
- Телефон: Android с 5G SA и VoNR в диапазоне партнёров, IMS и AMR/AMR-WB;
  программируемая USIM/ISIM с согласованными IMS-идентификаторами. Операторскую SIM
  в HSS скопировать нельзя. Подробнее — [native-phone.md](../native-phone.md).
- `python scripts/phone_readiness.py` только читает серверные возможности (JSON);
  `NOT_READY` ожидаем до приёмки телефона.

## 8. Проверки

| Проверка | Что подтверждает |
| --- | --- |
| `verify-ims-registration.sh` | Digest-регистрация 1001 и 1002 |
| `verify-ims-call.sh` | UE1 получает `200 OK`, UE2 — INVITE через IMS, S-CSCF вызывает AS по iFC, RTPengine видит оба IMS-адреса |
| `verify_plain_call.py` | Вызов без AS в iFC, звук в обе стороны; `--caller 1\|2`; `--mute-ue 1\|2` — обнаружение пропавшего источника |
| `verify_aka_registration.py` | AKA-регистрация двух UE и связанный Cx; `--bad-response` — отказ UE1 при успехе UE2 |
| `verify_aka_call.py` | AKA-регистрация и вызов одним процессом, PCMU в обе стороны, WAV у каждого UE; `--caller 1\|2` |
| `verify_aka_lifecycle.py` | Регистрация, обновление, снятие (`Expires: 0`), свежий challenge на каждом шаге |
| `verify_aka_inactive_call.py` | Вызов снятого (`--mode deregister`) или истёкшего (`--mode expire`) абонента: `404`, ACK, без оставшейся RTP-сессии; `--callee 1\|2` |
| `verify_phone_codecs.py` | Синтетический обмен AMR/AMR-WB ↔ PCMU через RTPengine, `octet-align` 0 и 1; не полный SIP-вызов и не разборчивость речи |

Правила для изолированных проверок (`verify_plain_call.py`, `verify_aka_*`):

- только на свободном базовом стенде, **с остановленными AS/AI и без активных
  RTP-сессий**, строго по одной;
- проверка блокирует стенд, временно останавливает PJSUA и затем восстанавливает
  клиентов — смотрите и `status`, и `cleanup`;
- приватные результаты (XML с ключами, SIP/PCAP, WAV, `result.json`) остаются в
  `local/private/plain-call-*`, `aka-register-*`, `aka-call-*`, `aka-lifecycle-*`,
  `aka-inactive-*` и не публикуются.

## 9. Диагностика

| Симптом | Что проверить |
| --- | --- |
| REGISTER без ответа | Маршруты `/32` в клиенте (`docker logs lab-sipue1`, строка `IMS transport:`), доступность P-CSCF и DNS с IMS-адреса, порт 5060, firewall |
| `401` повторяется, затем отказ | IMPI/IMPU и realm, способ аутентификации, совпадение ключей клиента и AuC, журналы I/S-CSCF и PyHSS (Cx) |
| Регистрация AKA вытесняется | Digest-клиенты не остановлены: лимит одного Contact с overwrite вытесняет binding |
| `ERROR: no TUN reaches IMS_UE_GATEWAY` | У UE нет IMS PDU-сессии — [туториал 1](guide-1-ims-core.md#8-диагностика) |
| Вызов есть, звука нет или в одну сторону | SDP (адреса и порты), маршруты к RTPengine в обе стороны, диапазон RTP, кодек, `docker logs lab-rtpengine` |
| Телефон получает отказ при `100rel`/`precondition` | Ограничение SIP AS (раздел 7) |
| После перезапуска первый вызов не проходит | Пересоздать `sipue1 sipue2`, повторить регистрацию; прежний `FAIL` сохраняется |
| Изменения конфигурации CSCF не применились | Пересоздать контейнер; для S-CSCF/RTPengine — пересобрать образ (часть 1, шаг Е) |

**Не сбрасывайте SQN и не отключайте аутентификацию для обхода ошибки.**

## 10. Что проверено и что нет

| Проверено | Не проверено |
| --- | --- |
| Digest-регистрация и вызов PJSUA | Gm IPsec (`WITH_IPSEC` включён, согласование защиты не принято) |
| AKA-регистрация и вызов SIPp в обе стороны с Cx | Синхронизация AUTS |
| Жизненный цикл регистрации, отказ вызова незарегистрированному абоненту | PRACK/UPDATE |
| Транскодирование AMR/AMR-WB ↔ PCMU | Внешние софтфоны вне IMS-пула, настоящие телефоны |
