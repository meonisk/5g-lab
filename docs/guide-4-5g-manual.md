# Туториал 4. Проверка через 5G вручную

Стенд запущен по туториалам [1](guide-1-ims-core.md)–[3](guide-3-sip.md): ядро OAI
работает, IMS и AI подняты. Тестовые клиенты из туториала 3 стоят в сети ядра и 5G не
проходят. Здесь вызовы идут как у телефона: SIM регистрируется в 5G, получает
PDU-сессию DNN `IMS_DNN`, и только через gNB и UPF доходит до P-CSCF. Всё делается
руками в нескольких терминалах, чтобы видеть каждое звено. Те же шаги одной командой —
[туториал 5](guide-5-5g-scripts.md).

Нужен собранный OAI RAN (`nr-softmodem`, `nr-uesoftmodem`) на том же хосте и `sudo`;
запускать от обычного пользователя. Конфигурации ядра, OAI RAN и исходные
конфигурации gNB/UE не меняются: всё, что создаётся, лежит в `local/manual/`.

# Часть 1. Как устроено

**Радио.** gNB и два UE работают в режиме RF Simulator: радио заменено обменом
отсчётами по TCP, gNB — сервер. Каждый UE сидит в своём network namespace (`ue1`,
`ue2`), который создаёт скрипт OAI `multi-ue.sh`; из namespace `ueN` сервер rfsim виден
по адресу `10.(200+N).1.100`. После PDU-сессии в namespace появляется туннель
`oaitun_ue1` — у обоих UE с одним именем, потому что номер UE внутри своего процесса
всегда нулевой.

**Абоненты 5G.** UE1 и UE2 — SIM из конфигураций партнёра `ue0.conf` и `ue1.conf`
(IMSI, K, OPc), они уже заведены в UDR ядра. В `lab.env` те же значения записаны в
`UE1_*`/`UE2_*`. Отличие от исходного запуска одно: в копии конфигурации DNN `ims`
вместо `oai`; DNN `ims` и его пул `IMS_UE_CIDR` настроены в SMF.

**Абоненты IMS.** `start.py` через `provision.py` заводит UE1/UE2 в PyHSS стенда: те же
IMSI, номера `UE1_MSISDN`/`UE2_MSISDN`, пароль `UE{n}_IMS_K`. Это база стенда, не ядра.

**SIP-клиент.** Тот же `pjsua`, что у тестовых клиентов, но без Docker: Docker не
умеет запускать контейнер в чужом namespace. Файловая система образа `lab-pjsua`
распаковывается в каталог, и `pjsua` запускается через `ip netns exec ueN chroot`.
Единственный выход в сеть у него — туннель, то есть 5G. Регистрация — SIP Digest
(`IMSI@IMS_DOMAIN`, пароль `UE{n}_IMS_K`), поэтому IMS AKA и IPsec проверит только
настоящий телефон. Звук — короткая фраза `espeak-ng` из того же каталога.

# Часть 2. Команды

Понадобится шесть терминалов: gNB, UE1, UE2, PJSUA UE1, PJSUA UE2 и терминал проверок.
Каждый новый терминал начинайте с одних и тех же переменных (пути — как на стенде
партнёра; если у вас другие, поправьте `RAN` и `CONFS`):

```bash
cd ~/projects/5g-lab && set -a && source app/config/lab.env && set +a
RAN=~/openairinterface5g; CONFS=~/projects/oai_configs; W=$PWD/local/manual
BUILD=$RAN/cmake_targets/ran_build/build; J=$W/pjsua-root
```

**1. Копии конфигураций** (терминал проверок, один раз)

В конфигурации gNB адрес NG/N3 — адрес контейнера gNB, которого на хосте нет: копия
получает адрес хоста на мосту ядра, иначе gNB падает с `errno 99`. UE получают DNN
`IMS_DNN`. Модели канала копируются рядом: `@include` OAI ищет файл в каталоге
конфигурации.

```bash
mkdir -p $W && cp $CONFS/channelmod_rfsimu*.conf $W/
HOST=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.Gateway}}/{{.IPPrefixLen}}{{end}}' lab-pcscf)
sed -E "s#(GNB_IPV4_ADDRESS_FOR_(NG_AMF|NGU)) *= *\"[^\"]*\"#\1 = \"$HOST\"#" $CONFS/band78_20mhz.conf >$W/gnb.conf
sed -E "s/dnn *= *\"[^\"]*\"/dnn = \"$IMS_DNN\"/" $CONFS/ue0.conf >$W/ue1.conf
sed -E "s/dnn *= *\"[^\"]*\"/dnn = \"$IMS_DNN\"/" $CONFS/ue1.conf >$W/ue2.conf
grep -E 'GNB_IPV4_ADDRESS_FOR_(NG_AMF|NGU)' $W/gnb.conf; grep dnn $W/ue[12].conf
```

