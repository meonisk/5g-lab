# Туториал 3. Установка и настройка SIP-серверов и клиентов

Этот документ описывает SIP-часть стенда: какие SIP-серверы и клиенты в нём есть,
как они собираются и запускаются, где их конфигурация, как добавить абонента,
позвонить с клиента и проверить регистрацию и вызов. Связь IMS с ядром 5G — в
[первом туториале](guide-1-ims-core.md), AI-услуги — во [втором](guide-2-ims-ai.md).

Документ состоит из двух частей:

- **Часть 1 — только команды.** Поднять SIP-серверы, зарегистрировать клиентов,
  позвонить и проверить Digest и AKA.
- **Часть 2 — разъяснения.** Состав серверов и клиентов, конфигурация, абоненты,
  параметры PJSUA и SIPp, внешний клиент и телефон, диагностика.

Все команды — из корня репозитория, в активированном `.venv`. Требования к машине
и установка Docker/Python — [туториал 1, часть 1](guide-1-ims-core.md#а-локальный-стенд-наше-ядро-oai--ims).
Команды Bash даны для Linux; на Windows `bash ...` запускайте в Git Bash,
`./scripts/compose.sh` заменяйте на `./scripts/compose.ps1`.

# Часть 1. Команды

## А. Поднять SIP-серверы

**Локальный стенд** (ядро + IMS + два SIP-клиента):

```bash
python scripts/initialize_local.py
python scripts/start_lab.py --base-only
```

Ожидается `LOCAL 5G IMS BASE: READY`.

**Или только IMS у ядра партнёров** (Linux, `lab.env` заполнен по
[туториалу 1, вариант Б](guide-1-ims-core.md#б-ядро-уже-работает-у-партнёров-ставим-только-ims--ai)):

```bash
python scripts/initialize_local.py --ims-only
python scripts/start_partner.py --check
python scripts/start_partner.py --ims-only
```

## Б. Убедиться, что серверы работают

```bash
./scripts/compose.sh ps
./scripts/compose.sh logs --tail 50 pcscf icscf scscf pyhss rtpengine dns
```

Контейнеры `lab-pcscf`, `lab-icscf`, `lab-scscf`, `lab-pyhss`, `lab-mysql`,
`lab-rtpengine`, `lab-dns` — `Up`. У партнёров вместо `./scripts/compose.sh`:
`docker compose --env-file app/config/lab.env --env-file local/secrets/ims.env -f compose.partner.yml`.

## В. Регистрация и звонок между клиентами PJSUA (локальный стенд)

**1. Проверить регистрацию**

```bash
bash app/tests/integration/verify-ims-registration.sh
```

`PASS` — оба клиента (1001, 1002) зарегистрированы.

**2. Позвонить 1001 → 1002 вручную**

```bash
docker exec lab-sipue1 sh -lc 'printf "m\nsip:1002@%s\n" "$IMS_DOMAIN" > /tmp/pjsua-control'
sleep 10
docker logs --tail 40 lab-sipue1
docker logs --tail 40 lab-sipue2
docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control'
```

У `lab-sipue1` — `200 OK` на INVITE, у `lab-sipue2` — входящий вызов с автоответом.

**3. Автоматическая проверка вызова**

```bash
bash app/tests/integration/verify-ims-call.sh
```

**4. После перезапуска радиочасти** — пересоздать клиентов:

```bash
./scripts/compose.sh up -d --force-recreate sipue1 sipue2
```

## Г. Проверки IMS AKA с SIPp

**1. Собрать клиент SIPp**

```bash
docker build -f app/infrastructure/images/sipp-aka/Dockerfile -t lab-sipp-aka:3.7.7-opc .
docker run --rm lab-sipp-aka:3.7.7-opc -v
```

Ожидается `SIPp v3.7.7-TLS-SCTP-PCAP-SHA256` (код выхода 1 — норма).

**2. Остановить AS/AI, если они запущены**

```bash
docker stop lab-sip-as lab-ai-worker lab-media-adapter lab-voice-agent
```

**3. Проверки** (строго по одной, на свободном стенде)

```bash
python app/tests/integration/verify_plain_call.py
python app/tests/integration/verify_aka_registration.py
python app/tests/integration/verify_aka_registration.py --bad-response
python app/tests/integration/verify_aka_call.py
python app/tests/integration/verify_aka_call.py --caller 2
python app/tests/integration/verify_aka_lifecycle.py
```

В каждом результате `status` и `cleanup` — `PASS`.

**4. Вернуть AS/AI**

```bash
./scripts/compose.sh up -d --no-deps --force-recreate sip-as ai-worker media-adapter voice-agent
```

## Д. Транскодирование кодеков телефона

```bash
python app/tests/integration/verify_phone_codecs.py
```

## Е. Пересобрать сервер после изменения конфигурации

```bash
./scripts/compose.sh build scscf rtpengine
./scripts/compose.sh up -d --force-recreate pcscf icscf scscf rtpengine
```

# Часть 2. Разъяснения

## 1. Состав

### SIP-серверы

| Сервер | Реализация | Контейнер, адрес, порт | Роль |
| --- | --- | --- | --- |
| P-CSCF | Kamailio (образ `docker_kamailio`, закреплён по digest) | `lab-pcscf`, `172.22.0.106:5060` | Вход UE в IMS; привязка медиа к RTPengine; удаление непроверенных идентификаторов |
| I-CSCF | Kamailio (тот же образ) | `lab-icscf`, `172.22.0.104:5060` | Запрос к HSS при регистрации, выбор S-CSCF |
| S-CSCF | Kamailio с патчем регистратора (`lab-kamailio-scscf:987459-expiry-v1`) | `lab-scscf`, `172.22.0.105:6060` | Регистратор, аутентификация (Digest/AKA), маршрутизация, вызов AS по iFC |
| HSS | PyHSS + MySQL | `lab-pyhss`, `172.22.0.103`; `lab-mysql`, `172.22.0.102` | Абоненты IMS, ключи AuC, iFC; Diameter Cx к I/S-CSCF |
| Медиа | RTPengine 26.0.1.23 + `libavcodec-extra59` | `lab-rtpengine`, `172.22.0.101`; NG 2223, RTP UDP 30000–30100 | Ретрансляция RTP, транскодирование AMR/AMR-WB ↔ PCMU |
| DNS | dnsmasq | `lab-dns`, `172.22.0.100:53` | Зона IMS-домена и SRV-записи SIP |
| SIP AS | Наш Python-сервис | `lab-sip-as`, `172.22.0.107:5070` | Прикладной сервер: AI-услуги по номерам ([туториал 2](guide-2-ims-ai.md)) |

### SIP-клиенты

| Клиент | Где | Аутентификация | Назначение |
| --- | --- | --- | --- |
| PJSUA (pjproject 2.14.1, только аудио) | `lab-sipue1`, `lab-sipue2` | Digest (лабораторная регрессия) | Постоянные тестовые абоненты 1001 и 1002, ручные вызовы |
| SIPp 3.7.7 с патчами AKA/OPc | Образ `lab-sipp-aka:3.7.7-opc`, временные контейнеры | IMS AKA (AKAv1-MD5, Milenage) | Проверки AKA-регистрации и вызова |
| Настоящий телефон / ISIM | У партнёров | IMS AKA | Целевой сценарий, пока не проверен |

## 2. Установка серверов

Отдельно SIP-серверы не устанавливаются: их собирает и запускает общий launcher.
Не запускайте фрагменты Compose самостоятельно — сети, тома и пути задаёт главная
конфигурация ([docker-compose.yml](../../docker-compose.yml) или
[compose.partner.yml](../../compose.partner.yml)).

Локальный стенд (OAI + IMS, без AI):

```bash
python scripts/initialize_local.py
python scripts/start_lab.py --base-only
```

Только IMS для внешнего ядра (Linux):

```bash
python scripts/initialize_local.py --ims-only
python scripts/start_partner.py --check
python scripts/start_partner.py --ims-only
```

Состояние и журналы серверов (Windows — `./scripts/compose.ps1`):

```bash
./scripts/compose.sh ps
./scripts/compose.sh logs --tail 100 pcscf icscf scscf pyhss rtpengine dns
```

### Образы, которые собираются локально

| Образ | Откуда | Как пересобрать |
| --- | --- | --- |
| S-CSCF | Базовый образ Kamailio по digest + однострочный патч `lookup()` в `ims_registrar_scscf` (не маршрутизировать на истёкший Contact) | `./scripts/compose.sh build scscf` |
| RTPengine | `app/infrastructure/vendor/docker_open5gs/rtpengine/`, добавлено кодирование AMR/AMR-WB | `./scripts/compose.sh build rtpengine` |
| DNS | `app/infrastructure/images/dnsmasq/` | `./scripts/compose.sh build dns` |
| PJSUA | `app/infrastructure/images/pjsua/` (pjproject 2.14.1 из исходников) | `./scripts/compose.sh build sipue1` |
| SIPp AKA | `app/infrastructure/images/sipp-aka/` | раздел 6 |

Dockerfile S-CSCF проверяет коммит Kamailio `9874599e…`, SHA-256 исходного
`lookup.c` и патча до применения. Происхождение и лицензии —
[kamailio-scscf-provenance.md](../kamailio-scscf-provenance.md),
[THIRD_PARTY.md](../../THIRD_PARTY.md).

## 3. Настройка серверов

### 3.1. Параметры в `app/config/lab.env`

| Параметр | По умолчанию | Смысл |
| --- | --- | --- |
| `IMS_DOMAIN` | `ims.mnc001.mcc001.3gppnetwork.org` | Домашний домен и realm |
| `PCSCF_IP`, `PCSCF_SIP_PORT` | `172.22.0.106`, `5060` | Адрес и порт P-CSCF |
| `ICSCF_IP`, `ICSCF_SIP_PORT` | `172.22.0.104`, `5060` | I-CSCF |
| `SCSCF_IP`, `SCSCF_SIP_PORT` | `172.22.0.105`, `6060` | S-CSCF |
| `PCSCF_UDP_MTU` | `65535` | Порог UDP для P-CSCF |
| `RTPENGINE_IP`, `RTPENGINE_NG_PORT` | `172.22.0.101`, `2223` | RTPengine и его управляющий порт NG |
| `RTPENGINE_PORT_MIN`, `RTPENGINE_PORT_MAX` | `30000`, `30100` | Диапазон RTP |
| `SIP_AS_IP`, `SIP_AS_PORT` | `172.22.0.107`, `5070` | Прикладной сервер |
| `KAMAILIO_IMAGE`, `SCSCF_IMAGE`, `PYHSS_IMAGE`, `MYSQL_IMAGE` | закреплены по digest | Версии образов |

После изменения параметров пересоздайте затронутые серверы
(`./scripts/compose.sh up -d --force-recreate <сервис>`); смена адресов или сетей
может потребовать полного перезапуска стенда. `restart` новое окружение не применяет.

### 3.2. Файлы конфигурации

| Сервер | Файлы |
| --- | --- |
| P-CSCF | `app/infrastructure/vendor/docker_open5gs/pcscf/`: `kamailio_pcscf.cfg`, `pcscf.cfg` (defines, в т.ч. `WITH_IPSEC`), `route/` (маршруты исходящих/входящих), `pcscf_init.sh` |
| I-CSCF | `app/infrastructure/vendor/docker_open5gs/icscf/` |
| S-CSCF | `app/infrastructure/vendor/docker_open5gs/scscf/`: `kamailio_scscf.cfg` (`route[REGISTER]`, `WITH_AUTH`), `scscf.cfg`, `scscf_init.sh` |
| PyHSS | `app/infrastructure/vendor/docker_open5gs/pyhss/`: `config.yaml`, `default_ifc.xml`, `default_sh_user_data.xml`; профиль без AS — `app/infrastructure/configs/pyhss/baseline_ifc.xml` |
| RTPengine | `app/infrastructure/vendor/docker_open5gs/rtpengine/` |
| DNS | `app/infrastructure/configs/dns/ims-dnsmasq.conf` (шаблон, подстановка из `lab.env`) |

Конфигурации CSCF взяты из проекта docker_open5gs (отсюда имя папки); активное
ядро при этом — OAI. Правки vendor-файлов делайте только с обоснованием и
записью происхождения.

### 3.3. DNS-зона IMS

Шаблон `ims-dnsmasq.conf` разрешает:

- `<IMS_DOMAIN>` и `icscf.<домен>` → I-CSCF (на него приходит REGISTER по домену);
- `pcscf.`, `scscf.`, `hss.`, `as.`, `media.`, `voice-agent.` → адреса сервисов;
- SRV `_sip._udp` / `_sip._tcp.<домен>` → I-CSCF:`ICSCF_SIP_PORT`;
- SRV `_sip._udp` / `_sip._tcp.scscf.<домен>` → S-CSCF:`SCSCF_SIP_PORT`.

### 3.4. iFC: когда S-CSCF вызывает AS

Шаблон [default_ifc.xml](../../app/infrastructure/vendor/docker_open5gs/pyhss/default_ifc.xml)
применяется к каждому абоненту при provisioning. Действующее правило: исходящий
(`SessionCase 0`) `INVITE`, приоритет 30, сервер
`sip:as.<домен>:<SIP_AS_PORT>;transport=udp`, `DefaultHandling 0` — при
недоступности AS вызов продолжается. Проверка обычного вызова без AS
(`verify_plain_call.py`) временно отключает AS в iFC и потом восстанавливает его.

## 4. Абоненты в HSS

Абонентов создаёт [provision-ims-subscribers.sh](../../scripts/provision-ims-subscribers.sh)
(его вызывают `start_lab.py` и `start_partner.py`). Скрипт работает через REST API
PyHSS по отдельной management-сети и создаёт:

1. APN (если его нет);
2. запись AuC: IMSI, IMS K, OPc, AMF;
3. subscriber;
4. IMS subscriber: MSISDN, домен, `ifc_path: default_ifc.xml`.

Существующие записи обновляются, ключи не перезаписываются молча, SQN не сбрасывается.
Ключи берутся из `local/secrets/ims.env` (`UE1_IMS_K`, `UE1_IMS_OPC`,
`UE1_IMS_AMF` и т.д.), идентификаторы — из `UE*_IMSI` и `UE*_MSISDN` в `lab.env`.

Идентификаторы абонента:

| Что | Формат | Пример UE1 |
| --- | --- | --- |
| IMPI (username) | `<IMSI>@<домен>` | `001010000000001@ims.mnc001.mcc001.3gppnetwork.org` |
| IMPU | `sip:<MSISDN>@<домен>`, `tel:<MSISDN>`, `sip:<IMSI>@<домен>` | `sip:1001@ims.mnc001.mcc001.3gppnetwork.org` |
| Realm | `<IMS_DOMAIN>` | `ims.mnc001.mcc001.3gppnetwork.org` |

**Чтобы добавить абонента сейчас**, используется тот же путь: текущий bootstrap
создаёт двух согласованных тестовых абонентов (`UE1_*`, `UE2_*`). Для другого
абонента измените `UE*_IMSI`/`UE*_MSISDN` и ключи, затем повторите
`python scripts/start_partner.py --ims-only` (или `start_lab.py --base-only`).
Для существующих баз смена ключей — только явной миграцией с backup.

Особенность лабораторного Digest: в закреплённом PyHSS Digest использует AuC `ki`
как пароль. Поэтому Compose передаёт каждому PJSUA его `UE*_IMS_K` как
`IMS_DIGEST_PASSWORD`. Это ограничение регрессионного Digest-клиента, а не IMS AKA;
production Ki как Digest-пароль не применять.

## 5. SIP-клиент PJSUA

### 5.1. Как он запускается

Контейнеры `lab-sipue1`/`lab-sipue2` (образ `lab-pjsua`) делят сетевое пространство
с эмулированными UE (`network_mode: service:ue1`). Скрипт
[sip-ue-run.sh](../../scripts/sip-ue-run.sh):

1. ждёт TUN UERANSIM с адресом из `IMS_UE_CIDR`;
2. ставит маршруты `/32` к `PCSCF_IP` и `RTPENGINE_IP` через этот TUN — SIP и RTP
   идут через IMS PDU-сессию, а не через Docker bridge;
3. готовит WAV для воспроизведения (из `SIP_UE_PLAYBACK_FILE` или синтезом eSpeak
   фразы `SIP_UE_TEST_UTTERANCE`);
4. создаёт управляющий FIFO `/tmp/pjsua-control` и запускает PJSUA;
5. каждые 2 с проверяет TUN, адрес и маршруты; при изменении завершается, и Docker
   перезапускает клиент с новой регистрацией.

Фактическая команда PJSUA:

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

### 5.2. Параметры клиента (`lab.env`)

| Параметр | По умолчанию | Смысл |
| --- | --- | --- |
| `SIP_UE_CODEC` | `PCMU/8000` | Единственный разрешённый кодек |
| `SIP_UE_AUTO_ANSWER` | `200` | Автоответ на входящий вызов |
| `SIP_UE_AUTO_CONFERENCE` | `1` | Автоматически подключать проигрыватель к вызову |
| `SIP_UE_TEST_UTTERANCE` | русская фраза | Текст для синтеза тестового WAV |
| `SIP_UE_PLAYBACK_FILE` | пусто | Готовый WAV вместо синтеза |
| `SIP_UE_RECORD_FILE` | пусто | Записывать принятый звук (то, что слышит абонент) |
| `SIP_CALL_DURATION_SECONDS` | `20` | Длительность тестового вызова |

Звуковая карта не используется (`--null-audio`): успешный вызов не включает звук
в динамиках компьютера; принятый звук можно записать в WAV.

### 5.3. Управление клиентом

Команды PJSUA пишутся в FIFO (Git Bash или Linux Bash):

| Действие | Команда |
| --- | --- |
| Позвонить | `docker exec lab-sipue1 sh -lc 'printf "m\nsip:1002@%s\n" "$IMS_DOMAIN" > /tmp/pjsua-control'` |
| Список аудиопортов | `docker exec lab-sipue1 sh -lc 'printf "cl\n" > /tmp/pjsua-control'` |
| Подключить порт 1 к порту 4 | `docker exec lab-sipue1 sh -lc 'printf "cc\n1\n4\n" > /tmp/pjsua-control'` |
| Отключить | `docker exec lab-sipue1 sh -lc 'printf "cd\n1\n4\n" > /tmp/pjsua-control'` |
| Завершить все вызовы | `docker exec lab-sipue1 sh -lc 'printf "ha\n" > /tmp/pjsua-control'` |

Ответ клиента — в `docker logs --tail 80 lab-sipue1`. В PowerShell номер и домен
можно взять из `lab.env`:

```powershell
$number = (Select-String '^VOICE_TRANSLATOR_MSISDN=' app/config/lab.env).Line.Split('=', 2)[1]
$domain = (Select-String '^IMS_DOMAIN=' app/config/lab.env).Line.Split('=', 2)[1]
docker exec lab-sipue1 sh -lc "printf 'm\nsip:${number}@${domain}\n' > /tmp/pjsua-control"
```

После перезапуска радиочасти (`gnb ue1 ue2`) пересоздайте клиенты, чтобы сокеты
привязались к новым IMS-адресам:

```bash
./scripts/compose.sh up -d --force-recreate sipue1 sipue2
```

## 6. SIP-клиент SIPp для IMS AKA

PJSUA проверяет только Digest. Для IMS AKA используется SIPp, собранный из
исходников с двумя лабораторными патчами: бинарно-безопасная передача `aka_K`,
`aka_OP`, `aka_AMF` и новый параметр `aka_OPc` (прямой ввод OPc для Milenage).
Сборка запускает синтетический тест кодирования и тест по 3GPP TS 35.208 Test Set 1.

```bash
docker build -f app/infrastructure/images/sipp-aka/Dockerfile -t lab-sipp-aka:3.7.7-opc .
docker run --rm lab-sipp-aka:3.7.7-opc -v
```

Ожидается строка `SIPp v3.7.7-TLS-SCTP-PCAP-SHA256` (код выхода 1 для `-v` — норма).
Происхождение и контрольные суммы — [sipp-aka-provenance.md](../sipp-aka-provenance.md).

Как устроен AKA-вызов: один процесс SIPp **на каждое UE**, один UDP-сокет
(`-t u1 -users 1 -m 2`). Первый «вызов» сценария выполняет REGISTER с AKA, второй —
INVITE с новым Call-ID и маршрутом из Service-Route. Вызываемая сторона принимает
INVITE тем же сокетом через `-oocsf`. RTP передаёт отдельный помощник в сети UE.
Ключи попадают только в приватные сгенерированные XML, не в командную строку
и не в трассы. Подробности — [aka-continuous-client-spike.md](../aka-continuous-client-spike.md).

Параметры SIPp в `lab.env`: `SIP_AKA_PORT` (5062), `SIP_AKA_MEDIA_PORT` (4000),
`SIP_AKA_CALL_SECONDS` (20), `SIP_AKA_TIMEOUT_SECONDS` (35), `SIP_AKA_EXPIRY_SECONDS`
(30) и таймауты восстановления `SIP_AKA_*_TIMEOUT_SECONDS`.

## 7. Внешний SIP-клиент и настоящий телефон

Что настроить в ядре партнёров, чтобы их UE дошли до нашего P-CSCF, —
[туториал 1, раздел 6](guide-1-ims-core.md#6-вариант-б-подключение-ims--ai--sip-к-уже-работающему-ядру).

Клиент должен находиться **в IMS-пуле UE** (иметь IMS PDU-сессию через ядро) либо
иметь маршрут к P-CSCF и RTPengine без NAT. Подключение произвольного софтфона
из LAN в обход ядра этим стендом не проверялось.

Параметры для клиента:

| Поле | Значение |
| --- | --- |
| Outbound proxy | `sip:<PCSCF_IP>:<PCSCF_SIP_PORT>;transport=udp;lr` |
| Registrar / домен | `sip:<IMS_DOMAIN>` |
| SIP URI | `sip:<IMSI>@<IMS_DOMAIN>` (или IMPU с MSISDN) |
| Имя пользователя | `<IMSI>@<IMS_DOMAIN>` |
| Realm | `<IMS_DOMAIN>` |
| Аутентификация | IMS AKA с K/OPc/AMF абонента; Digest — только лабораторная регрессия |
| Кодек | PCMU/8000; AMR/AMR-WB транскодирует RTPengine; EVS не поддержан |
| Транспорт | UDP/TCP текущего профиля, без TLS/IPsec (Gm security не принята) |

Ограничения:

- SIP AS отклоняет вызовы, в которых обязательны `100rel`/`precondition`. Если
  телефон их требует, нужна реализация PRACK/UPDATE и согласования QoS.
- Для телефона нужен Android с 5G SA и VoNR в диапазоне партнёров, IMS и AMR/AMR-WB;
  программируемая USIM/ISIM с согласованными IMS-идентификаторами. Операторскую SIM
  нельзя скопировать в HSS. Подробнее — [native-phone.md](../native-phone.md).
- `python scripts/phone_readiness.py` только читает серверные возможности;
  `NOT_READY` ожидаем до приёмки телефона.

## 8. Проверки

### 8.1. Регистрация и вызов (Digest, PJSUA)

```bash
bash app/tests/integration/verify-ims-registration.sh
bash app/tests/integration/verify-ims-call.sh
```

Обычный вызов успешен, когда UE1 получает `200 OK`, UE2 получает INVITE через IMS,
S-CSCF вызывает AS по iFC, RTPengine видит оба IMS-адреса.

### 8.2. Изолированные проверки Digest и AKA

Только на свободном базовом стенде, **с остановленными AS/AI и без активных
RTP-сессий**, строго по одной. Проверки блокируют стенд, временно останавливают
PJSUA и потом восстанавливают клиентов; смотрите и `status`, и `cleanup` в результате.

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

| Проверка | Что подтверждает |
| --- | --- |
| `verify_plain_call.py` | Вызов без AS в iFC, звук в обе стороны (`--mute-ue` — обнаружение пропавшего источника) |
| `verify_aka_registration.py` | AKA-регистрация двух UE и связанный Cx; `--bad-response` — отказ UE1 при успехе UE2 |
| `verify_aka_call.py` | AKA-регистрация и вызов одним процессом, PCMU в обе стороны, WAV у каждого UE |
| `verify_aka_lifecycle.py` | Регистрация, обновление, снятие (`Expires: 0`), свежий challenge на каждом шаге |
| `verify_aka_inactive_call.py` | Вызов снятого с регистрации или истёкшего абонента: `404`, ACK, без оставшейся RTP-сессии |

Если AS/AI уже запущены, перед AKA-вызовом остановите и затем верните их:

```bash
docker stop lab-sip-as lab-ai-worker lab-media-adapter lab-voice-agent
python app/tests/integration/verify_aka_call.py --caller 1
./scripts/compose.sh up -d --no-deps --force-recreate sip-as ai-worker media-adapter voice-agent
```

Приватные результаты (XML с ключами, SIP/PCAP, WAV, `result.json`) остаются в
`local/private/plain-call-*`, `aka-register-*`, `aka-call-*`, `aka-lifecycle-*`,
`aka-inactive-*` и не публикуются.

### 8.3. Кодеки телефона

```bash
python app/tests/integration/verify_phone_codecs.py
```

Синтетический обмен AMR/AMR-WB ↔ PCMU через RTPengine, обе упаковки (`octet-align`
0 и 1). Это проверка транскодирования, а не полного SIP-вызова и не разборчивости речи.

## 9. Диагностика

| Симптом | Что проверить |
| --- | --- |
| REGISTER без ответа | Маршруты `/32` в клиенте (`docker logs lab-sipue1`, строка `IMS transport:`), доступность P-CSCF и DNS с IMS-адреса, порт 5060, firewall |
| `401` повторяется, затем отказ | IMPI/IMPU и realm, способ аутентификации, совпадение ключей клиента и AuC, журналы I/S-CSCF и PyHSS (Cx) |
| Регистрация AKA вытесняется | Digest-клиенты не остановлены: лимит одного Contact с overwrite вытесняет binding |
| `ERROR: no TUN reaches IMS_UE_GATEWAY` | У UE нет IMS PDU-сессии: см. [туториал 1](guide-1-ims-core.md#8-диагностика) |
| Вызов есть, звука нет или в одну сторону | SDP (адреса и порты), маршруты к RTPengine в обе стороны, диапазон RTP, кодек, `docker logs lab-rtpengine` |
| Телефон получает отказ при `100rel`/`precondition` | Ограничение текущего SIP AS (раздел 7) |
| После перезапуска первый вызов не проходит | Пересоздать `sipue1 sipue2`, повторить регистрацию; прежний `FAIL` сохраняется |
| Изменения конфигурации CSCF не применились | Пересоздать контейнер, для S-CSCF/RTPengine — пересобрать образ |

Не сбрасывайте SQN и не отключайте аутентификацию для обхода ошибки.

## 10. Что проверено и что нет

Проверено: Digest-регистрация и вызов PJSUA, AKA-регистрация и вызов SIPp в обе
стороны с Cx, жизненный цикл регистрации и отказ вызова незарегистрированному
абоненту, транскодирование AMR/AMR-WB ↔ PCMU.

Не проверено: Gm IPsec (`WITH_IPSEC` включён, но согласование защиты не принято),
синхронизация AUTS, PRACK/UPDATE, внешние софтфоны вне IMS-пула, настоящие телефоны.
