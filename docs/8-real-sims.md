# 8. Настоящие SIM и телефоны: PLMN 901/70, gNB на USRP X310

Как стенд работает с партией исследовательских SIM-карт и настоящими телефонами:
что меняется в ядре и IMS, как включить и выключить всё одной командой, как
проверить готовность и что смотреть во время звонка. Общая картина 5G и IMS —
[документ 7](7-guide.md).

## 1. Что получилось

| Часть | Состояние |
|---|---|
| PLMN | `901/70` в ядре OAI (AMF), в gNB на X310 и в rfsim; IMS-домен `ims.mnc070.mcc901.3gppnetwork.org` |
| SIM | 10 карт, IMSI `901700000029600`–`…609`, номера `2600`–`2609`; заведены в UDR ядра (5G AKA) и в PyHSS (IMS AKA) с одними Ki/OPc |
| Эмулятор | UE1/UE2 rfsim с IMSI `90170…`: `verify-all.sh` проходит целиком, включая `verify-5g` |
| Радио | gNB OAI на USRP X310, n78, 20 МГц (`band78_20mhz.conf`) |
| Звонки в AI со штатной звонилки | номера 1003–1006 поддерживают `100rel`, QoS preconditions, PRACK и UPDATE (RFC 3262, 3312, 3311) |
| Проверено с телефоном | нет: регистрация и звонок настоящего телефона — следующий шаг |

## 2. Секреты

Репозиторий публичный. Ki/OPc карт в Git не попадают никогда:

- список карт лежит только в `local/secrets/research-sims.csv` (каталог `local/`
  игнорируется Git, права `600`);
- скрипты не печатают ключи: `plan`, `status`, `check` выводят только IMSI, номера и
  IMPI; ошибки MySQL не пересказываются, потому что в них может быть текст запроса;
- журналы для разбора (`stand_check.py collect`) сохраняются без строк с материалом
  аутентификации.

Файл списка создаётся импортом таблицы поставщика:

```bash
python3 scripts/research_sims.py import sim_imsi.xlsx   # или CSV; PIN/PUK не переносятся
python3 scripts/research_sims.py plan                    # проверка без ключей
```

Колонки CSV: `IMSI,ICCID,KI,OPC,AMF,MSISDN`. Номер карты по умолчанию — префикс
`RESEARCH_SIM_MSISDN_PREFIX` и последние `RESEARCH_SIM_MSISDN_SUFFIX_DIGITS` цифр IMSI.

## 3. Включить и выключить всё

```bash
scripts/stand.sh down     # gNB, rfsim, IMS + AI, ядро OAI
scripts/stand.sh up       # ядро -> настройка ядра -> IMS + AI -> gNB -> проверка
scripts/stand.sh status
```

`up` выполняет по порядку:

1. `docker compose up -d` ядра OAI и ожидание, пока все NF станут healthy.
2. `scripts/core-setup.sh apply` — PLMN, P-CSCF и DNS для телефона, NAT, абоненты UDR.
   Повторный запуск безопасен: уже заведённые абоненты и их SQN не меняются.
3. `scripts/setup.sh` — IMS и AI в режиме `AI_MODE` (на сервере `compact`), заведение
   абонентов в PyHSS.
4. `scripts/gnb.sh up` — gNB на X310 с PLMN из `lab.env`. Если gNB не поднялся,
   проверка всё равно выполняется, а `up` завершается с ошибкой.
5. `python3 scripts/stand_check.py` — готовность к телефону.

`down` останавливает ядро (`stop`), а не удаляет его контейнеры: у базы MySQL ядра в
учебной раскладке OAI нет тома, и новая база вернула бы SQN карт в ноль. Тома IMS и
AI (PyHSS, модели, записи) тоже остаются.

После перезагрузки сервера достаточно `scripts/stand.sh up`: контейнеры IMS и AI
поднимаются сами, ядро и gNB — нет.

Каталог ядра скрипты берут из `OAI_CORE_DIR`, иначе — из метки Compose у контейнера
`oai-amf`, иначе `~/oai-cn5g`.

## 4. Что меняется в ядре OAI

`scripts/core-setup.sh apply` (вызывается из `stand.sh up`):

| Изменение | Зачем |
|---|---|
| `mcc`/`mnc` в `served_guami_list` и `plmn_support_list` = `MCC`/`MNC` | SIM видит и принимает только сеть своего PLMN |
| при смене PLMN пересоздаются NRF, UDR, UDM, AUSF, AMF, SMF, UPF | PLMN читается при старте |
| UE1/UE2 и SIM в `AuthenticationSubscription` и `SessionManagementSubscriptionData` | 5G AKA по тем же Ki/OPc, что в PyHSS |
| срез и DNN копируются с абонента ядра, у которого есть DNN `ims` | настройки сессий партнёра не меняются; статический адрес не копируется |

Расхождение ключей у уже заведённого IMSI — ошибка до записи. Исходные файлы ядра
сохраняются как `*.bak-ims`; откат — `scripts/core-setup.sh revert`.

PyHSS заполняет `scripts/provision.py` (из `setup.sh`): абоненты прежнего PLMN
удаляются, SIM заводятся с услугами `RESEARCH_SIM_SERVICES` и языком
`RESEARCH_SIM_LANGUAGE`.

