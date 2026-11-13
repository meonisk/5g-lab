# Туториал 6. Своя услуга IMS и известные ограничения

Для тех, кто развивает стенд дальше. Стенд запущен по [туториалу 2](guide-2-ims-ai.md),
как вызов попадает в AS — там же, [раздел 6](guide-2-ims-ai.md#6-как-вызов-попадает-в-ai).
Команды — из корня репозитория.

# Часть 1. Как добавить услугу

Услуга — логический AS внутри одного процесса SIP AS (`lab-sip-as`). S-CSCF включает его
по iFC абонента: правило с приоритетом указывает на `sip:<имя>.as.<IMS_DOMAIN>`, SIP AS
по хосту первого `Route` выбирает модуль. Пример ниже — услуга `demo`.

**1. Модуль услуги.** `app/services/sip-as/ims_sip/services/demo.py` объявляет
`HOST = "demo.as"` и `handle(message, peer)`. Готовые образцы:
[record.py](../app/services/sip-as/ims_sip/services/record.py) — прокси (пропускает
вызов дальше, может добавить `Record-Route` и действовать по ответу);
[translate.py](../app/services/sip-as/ims_sip/services/translate.py) — B2BUA (сам
отвечает звонящему и создаёт свою ногу B). Транзакции, Via, Route и MRF делает `core/`,
контракт модуля — в [services/\_\_init\_\_.py](../app/services/sip-as/ims_sip/services/__init__.py).
В журналы — только Call-ID и метаданные: без IMSI и текста реплик.

**2. Регистрация в SIP AS.** Добавьте модуль в `SERVICES` в
[core/dispatch.py](../app/services/sip-as/ims_sip/core/dispatch.py).

**3. Правило iFC.** В [scripts/provision.py](../scripts/provision.py) добавьте в
`SERVICES` строку `"demo": ("demo.as", 25)`. Приоритет задаёт место в цепочке: сейчас
translate 10, `*номер` 15, record 20, numbers 30, SMS 40. Порядок важен: нога B
translate идёт по цепочке дальше и проходит все AS с большим приоритетом. Правила
`provision.py` — для исходящих вызовов абонента (`SessionCase 0`); правило для
входящих (`SessionCase 1`) собирается так же, образец —
[term_ifc.py](../app/tests/integration/term_ifc.py).

**4. DNS не трогать.** `address=/as.<IMS_DOMAIN>/` в
[ims-dnsmasq.conf](../app/infrastructure/configs/dns/ims-dnsmasq.conf) отвечает за все
имена `*.as.<IMS_DOMAIN>`, и `demo.as` попадает на SIP AS сам.

**5. Включить абоненту.** В `app/config/lab.env`: `SIPUE1_SERVICES=translate,record,demo`.
Неизвестное имя `provision.py` отвергнет до обращения к HSS.

**6. Применить.** Код SIP AS вшит в образ, iFC S-CSCF читает только при регистрации:

```bash
python3 scripts/start.py
docker restart lab-scscf
```

`start.py` пересобирает образы и записывает iFC в PyHSS; рестарт S-CSCF сбрасывает
кэш iFC. Клиенты и телефоны после этого регистрируются заново.

**7. Тесты.** Unit-тест модуля — по образцу `app/tests/unit/test_sip_as_record.py` на
фейках `sip_fakes.py`; сценарий вызова — в `app/tests/integration/verify-services.sh`.
Перед коммитом — `python3 scripts/check.py`.

# Часть 2. Известные ограничения

**Отказ AS (DefaultHandling 0).** S-CSCF ждёт каждый AS до 5 с (`isc_fr_timeout`), при
отказе пробует следующий AS цепочки один раз, после второго отказа пропускает остаток
цепочки и соединяет вызов. Так и для звонящего, и для вызываемого. Причина — модуль
`ims_isc`: в failure route он всегда берёт позицию цепочки из исходного запроса.
Пока все логические AS в одном `lab-sip-as`, это верно (упал один — упали все). Если
разнести AS по контейнерам, при отказе одного будут пропущены и живые AS после него;
полное решение — правка `ims_isc` на C.

**Заголовок `X-Lab-ISC-Continued`.** Расширение стенда, не 3GPP: им S-CSCF помечает
продолжение вызова после отказа AS. Подделав его, звонящий отключит только свои
услуги; услуги вызываемого метку принимают только от самого S-CSCF. Подробности —
[PROVENANCE.md](../app/infrastructure/vendor/docker_open5gs/PROVENANCE.md).

**AI — только через `start.py`.** Режим AI (`AI_MODE`, например compact) применяет
`scripts/start.py`. Поднятый в обход AI Worker не стартует и пишет в журнал
`AI startup_refused` с подсказкой.

**Тест услуг перезапускает S-CSCF.** Сценарий 4 `verify-services.sh` дважды делает
`docker restart lab-scscf`: регистрации телефонов сбрасываются. Не запускайте его во
время звонков с телефонов.

**Звук внутри AI — PCMU/8000.** Это контракт между сервисами, одной переменной его не
поменять.

**Разработка на Windows.** `scripts/start.py` работает с Docker Desktop; сеть ядра без
OAI создаётся вручную: `docker network create --subnet <LAB_NETWORK_CIDR> <CORE_NETWORK_NAME>`.
Bash-тесты запускайте в Linux (WSL или контейнер с docker CLI): Git Bash подменяет пути,
и docker получает неверные пути монтирования.