Результат: в `gnb.conf` адрес хоста (например, `192.168.70.1/24`), в обоих UE —
`dnn = "ims"`.

**2. Namespace UE** (терминал проверок, один раз после загрузки хоста)

```bash
sudo ip netns list | grep -qw ue1 || sudo $RAN/tools/scripts/multi-ue.sh -c1
sudo ip netns list | grep -qw ue2 || sudo $RAN/tools/scripts/multi-ue.sh -c2
```

**3. gNB** (терминал gNB)

Кавычки вокруг `[0]` обязательны: без них bash принимает скобки за шаблон имени файла.

```bash
sudo RFSIMULATOR=server $BUILD/nr-softmodem -O $W/gnb.conf --continuous-tx --rfsim \
  '--rfsimulator.[0].options' chanmod --channelmod.modellist modellist_rfsimu_1
```

Результат: `Received NGSetupResponse from AMF` и строка
`Command line parameters for OAI UE: -C 3550080000 -r 51 --numerology 1 --ssb 186 --band 78`.
Если параметры у вас другие, подставьте свои в шаги 4 и 5.

**4. UE1** (терминал UE1)

```bash
sudo ip netns exec ue1 $BUILD/nr-uesoftmodem -O $W/ue1.conf --rfsim \
  -C 3550080000 -r 51 --numerology 1 --ssb 186 --band 78 \
  '--rfsimulator.[0].options' chanmod --channelmod.modellist modellist_rfsimu_1 \
  '--rfsimulator.[0].serveraddr' 10.201.1.100
```

Результат через 30–120 с: `Received Registration Accept`, затем
`Received PDU Session Establishment Accept, UE IPv4: 10.46.0.x` и
`TUN Interface oaitun_ue1 successfully configured`. Запускайте UE2 только после этой
строки: при одновременном входе нагруженный gNB не успевает обслужить оба UE.

**5. UE2** (терминал UE2) — своя конфигурация и свой адрес сервера:

```bash
sudo ip netns exec ue2 $BUILD/nr-uesoftmodem -O $W/ue2.conf --rfsim \
  -C 3550080000 -r 51 --numerology 1 --ssb 186 --band 78 \
  '--rfsimulator.[0].options' chanmod --channelmod.modellist modellist_rfsimu_1 \
  '--rfsimulator.[0].serveraddr' 10.202.1.100
```

**6. Туннели и маршрут** (терминал проверок)

Сеть стенда `LAB_NETWORK_CIDR` направляется в туннель, иначе SIP и RTP ушли бы в обход
5G через veth.

```bash
for n in 1 2; do
  sudo ip netns exec ue$n ip -4 -o addr show oaitun_ue1
  sudo ip netns exec ue$n ip route replace $LAB_NETWORK_CIDR dev oaitun_ue1
  sudo ip netns exec ue$n ping -c2 -W3 $PCSCF_IP
done
```

Результат: у каждого UE адрес из `IMS_UE_CIDR`, P-CSCF отвечает на ping.

**7. Корень PJSUA и фраза** (терминал проверок, один раз)

Фраза короткая: длинная режется пределом реплики AI Worker (5 с), а не паузой.

```bash
sudo mkdir -p $J && docker create --name pjsua-export lab-pjsua >/dev/null
docker export pjsua-export | sudo tar -x -C $J; docker rm pjsua-export
for d in 'null 3' 'random 8' 'urandom 9'; do set -- $d; sudo rm -f $J/dev/$1; sudo mknod -m 666 $J/dev/$1 c 1 $2; done
sudo chroot $J espeak-ng -v $TTS_VOICE -s $TTS_RATE -w /tmp/phrase.wav 'Добрый день. Как у вас дела?'
```

**8. PJSUA UE1 и UE2** (терминалы PJSUA)

Клиент работает интерактивно: команды консоли вводятся прямо в его терминал. Для UE2
замените `ue1`, `UE1_IMSI` и `UE1_IMS_K` на `ue2`, `UE2_IMSI` и `UE2_IMS_K`.

```bash
IP=$(sudo ip netns exec ue1 ip -4 -o addr show oaitun_ue1 | awk '{print $4}' | cut -d/ -f1)
sudo ip netns exec ue1 chroot $J pjsua --log-level=3 --app-log-level=4 --null-audio --no-tcp --no-vad \
  --clock-rate=8000 --snd-clock-rate=8000 --dis-codec='*' --add-codec=$SIP_UE_CODEC \
  --auto-answer=200 --play-file=/tmp/phrase.wav \
  --id sip:$UE1_IMSI@$IMS_DOMAIN --registrar sip:$IMS_DOMAIN \
  --proxy "sip:$PCSCF_IP:$PCSCF_SIP_PORT;transport=udp;lr" --realm $IMS_DOMAIN \
  --username $UE1_IMSI@$IMS_DOMAIN --password $UE1_IMS_K --ip-addr=$IP --bound-addr=$IP
```

