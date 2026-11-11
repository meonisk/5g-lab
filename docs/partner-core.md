# Ядро партнёра: что меняется под наш IMS

Стенд партнёра — стандартный docker-compose OAI CN5G в `~/oai-cn5g` (NRF, AMF, SMF,
UPF, UDR, UDM, AUSF, MySQL, ext-dn) в сети `oai-cn5g-public-net` (`192.168.70.128/26`).
В том же compose OAI поставляет демонстрационный IMS — контейнер `ims`
(`oaisoftwarealliance/ims`, адрес `.139`), и SMF по умолчанию отдаёт телефонам
именно его. Наш IMS заменяет демо: телефоны должны попадать в него.

Все изменения ядра делает один скрипт, повтор безопасен:

```bash
scripts/core-setup.sh check     # текущее состояние, ничего не меняет
scripts/core-setup.sh apply     # применить
scripts/core-setup.sh revert    # вернуть исходные файлы ядра
```

Значения берутся из [lab.env](../app/config/lab.env). Каталог ядра — `OAI_CORE_DIR`
(по умолчанию `~/oai-cn5g`), имя сервиса демо-IMS — `OAI_DEMO_IMS_SERVICE`
(по умолчанию `ims`); обе переменные задаются в окружении при запуске.

## Что меняется и зачем

| Где | Было | Стало | Зачем |
|---|---|---|---|
| `conf/config.yaml`, `upf.support_features.enable_snat` | `yes` | `no` | UPF не подменяет адрес UE: он записан в SIP и SDP, с NAT регистрация и медиа ломаются |
| `docker-compose.yaml`, `oai-upf.post_start` | — | `iptables ... -s INTERNET_UE_CIDR ! -d LAB_NETWORK_CIDR -o eth0 -j MASQUERADE` | интернет у UE остаётся через NAT, трафик в сеть ядра (IMS, ext-dn) идёт с настоящим адресом |
| `conf/config.yaml`, `smf.ims.pcscf_ipv4` | `192.168.70.139` (демо-IMS) | `PCSCF_IP` (`.166`) | телефон получает наш P-CSCF в PCO при PDU-сессии DNN `ims` |
| `conf/config.yaml`, `smf.ue_dns.primary_ipv4` | `1.1.1.1` | `DNS_IP` (`.160`) | наш DNS знает домен IMS; чужие имена пересылает на `DNS_UPSTREAM_*` |
| `docker-compose.yaml`, сервис `ims` | запускается | `profiles: ["oai-demo-ims"]`, контейнер удалён | демо-IMS не поднимается обычным `docker compose up` и не путает телефоны |

Не меняется: пулы DNN (`ims` — `10.0.9.0/24`, всего `10.0.0.0/16`), абоненты UDR,
AMF, радио. `oai-ext-dn` уже маршрутизирует `10.0.0.0/16` через UPF, поэтому без
NAT для сети ядра его проверки продолжают работать.

Перед первой правкой скрипт сохраняет `conf/config.yaml.bak-ims` и
`docker-compose.yaml.bak-ims` — исходное состояние партнёра; `revert` возвращает их и
снова поднимает демо-IMS. Применение пересоздаёт `oai-smf` и `oai-upf`
(`--force-recreate`: конфиг подключён файлом, и без пересоздания Compose правку не
заметит); PDU-сессии всех UE обрываются на несколько секунд.

## Проверка

```bash
scripts/core-setup.sh check
bash app/tests/integration/verify-ims.sh
scripts/verify-5g.sh
```

В `check`: `enable_snat: no`, `pcscf_ipv4` и `ue_dns` — наши адреса, в UPF одно
правило `MASQUERADE` и ни одного `SNAT --to-source`, контейнера `ims` нет. В
`verify-5g.sh` контакт S-CSCF — адрес туннеля UE (`10.0.9.x`), а не UPF.

Демо-IMS при необходимости запускается вручную:
`docker compose --profile oai-demo-ims up -d ims` в `~/oai-cn5g` (тогда верните и
`pcscf_ipv4`, иначе телефоны продолжат идти в наш IMS).

## Абоненты

Для настоящей SIM в UDR партнёра у абонента должен быть разрешён DNN `ims`, а IMSI,
K и OPc карты — совпадать с `UE<n>_IMSI`, `UE<n>_IMS_K`, `UE<n>_IMS_OPC` в `lab.env`
(после правки `lab.env` — `scripts/setup.sh`, он обновит PyHSS). Разрешённые DNN:

```bash
docker exec mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -E oai_db -e "SELECT ueid, dnnConfigurations FROM SessionManagementSubscriptionData"'
```

## Хост

На kopatych нет маршрута IPv6, а Python по умолчанию пробует IPv6 и не скачивает
модели с Hugging Face. Исправлено строкой в `/etc/gai.conf` (предпочитать IPv4):
`precedence ::ffff:0:0/96  100`. Это настройка машины, не репозитория.
