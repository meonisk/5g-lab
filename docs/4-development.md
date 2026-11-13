# 4. Разработка

## Устройство репозитория

| Путь | Что там |
|---|---|
| `docker-compose.yml` | единая точка запуска; подключает `app/infrastructure/compose/ims.yml` (IMS) и `ai.yml` (AI) |
| `app/config/lab.env` | все параметры стенда: сеть, адреса, абоненты, ключи SIM, номера, модели, лимиты |
| `app/config/ai-profiles.json` | параметры режимов AI (`compact`, `minimal`, ...) |
| `app/services/sip-as/` | сервер услуг: `core/` — SIP, B2BUA, медиасервер; `services/` — модули услуг |
| `app/services/media-adapter/` | копирование звука звонка из RTPengine в AI Worker |
| `app/services/ai-worker/` | деление на фразы, распознавание, перевод, запись |
| `app/services/voice-agent/` | синтез речи и отправка звука в звонок |
| `app/services/lab_common/` | общий HTTP-код; копируется во все четыре образа |
| `app/infrastructure/` | Dockerfile инфраструктуры, DNS, сторонние конфигурации Kamailio и PyHSS (`vendor/`, правки описаны в `PROVENANCE.md`) |
| `app/tests/unit/` | быстрые тесты без Docker |
| `app/tests/integration/` | проверки работающего стенда (звонки) |
| `scripts/` | запуск, абоненты, проверки, rfsim, замеры (`profile/`), общий код (`lib/`) |
| `local/` | не в git: модели, записи, журналы, отчёты |

Где менять поведение AI Worker (`app/services/ai-worker/ims_ai/`):
`segmentation.py` — границы фраз, `utterances.py` — распознавание, `translation.py` —
перевод, `replies.py` — доставка ответа, `recording.py` — запись, `settings.py` —
параметры из `lab.env`, `runtime.py` — изменяемое состояние.

## Правила

- Перед коммитом: `python3 scripts/check.py`. Он проверяет git-индекс, размер и
  синтаксис файлов, окончания строк LF, ссылки в документации, отсутствие адресов вне
  `lab.env`, ruff и unit-тесты. Нужны пакеты из `requirements-dev.txt`.
- Не больше 300 строк кода в одном нашем файле (пустые строки и комментарии не
  считаются). Один модуль — одна задача.
- Все адреса, номера и ключи — только в `app/config/lab.env`.
- Формат звука между сервисами — PCMU 8000 Гц. Это контракт; одной переменной его не
  поменять.
- В журналы не писать IMSI и текст фраз.
- Записи, WAV, модели и отчёты в git не добавлять (каталог `local/`).
- Тексты, комментарии и сообщения — по-русски; имена переменных, файлов и параметров —
  по-английски.
- Интеграционные проверки звонят через один общий стенд: запускать строго по одной.

## Тесты

Unit-тесты (без Docker), запускаются из `check.py`:

```bash
PYTHONPATH=app/services python3 -m unittest discover -s app/tests/unit
```

Интеграционные проверки (стенд запущен; все вместе — `scripts/verify-all.sh`):

| Проверка | Что проверяет |
|---|---|
| `verify-ims.sh` | DNS, HSS, маршрут к телефонам, регистрация тестовых клиентов |
| `verify-ims-call.sh` | обычный звонок через сервер услуг; звонок не рвётся, если остановить AI |
| `verify-voice-agent.sh` | номер услуги: приветствие, звук, завершение |
| `verify-translation.sh` | 1003: русская речь → английский перевод |
| `verify-transcription.sh` | 1004: запись и расшифровка (очистка текста языковой моделью — только в `baseline`) |
| `verify_interpreter.py` | 1005/1006: перевод в обе стороны и задержка |
| `verify-services.sh` | `translate` + `record`, `*номер`, обычный звонок, отказ сервера услуг у звонящего и у вызываемого |
| `verify-isc-spike.sh` | цепочка из нескольких серверов услуг в S-CSCF |
| `verify-security.sh` | права контейнеров, токены, отсутствие личных данных в журналах |
| `verify-5g-ue.sh` | всё то же через 5G (см. [документ 3](3-5g-and-profiling.md)) |

Каждый тестовый файл начинается с описания того, что он проверяет.

