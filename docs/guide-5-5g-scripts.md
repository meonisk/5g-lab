# Туториал 5. Проверка через 5G скриптами

Тот же прогон, что в [туториале 4](guide-4-5g-manual.md), одной командой: gNB и два UE
OAI в RF Simulator, PJSUA внутри namespace UE, вызовы через 5G в IMS и AI. Как
устроены радио, абоненты и клиент, разобрано в части 1 туториала 4; здесь — только
запуск, что делает каждый скрипт и где смотреть журналы. Стенд запущен по туториалам
[1](guide-1-ims-core.md)–[3](guide-3-sip.md), нужен собранный OAI RAN на том же хосте
и `sudo`; запускать от обычного пользователя.

# Часть 1. Команды

**1. Прогон целиком**

```bash
scripts/rfsim.sh up && bash app/tests/integration/verify-5g-ue.sh; scripts/rfsim.sh down
```

Результат через 4–5 минут:

```text
gNB: NGSetupResponse получен
UE1: 10.46.0.3
UE2: 10.46.0.4
===== 5G: PDU-сессии UE =====
PASS: UE1: туннель oaitun_ue1 (10.46.0.3) — scripts/rfsim.sh up
...
===== A: UE1 -> переводчик 1003 =====
PASS: Voice Agent: перевод озвучен полностью
PASS: UE1: получил приветствие и перевод (RX 372 > 241)
===== B: UE1 -> UE2 (1001 -> 1002) =====
PASS: UE1: звук от собеседника (RX 1100 > 500)
PASS: UE2: звук от собеседника (RX 1100 > 500)
===== C: UE2 -> расшифровка 1004 =====
PASS: AI Worker: фраза UE2 распознана
5G UE -> IMS -> AI: PASS
rfsim остановлен
```

`down` стоит после `;`, а не после `&&`: радио останавливается и тогда, когда тест
упал.

**2. По частям**

Радио можно держать поднятым и гонять тест несколько раз:

```bash
scripts/rfsim.sh up
scripts/rfsim.sh status
bash app/tests/integration/verify-5g-ue.sh
scripts/rfsim.sh down
```

`status` показывает процессы gNB/UE и адреса туннелей.

**3. Другие пути и конфигурации**

Значения по умолчанию — как на стенде партнёра. Свои задаются в `lab.env` или в
окружении:

| Переменная | По умолчанию |
|---|---|
| `OAI_RAN_DIR` | `~/openairinterface5g` |
| `OAI_RAN_CONF_DIR` | `~/projects/oai_configs` |
| `RFSIM_GNB_CONF` | `band78_20mhz.conf` |
| `RFSIM_UE_CONFS` | `ue0.conf ue1.conf` |

# Часть 2. Как устроено

**[rfsim.sh](../scripts/rfsim.sh) `up`** — шаги 1–5 туториала 4:

1. Копии конфигураций в `local/rfsim/`: адрес NG/N3 gNB заменён адресом хоста на мосту
   ядра (шлюз сети `lab-pcscf`), DNN UE — `IMS_DNN`, модели канала рядом.
2. gNB в фоне; ожидание `Received NGSetupResponse` до 30 с.
3. Параметры UE (частота, numerology, SSB) — из строки, которую печатает gNB.
4. Namespace `ue1`/`ue2` через `multi-ue.sh`, если их ещё нет.
5. UE по очереди: следующий стартует только после адреса у предыдущего, ожидание до
   двух минут на каждый.

Процессы идут в фоне с `</dev/null`, чтобы не забирать терминал. Если адреса не
дождались, скрипт завершается с ошибкой и оставляет радио работать для разбора.

**`rfsim.sh down`** — шаг 9: сначала UE по `SIGINT`, пока gNB ещё работает (UE успевают
отключиться от сети), затем gNB, через 10 с — `SIGKILL` оставшимся. Останавливаются
только процессы с копиями из `local/rfsim/`: чужой gNB на том же хосте не трогается.
Если до запуска уже работает любой softmodem, `up` отказывается стартовать.

**[verify-5g-ue.sh](../app/tests/integration/verify-5g-ue.sh)** — шаги 6–8 и тесты A–C:

- PDU-сессии: туннель у каждого UE, адрес в `IMS_UE_CIDR`, маршрут `LAB_NETWORK_CIDR` в
  туннель, ping P-CSCF;
- корень PJSUA в `local/rfsim/pjsua-root` (распаковывается один раз) и фраза с 20 с
  тишины;
- клиенты в фоне; команды консоли — через FIFO `/tmp/control-ueN` в корне вместо
  клавиатуры;
- регистрация: `REGISTER 200` и контакт `IMSI@адрес туннеля` в ответе S-CSCF;
- тест A: приветствие, `llm_reply state=sent` до 120 с, RX больше пакетов приветствия;
- тест B: оба вызова `CONFIRMED`, через 20 с RX больше 500 у обоих, BYE дошёл;
- тест C: `utterance_processed` с ненулевым `transcript_chars`.

Номера плеера и вызова для `cc`/`cd` скрипт читает из `cl`, RX — из `dq`. В конце
клиенты получают `ha` и `q`, остатки снимаются `pkill` по `chroot`.

**Журналы**

| Файл | Что в нём |
|---|---|
| `local/rfsim/gnb.log` | gNB: NG Setup, PDU Session Setup |
| `local/rfsim/ue1.log`, `ue2.log` | UE: регистрация, PDU-сессия, туннель |
| `local/rfsim/pjsua-ue1.log`, `pjsua-ue2.log` | PJSUA: SIP, `cl`, `dq` |

# Часть 3. Диагностика

**`UE1 без PDU-сессии`**

```bash
grep -E 'Registration Accept|PduSession|Establishment Accept|REJ|TUN Interface' local/rfsim/ue1.log
```

- есть `TUN Interface ... configured` — сессия есть, адрес не увидел скрипт; проверьте
  `sudo ip netns exec ue1 ip -o addr`;
- есть `ESTABLISHMENT_REJ` — сеть отказала: `docker logs --tail 2000 oai-smf`
  (`--since` у SMF ненадёжен, часы журнала могут не совпадать с часами хоста);
- после `PduSessionEstablishRequest` ничего — `grep -i pdusession local/rfsim/gnb.log`.

После разбора — `scripts/rfsim.sh down`.

**`gNB не подключился к AMF`** — `grep -E 'SCTP|errno|bind' local/rfsim/gnb.log`; если
порт занят, где-то работает другой gNB.

**`softmodem уже запущен`** — остался прошлый прогон (`scripts/rfsim.sh down`) или
работает чужой gNB: его не трогайте, договоритесь о времени.

**Терминал печатает «лесенкой»** после прерванного прогона — `stty sane`.

**Тест A медленный или `interrupted`.** Рядом с rfsim Qwen на CPU в 2–3 раза
медленнее; у `llm_reply` запас 120 с. `state=interrupted` означает, что ответ перебили:
фраза должна звучать один раз, проверьте `cc`/`cd` в `pjsua-ue1.log`.

Каталог `local/rfsim/` после прогонов можно удалить целиком:
`sudo rm -rf local/rfsim` (в `pjsua-root` есть файлы устройств от root).
