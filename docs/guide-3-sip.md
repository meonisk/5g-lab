# Туториал 3. SIP-серверы и клиенты

SIP-часть стенда: серверы Kamailio P/I/S-CSCF, PyHSS, RTPengine, DNS; тестовые
клиенты PJSUA; настройки телефона. Подключение к ядру — [туториал 1](guide-1-ims-core.md),
AI-услуги — [туториал 2](guide-2-ims-ai.md). Команды — из корня репозитория.

# Часть 1. Команды

**1. Поднять SIP-серверы без AI**

```bash
python3 scripts/start.py --ims-only
docker compose --env-file app/config/lab.env ps
```

Результат: `lab-dns`, `lab-mysql`, `lab-pyhss`, `lab-icscf`, `lab-scscf`,
`lab-rtpengine`, `lab-pcscf` — `Up`.

**2. Регистрация тестовых клиентов**

```bash
bash app/tests/integration/verify-ims.sh
```

Результат: `IMS DNS + HSS + REGISTRATION: PASS`; клиенты 1101 и 1102 зарегистрированы.

**3. Звонок 1101 → 1102 вручную**

```bash
docker exec lab-sipue1 sh -c 'printf "m\nsip:1102@%s\n" "$IMS_DOMAIN" > /tmp/pjsua-control'
sleep 10
docker logs --tail 40 lab-sipue2
docker exec lab-sipue1 sh -c 'printf "ha\n" > /tmp/pjsua-control'
```

Результат: у `lab-sipue2` входящий вызов с автоответом `200`.

**4. Абоненты в HSS**

```bash
python3 scripts/provision.py                 # план без изменений
python3 scripts/provision.py --apply         # завести или обновить
curl -s http://127.0.0.1:8088/ims_subscriber/list | python3 -m json.tool | head
```

**5. Пересобрать сервер после изменения конфигурации**

```bash
docker compose --env-file app/config/lab.env build scscf rtpengine
docker compose --env-file app/config/lab.env up -d --force-recreate pcscf icscf scscf rtpengine
python3 scripts/start.py --ims-only
```

Последняя команда дожидается Cx и перезапускает CSCF в правильном порядке.

# Часть 2. Как устроено

## 1. Серверы

- **P-CSCF** — Kamailio из образа `docker_kamailio` (закреплён по digest), `lab-pcscf`,
  порт `PCSCF_SIP_PORT` (5060). Вход телефона в IMS; при каждом вызове вызывает
  `rtpengine_manage()` и привязывает медиа к RTPengine.
- **I-CSCF** — тот же образ, `lab-icscf`, 5060. При регистрации запрашивает HSS (UAR)
  и выбирает S-CSCF.
- **S-CSCF** — Kamailio с однострочным патчем `lookup()` регистратора (не маршрутизировать
  на истёкший контакт), образ `lab-kamailio-scscf`, порт 6060. Регистратор,
  аутентификация Digest/AKA, маршрутизация, вызов SIP AS по iFC.
- **HSS** — PyHSS с базой MySQL (`lab-pyhss`, `lab-mysql`). Абоненты IMS, ключи AuC, iFC;
  Diameter Cx к I/S-CSCF; REST API на `127.0.0.1:${PYHSS_API_PORT}`.
- **RTPengine** — `lab-rtpengine`, NG 2223, RTP 30000–30100, с `libavcodec-extra`:
  ретрансляция RTP и транскодирование AMR/AMR-WB ↔ PCMU.
- **DNS** — dnsmasq, `lab-dns`, 53. Зона IMS-домена и SRV-записи SIP.

Конфигурации CSCF, PyHSS и RTPengine взяты из проекта docker_open5gs и лежат в
`app/infrastructure/vendor/docker_open5gs/`: у каждого сервера свой `*_init.sh`,
который при старте подставляет значения из `lab.env` и добавляет маршрут
`IMS_UE_CIDR via UPF_IP`. Vendor-файлы правьте только с обоснованием и записью в
`PROVENANCE.md`. Патч S-CSCF и его проверка SHA-256 — в
`app/infrastructure/images/kamailio-scscf/` и `app/infrastructure/vendor/kamailio-ims/`.

DNS-зона ([ims-dnsmasq.conf](../app/infrastructure/configs/dns/ims-dnsmasq.conf))
отправляет сам домен и `icscf.<домен>` на I-CSCF, имена `pcscf.`, `scscf.`, `hss.`,
`as.`, `media.`, `voice-agent.` — на адреса сервисов, SRV `_sip._udp.<домен>` — на
I-CSCF, SRV `_sip._udp.scscf.<домен>` — на S-CSCF. Запросы к другим именам
пересылаются на `DNS_UPSTREAM_*`.

Изменения `lab.env` применяются пересозданием контейнера, а не `docker restart`.

## 2. Абоненты