## Как добавить свою услугу

Услуга — это модуль Python внутри сервера услуг `lab-sip-as`. S-CSCF отправляет туда
звонок, если в профиле абонента есть правило iFC на адрес этой услуги. Пример —
услуга `demo`, которая видит каждый новый звонок абонента, пишет его в журнал и
пропускает дальше без изменений.

1. Создайте `app/services/sip-as/ims_sip/services/demo.py`:

   ```python
   """demo AS: пишет в журнал каждый новый звонок и пропускает его дальше."""

   from ..core import proxy
   from ..core.sip import message_call_id, request_method, tag_of, value_of

   HOST = "demo.as"  # адрес услуги: sip:demo.as.<IMS_DOMAIN>


   def handle(message: str, peer: tuple[str, int]) -> None:
       # Новый звонок — INVITE без тега у получателя; повторные запросы его имеют.
       if request_method(message) == "INVITE" and not tag_of(value_of(message, "To")):
           print(f"AS demo call_id={message_call_id(message)}", flush=True)
       proxy.forward(message, peer)  # вернуть запрос в S-CSCF, дальше по цепочке
   ```

   `proxy.forward` возвращает запрос в S-CSCF, а транзакции, заголовки Via и Route
   берёт на себя `core/`. Если услуге нужно ответить самой или вмешаться в звук,
   смотрите образцы: `record.py` — пропускает звонок и действует по ответу (запись);
   `translate.py` — B2BUA (сам отвечает и делает второй звонок). Контракт модуля
   описан в `services/__init__.py`.
2. Добавьте модуль в `SERVICES` в `app/services/sip-as/ims_sip/core/dispatch.py`.
3. В `scripts/provision.py` добавьте в `SERVICES` строку `"demo": ("demo.as", 25)`.
   Число — приоритет, то есть место в цепочке услуг (сейчас translate 10, `*номер` 15,
   record 20, номера 30, SMS 40).
4. DNS не трогайте: все имена `*.as.<домен>` уже ведут на `lab-sip-as`.
5. Включите абоненту в `lab.env`: `SIPUE1_SERVICES=translate,record,demo`.
6. Примените: `python3 scripts/start.py && docker restart lab-scscf`. `start.py`
   пересобирает образ и записывает iFC в HSS; перезапуск S-CSCF сбрасывает его кэш iFC.
   Телефоны после этого регистрируются заново.
7. Тесты: unit-тест по образцу `app/tests/unit/test_sip_as_record.py`, сценарий звонка —
   в `app/tests/integration/verify-services.sh`.

## Известные ограничения

- **Отказ сервера услуг.** S-CSCF после отказа пробует следующий сервер один раз, затем
  пропускает остаток цепочки. Пока все услуги в одном контейнере, это правильно: упал
  один — упали все. Если разнести услуги по разным контейнерам, при отказе одного
  будут пропущены и живые после него. Полное решение — правка модуля Kamailio
  `ims_isc` на C.
- **Заголовок `X-Lab-ISC-Continued`.** Звонящий, подделав его, отключит только свои же
  услуги. Услуги вызываемого принимают этот заголовок только от самого S-CSCF.
- **`verify-services.sh` перезапускает S-CSCF** (сценарий 4) — регистрации телефонов
  сбрасываются. Не запускайте его во время звонков.
- **Телефон.** Не проверены: IPsec между телефоном и P-CSCF, обязательные `100rel` и
  `precondition` (сервер услуг их отклоняет), кодек EVS.
- **Задержка.** Перевод идёт по фразам: фраза + 0,7 с паузы + распознавание + перевод +
  синтез. Потоковый режим (`AI_STREAMING_ENABLED=1`) экспериментальный и выключен.

## Разработка на Windows

`python scripts/start.py` работает с Docker Desktop. Сети ядра OAI нет, её создают
вручную:

```bash
docker network create --driver bridge --subnet 192.168.70.128/26 oai-cn5g-public-net
```

Bash-проверки запускайте в Linux (WSL или контейнер с docker CLI): Git Bash подменяет
пути, и docker получает неверные пути монтирования. rfsim на Windows нет, поэтому
проверки 5G и сценарии S2, S4, S5 выполняются только на сервере.
