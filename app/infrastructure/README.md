# Инфраструктура: что запускается и откуда берётся

[Назад к карте app](../README.md).

## Compose — состав стенда

| Файл | Содержимое | Назначение |
| --- | --- | --- |
| [core-oai.yml](compose/core-oai.yml) | OAI NRF, UDR, UDM, AUSF, AMF, SMF, UPF и MySQL | Активное локальное ядро |
| [access.yml](compose/access.yml) | UERANSIM gNB/UE и SIP-клиенты | Эмуляция радиодоступа и абонентов |
| [ims.yml](compose/ims.yml) | DNS, PyHSS, P/I/S-CSCF, RTPengine и IMS MySQL | Регистрация и телефония |
| [ai.yml](compose/ai.yml) | SIP AS, Media Adapter, AI Worker, Voice Agent и LLM | Голосовые AI-услуги |
| [core-open5gs.yml](compose/core-open5gs.yml) | Прежнее ядро Open5GS | Сохранённая конфигурация для отката; не подключена по умолчанию |

[docker-compose.yml](../../docker-compose.yml) собирает локальный стенд из этих
разделов. [compose.partner.yml](../../compose.partner.yml) подключает только
IMS и AI. Не запускайте отдельные фрагменты как самостоятельный стенд: сети,
тома и корень относительных путей задаёт главная Compose-конфигурация.

## Остальные папки

| Папка | Что внутри |
| --- | --- |
| [configs/dns](configs/dns) | IMS DNS |
| [configs/ueransim](configs/ueransim) | Шаблоны gNB и UE |
| [configs/pyhss](configs/pyhss) | IMS-профили абонентов и услуг |
| [configs/open5gs](configs/open5gs) | Конфигурации прежнего ядра для отката |
| [images](images) | Dockerfile инфраструктурных инструментов: DNS, SIP-клиенты, S-CSCF, загрузчик LLM |
| [vendor/oai-cn5g](vendor/oai-cn5g) | SQL-схема OAI, лицензия, происхождение |
| [vendor/docker_open5gs](vendor/docker_open5gs) | Используемые upstream-конфиги IMS и сборка RTPengine; имя отражает источник |
| [vendor/kamailio-ims](vendor/kamailio-ims) | Материалы Kamailio для IMS |
| [vendor/sipp-aka](vendor/sipp-aka) | Материалы SIPp для проверки AKA |

OAI YAML генерируется [скриптом](../../scripts/oai_config.py) в `local/oai/`.
Это приватные рабочие файлы, поэтому их нет в GitLab. Публичные параметры
задаются через [config](../config/README.md), а не правкой контейнеров.

Для изменения нашей прикладной логики перейдите в [services](../services/README.md).
Порядок подключения внешнего ядра описан в [инструкции для партнёров](../../docs/partner-integration.md).
