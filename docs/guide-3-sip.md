# Туториал 3. SIP-серверы и клиенты

Последняя часть цепочки: стенд запущен по [туториалу 1](guide-1-ims-core.md) (IMS) и
[туториалу 2](guide-2-ims-ai.md) (AI), ничего заново запускать не нужно. Здесь
разбирается SIP-часть этого же стенда: серверы Kamailio P/I/S-CSCF, PyHSS, RTPengine,
DNS; тестовые клиенты PJSUA; настройки телефона. В конце — остановка стенда.
Команды — из корня репозитория.

# Часть 1. Команды

**1. Что запущено**

```bash
docker compose --env-file app/config/lab.env ps
```

Результат: двенадцать контейнеров `Up` — семь IMS (`lab-dns`, `lab-mysql`, `lab-pyhss`,
`lab-icscf`, `lab-scscf`, `lab-rtpengine`, `lab-pcscf`) и пять AI. Тестовых клиентов
среди них нет: они существуют только во время проверок.

**2. Поднять тестовых клиентов вручную**

```bash
docker compose --env-file app/config/lab.env --profile test up -d sipue1 sipue2
docker logs lab-sipue1 2>&1 | grep 'Response msg 200/REGISTER'
```

Результат: строка `200/REGISTER` у клиента 1101 (у `lab-sipue2` — так же, 1102). Если
её нет сразу, подождите несколько секунд: клиент регистрируется после старта.

**3. Звонок 1101 → 1102**

```bash
docker exec lab-sipue1 sh -c 'printf "m\nsip:1102@%s\n" "$IMS_DOMAIN" > /tmp/pjsua-control'
sleep 10
docker logs --tail 40 lab-sipue2
docker exec lab-sipue1 sh -c 'printf "ha\n" > /tmp/pjsua-control'
```

Результат: у `lab-sipue2` входящий вызов с автоответом `200`. Другие команды PJSUA —
[раздел 3](#3-тестовые-клиенты-pjsua).

**4. Убрать тестовых клиентов**

```bash
docker compose --env-file app/config/lab.env --profile test rm -sf sipue1 sipue2
```

Клиенты, оставленные запущенными, держат регистрацию в S-CSCF; проверки всё равно
пересоздают их, но порядок на стенде лучше поддерживать самим.

**5. Абоненты в HSS**

```bash
python3 scripts/provision.py                 # план без изменений
python3 scripts/provision.py --apply         # завести или обновить
curl -s http://127.0.0.1:8088/ims_subscriber/list | python3 -m json.tool | head
```

**6. Пересобрать сервер после изменения конфигурации**

```bash
docker compose --env-file app/config/lab.env build scscf rtpengine
docker compose --env-file app/config/lab.env up -d --force-recreate pcscf icscf scscf rtpengine
python3 scripts/start.py
```

`start.py` (с тем же `--mode`, что в туториале 2) проверяет Cx и при необходимости
перезапускает CSCF в правильном порядке; остальные контейнеры не трогает.

**7. Остановка стенда** (конец цепочки; подробно — [раздел 6](#6-остановка-и-обновление))

```bash
docker compose --env-file app/config/lab.env --profile test down
```

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
в профиль Compose `test`: обычный `up` и `start.py` их не запускают. Каждая проверка
пересоздаёт их со своими параметрами (WAV, автоконференция) и удаляет при завершении,
поэтому между проверками на стенде нет лишних контейнеров.
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
пересоздайте контейнер, а для S-CSCF и RTPengine пересоберите образ (часть 1, шаг 6).

Не сбрасывайте SQN и не отключайте аутентификацию, чтобы обойти ошибку.

## 6. Остановка и обновление

`docker compose --env-file app/config/lab.env --profile test down` удаляет все наши
контейнеры (вместе с тестовыми клиентами, если они остались) и внутреннюю сеть
`lab-ai-backend`. Сеть ядра `oai-cn5g` не трогается: её создаёт и удаляет ядро. Тома с
базой HSS, токеном и моделями остаются; `down -v` удалит и их, тогда абоненты
заводятся заново, а модели скачиваются снова.

Чтобы убрать только AI и вернуться к состоянию после туториала 1:

```bash
docker compose --env-file app/config/lab.env rm -sf sip-as media-adapter ai-worker voice-agent llm-worker llm-model-init stand-init
```

Обратно — `python3 scripts/start.py`. После обновления исходников повторите тот же
`start.py` и проверки туториалов 1 и 2. Изменение `lab.env` применяется
пересозданием сервиса (`start.py` делает это сам); `docker restart` оставляет старое
окружение.