[provision.py](../scripts/provision.py) заводит в PyHSS четырёх абонентов из
`lab.env`: телефоны `UE1`, `UE2` и тестовые клиенты `SIPUE1`, `SIPUE2`. Для каждого
создаются APN (если нет), AuC с ключами K/OPc/AMF, subscriber и IMS subscriber с
MSISDN, доменом и iFC `default_ifc.xml`. Скрипт можно запускать повторно: он
обновляет записи, но не перезаписывает ключи существующего AuC. Если ключи в
`lab.env` разошлись с HSS, он останавливается; заменить их можно явно, флагом
`--replace-keys` (SQN сохраняется). Ключи проверяются до первой записи в HSS, поэтому
опечатка в `lab.env` не оставит половину абонентов.

Идентификаторы абонента: IMPI (имя пользователя) — `<IMSI>@<IMS_DOMAIN>`, IMPU —
`sip:<MSISDN>@<домен>`, `tel:<MSISDN>` и `sip:<IMSI>@<домен>`, realm — `<IMS_DOMAIN>`.
Поэтому на абонента можно звонить и по номеру, и по IMSI.

Чтобы добавить телефон, поменяйте `UE1_*` или `UE2_*`, либо добавьте префикс в
`PROFILES` в `provision.py` и соответствующие строки в `lab.env`.

## 3. Тестовые клиенты PJSUA

`lab-sipue1` и `lab-sipue2` (образ `lab-pjsua`, pjproject 2.14.1, только аудио) входят
в профиль Compose `test`: обычный `up` их не запускает, тесты поднимают их сами.
Клиенты подключены к сети ядра со своими адресами `SIPUE1_IP`, `SIPUE2_IP` и
регистрируются на P-CSCF напрямую, без 5G-сессии. Аутентификация — SIP Digest:
закреплённая версия PyHSS использует K абонента из AuC как пароль Digest, поэтому
клиент получает `SIPUE<n>_IMS_K`. Это упрощение для тестов, не IMS AKA.

[sip-ue-run.sh](../scripts/sip-ue-run.sh) готовит звук (WAV из `SIPUE<n>_PLAYBACK_FILE`
или фраза `SIP_UE_TEST_UTTERANCE`, синтезированная eSpeak), создаёт FIFO
`/tmp/pjsua-control` и запускает PJSUA с единственным кодеком `SIP_UE_CODEC`
(PCMU/8000) и автоответом. Звуковой карты нет (`--null-audio`); то, что клиент
«говорит», берётся из WAV, а то, что он «слышит», видно по счётчикам RTP.

Команды отправляются в FIFO так: `docker exec lab-sipue1 sh -c 'printf "<команда>" > /tmp/pjsua-control'`.
Ответ читается в `docker logs --tail 80 lab-sipue1`.

- `m\nsip:<номер>@<домен>\n` — позвонить;
- `cl\n` — список портов конференц-моста (обычно 1 — проигрыватель WAV, 4 — вызов);
- `cc\n1\n4\n` — подать звук проигрывателя в вызов, `cd\n1\n4\n` — отключить;
- `d\n` — дамп состояния (заодно выталкивает буфер журнала);
- `ha\n` — положить все вызовы.

## 4. Телефон

Телефон должен попадать в IMS через ядро: PDU-сессия DNN `ims`, P-CSCF и DNS из SMF.
Нужен Android с 5G SA и VoNR в диапазоне вашей радиосети, с IMS и AMR/AMR-WB, и
программируемая USIM/ISIM, ключи которой совпадают с `UE<n>_IMS_K`/`OPC` в `lab.env`.

Если клиент настраивается вручную: outbound proxy `sip:<PCSCF_IP>:5060;transport=udp;lr`,
registrar `sip:<IMS_DOMAIN>`, SIP URI `sip:<IMSI>@<IMS_DOMAIN>`, имя пользователя
`<IMSI>@<IMS_DOMAIN>`, realm `<IMS_DOMAIN>`, кодек PCMU/8000 или AMR/AMR-WB (EVS не
поддержан). Ограничения: защита Gm (IPsec) не принята; SIP AS не поддерживает
обязательные `100rel`/`precondition` (PRACK/UPDATE).

## 5. Диагностика SIP

Если `REGISTER` тестового клиента остаётся без ответа, проверьте, что P-CSCF доступен
из сети ядра (`docker exec lab-sipue1 ping -c1 <PCSCF_IP>`) и что `lab-pcscf` запущен.
Повторяющийся `401` и затем отказ означают несовпадение ключей клиента и AuC или
неверный realm: смотрите `docker logs lab-icscf`, `lab-scscf`, `lab-pyhss`.
`403`/`404` при регистрации — абонента нет в HSS (`provision.py --apply`). Если вызов
есть, а звука нет или он в одну сторону, сравните адреса и порты в SDP с сессией в
`docker logs lab-rtpengine`. Если изменения конфигурации CSCF не применились,
пересоздайте контейнер, а для S-CSCF и RTPengine пересоберите образ (часть 1, шаг 5).

Не сбрасывайте SQN и не отключайте аутентификацию, чтобы обойти ошибку.