Результат: `registration success, status=200 (OK)`. `--no-vad` нужен, чтобы тишина
тоже шла в RTP и счётчики пакетов не зависели от длины фразы.

Команды консоли PJSUA:

- `m` — вызов, затем адрес;
- `cl` — порты конференц-моста: плеер — строка с `phrase.wav`, вызов — строка с `sip:`;
- `cc` — соединить порты, затем номер источника и номер приёмника; `cd` — разъединить;
- `dq` — качество текущего вызова, строка `RX ... pkt`;
- `h` — положить трубку, `q` — выход.

Плеер сам в вызов не подключается, а подключённый играет фразу по кругу. Поэтому
фразу подают `cc` (плеер → вызов) и снимают `cd` с теми же номерами через 3–4 с:
повтор перебил бы ответ агента.

**Тест A. UE1 → переводчик** (`VOICE_TRANSLATOR_MSISDN`, у нас 1003)

В терминале проверок:

```bash
docker logs -f --since 1m lab-voice-agent 2>&1 | grep --line-buffered -E 'reason='
```

В PJSUA UE1: `m`, затем `sip:1003@<IMS_DOMAIN>`. После `reason=greeting state=sent` —
`cl`, `cc`, через 4 с `cd`. Результат: `reason=llm_reply state=sent`; рядом с rfsim
перевод занимает 20–60 с. Затем `dq`: RX больше `packets=` из строки приветствия —
значит, до UE дошёл и перевод. `h`.

**Тест B. UE1 → UE2** (`UE2_MSISDN`, у нас 1002)

В PJSUA UE1: `m`, `sip:1002@<IMS_DOMAIN>`. UE2 отвечает сам (`--auto-answer`), в обоих
терминалах `state changed to CONFIRMED`. На каждой стороне `cl` и `cc` (плеер → вызов),
через 20 с `dq` на обеих. Результат: RX больше 500 пакетов (20 с при ptime 20 мс —
около 1000). `h` в UE1; у UE2 — `DISCONNECTED`, BYE дошёл.

**Тест C. UE2 → расшифровка** (`VOICE_TRANSCRIBER_MSISDN`, у нас 1004)

В терминале проверок:

```bash
docker logs -f --since 1m lab-ai-worker 2>&1 | grep --line-buffered utterance_processed
```

В PJSUA UE2: `m`, `sip:1004@<IMS_DOMAIN>`, через 6 с `cl`, `cc`, через 4 с `cd`.
Результат: `utterance_processed` с `transcript_chars` больше нуля. `h`.

**9. Остановка**

Порядок важен: UE отключаются от сети, пока gNB ещё работает, иначе SMF держит старую
PDU-сессию.

1. В обоих терминалах PJSUA — `q`.
2. В терминалах UE2 и UE1 — `Ctrl+C`; в журнале `Received NAS_DEREGISTRATION_REQ`.
3. В терминале gNB — `Ctrl+C`.
4. Если терминал после этого печатает «лесенкой» — `stty sane`.

Namespace `ue1`/`ue2` живут до перезагрузки хоста и не мешают; убрать раньше —
`sudo $RAN/tools/scripts/multi-ue.sh -d1 -d2`. Каталог `local/manual` после прогона
можно удалить: `sudo rm -rf local/manual` (в корне PJSUA есть файлы устройств от root).

# Часть 3. Диагностика

**Нагрузка.** gNB и UE заметно грузят процессор: Qwen на 8 ядрах без GPU отвечает в
2–3 раза медленнее, RTP иногда приходит пачками (jitter до нескольких секунд). На
настоящем радио этого нет.

**У UE нет адреса.** Сначала журнал UE, а не ядро:

- есть `Establishment Accept` и `TUN Interface ... configured` — сессия есть, проверьте
  `sudo ip netns exec ue1 ip -o addr`;
- есть `ESTABLISHMENT_REJ` — сеть отказала, причину ищите в
  `docker logs --tail 2000 oai-smf`. У SMF часы журнала могут не совпадать с часами
  хоста, поэтому `--since` у него ненадёжен — берите `--tail`;
- после `PduSessionEstablishRequest` ничего — дошёл ли запрос до gNB, видно по строкам
  `PDU Session` в его терминале. Замолчавший SMF лечится перезапуском его контейнера;
  это ядро, поэтому только с ведома владельца.

**gNB: `errno 99`** — в копии остался адрес контейнера; повторите шаг 1. **UE: `No USRP
device found`** — забыт `--rfsim`. **UE: ошибка `@include`** — модели канала не
скопированы рядом с конфигурацией.

**Нет `registration success`.** Проверьте ping P-CSCF из шага 6 и абонента в PyHSS:
`curl -s http://127.0.0.1:8088/ims_subscriber/list | grep -c "$UE1_IMSI"`.