## 5. gNB на USRP X310

```bash
scripts/gnb.sh up       # копия GNB_CONF с PLMN и адресом NG/N3 -> nr-softmodem
scripts/gnb.sh status
scripts/gnb.sh down
```

- Исходная конфигурация — `GNB_CONF` (`band78_20mhz.conf` в `OAI_RAN_CONF_DIR`), в ней
  `sdr_addrs = "type=x300,addr=192.168.40.2"`. Аргументы — `GNB_ARGS`.
- Копия в `local/gnb/gnb.conf` получает PLMN и адрес хоста на мосту ядра для NG и N3.
  Исходный файл не меняется. Журнал — `local/gnb/gnb.log`.
- Если `GNB_CONF` пуст, скрипт берёт конфигурацию и аргументы уже работающего
  `nr-softmodem`, сохраняет их в `local/gnb/source.txt` и перезапускает его с копией.
- gNB X310 и gNB rfsim одновременно не работают: перед `verify-all.sh` нужен
  `scripts/gnb.sh down`, после — `scripts/gnb.sh up`.

`rfsim.sh` подставляет в свои копии тот же PLMN, а в UE — IMSI и ключи `UE1_*`/`UE2_*`.
UE, который OAI уронил при старте (`_Assert_Exit_` в `threadCreate`), запускается
заново, до трёх попыток.

## 6. Проверка готовности

```bash
python3 scripts/stand_check.py           # preflight
python3 scripts/stand_check.py phones    # какие SIM зарегистрированы в IMS
python3 scripts/stand_check.py watch     # REGISTER/INVITE/PRACK/UPDATE в реальном времени
python3 scripts/stand_check.py collect   # журналы в local/evidence/ без ключей
```

Preflight проверяет `lab.env`, контейнеры IMS, AI и ядра, PLMN в конфигурации ядра,
версию SIP AS, наличие всех SIM в UDR и PyHSS и делает самотест звонка в AI без
телефона: INVITE с `Supported: 100rel, precondition` → надёжный 183 → PRACK → UPDATE →
200 → ACK → BYE. Итог — «СТЕНД ГОТОВ К ТЕЛЕФОНУ» или список проблем с подсказками.

Самотест — настоящий вызов внутри `lab-sip-as`; не запускайте его одновременно с
`verify-all.sh`.

## 7. Звонок с телефона

1. `scripts/stand.sh up` — итог «СТЕНД ГОТОВ К ТЕЛЕФОНУ», gNB: `NGSetupResponse получен`.
2. Вставить SIM из партии. В телефоне: сеть только 5G (SA), VoNR включён, точка
   доступа `ims` с типом `ims`, если телефон не создал её сам.
3. В соседнем терминале — `python3 scripts/stand_check.py watch`.
4. Регистрация: в `watch` — `REGISTER` и `Contact valid` с IMSI карты;
   `stand_check.py phones` показывает карту как зарегистрированную.
5. Позвонить на 1003 (переводчик), 1004 (запись), 1005/1006 (переводчик ru/en) или на
   номер другой карты (2600–2609).

Как SIP AS отвечает штатной звонилке на номерах 1003–1006:

| Телефон прислал | SIP AS |
|---|---|
| `Require`/`Supported: 100rel` | надёжный 183 с SDP и `RSeq`, повтор до PRACK (T1 = `SIP_AS_T1_SECONDS`, до 4 с; без PRACK за 64·T1 — 504) |
| `precondition` и строки `a=curr`/`a=des` | ответ с состоянием QoS, ждёт UPDATE о готовности телефона, затем 200; без UPDATE — ответ через `SIP_AS_PRECONDITION_TIMEOUT_SECONDS` |
| UPDATE или re-INVITE с новым адресом медиа | Voice Agent получает новый адрес |
| CANCEL до ответа | 200 на CANCEL и 487 на INVITE |
| неизвестный `Require` | 420 |

P-CSCF ставит ответы AS на UPDATE через RTPengine и принимает номера вида
`tel:1003;phone-context=…`.

## 8. Если не работает

| Симптом | Что смотреть |
|---|---|
| телефон не видит сеть | `scripts/gnb.sh status` (PLMN 901/70), `tail -50 local/gnb/gnb.log`; диапазон n78 в телефоне |
| `Registration reject` в AMF | `stand_check.py`: SIM в UDR; `docker logs oai-amf | grep -i reject` |
| 5G есть, IMS нет | точка доступа `ims`; `watch`: доходит ли REGISTER; P-CSCF из SMF — `core-setup.sh check` |
| 401 по кругу в IMS | ключи SIM и PyHSS; SQN не сбрасывать |
| звонок в AI сбрасывается | `watch`: 183/PRACK/UPDATE; `docker logs --tail 50 lab-sip-as` |
| звонок без звука | `docker exec lab-rtpengine rtpengine --codecs`: AMR-WB → PCMU |
| `verify-5g`: `softmodem уже запущен` | работает gNB X310: `scripts/gnb.sh down` |

Журналы для разбора: `python3 scripts/stand_check.py collect` и
`local/verify-all/*.log`.
