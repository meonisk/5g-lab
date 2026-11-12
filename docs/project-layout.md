# Карта проекта

Пути — от корня репозитория. Команды лежат в `scripts/`, документация — в `docs/`,
код и конфигурация — в `app/`, локальные данные (записи, модели, WAV) — в
игнорируемом `local/`.

## Каталоги и файлы

- `docker-compose.yml` — единственная точка сборки: подключает `ims.yml` и `ai.yml`,
  объявляет внешнюю сеть ядра и тома.
- `app/config/lab.env` — все параметры: сеть ядра, адреса, абоненты и ключи SIM,
  номера услуг, модели, лимиты.
- `app/config/ai-profiles.json` — параметры CPU-режимов AI.
- `app/infrastructure/compose/ims.yml` — DNS, MySQL, PyHSS, P/I/S-CSCF, RTPengine и
  тестовые клиенты PJSUA (профиль `test`).
- `app/infrastructure/compose/ai.yml` — SIP AS, Media Adapter, AI Worker, LLM, Voice Agent
  и разовые init-контейнеры.
- `app/infrastructure/configs/dns/` — шаблон DNS-зоны IMS.
- `app/infrastructure/images/` — Dockerfile инфраструктуры: DNS, PJSUA, S-CSCF с патчем,
  загрузчик LLM.
- `app/infrastructure/vendor/` — сторонние конфигурации (docker_open5gs, kamailio-ims)
  с лицензией и provenance.
- `app/services/` — наши Python-сервисы: `sip-as/`, `media-adapter/`, `ai-worker/`,
  `voice-agent/` и общая HTTP-обвязка `lab_common/`.
- `app/tests/unit/` — быстрые проверки без Docker; `app/tests/integration/` — проверки
  работающего стенда; `app/tests/fixtures/` — синтетический диалог для теста перевода.
- `scripts/` — одиннадцать файлов, описаны ниже.
- `docs/` — описание правок ядра партнёра (`partner-core.md`), отчёт о подключении к ядру партнёра (`partner-integration.md`), три туториала стенда, два туториала проверки через 5G, схема `ims-ai.svg`
  и эта карта.

## Скрипты

- `core-setup.sh` — настройка ядра OAI партнёра под наш IMS (`check`, `apply`, `revert`);
  что меняется — [partner-core.md](partner-core.md).
- `setup.sh` — установка одной командой: модели OPUS-MT для CPU-режима (один раз в
  `local/`), затем `start.py`; режим — `AI_MODE` из `lab.env` или `--mode`.
- `verify-5g.sh` — `rfsim.sh up`, `verify-5g-ue.sh`, `rfsim.sh down` одной командой.
- `bench_5g.py` — бенчмарк задержек через 5G: путь через туннель, RTT 5G и напрямую,
  REGISTER/INVITE, переводчик по этапам; отчёт в `local/bench/`.
- `start.py` — проверка `lab.env` и сети ядра, запуск, абоненты, ожидание готовности;
  `--check`, `--ims-only`, `--mode baseline|balanced|compact|minimal` (по умолчанию `AI_MODE`).
- `provision.py` — абоненты в PyHSS (вызывается из `start.py`, можно отдельно).
- `prepare_translation_models.py` — однократная подготовка OPUS-MT для CPU-режимов.
- `check.py` — offline-проверки перед коммитом.
- `rfsim.sh` — gNB и два UE OAI в RF Simulator для проверки через 5G (`up`, `down`, `status`).
- `dns-ims-run.sh`, `sip-ue-run.sh` — entrypoint контейнеров DNS и PJSUA.

## Где менять поведение AI

AI Worker, `app/services/ai-worker/ims_ai/`: `settings.py` — параметры из env,
`runtime.py` — изменяемое состояние (не копируйте его через `from runtime import ...`),
`segmentation.py` — границы реплик, `queueing.py` — очередь, `utterances.py` — STT,
`translation.py` — OPUS-MT, `llm.py` — запросы к Ollama, `replies.py` — доставка ответа,
`transcription.py` и `recording.py` — запись 1004, `lifecycle.py` — хвост вызова при BYE,
`api.py` и `app.py` — HTTP и запуск потоков.

SIP AS — `app/services/sip-as/ims_sip/`: `core/` — SIP без состояния (`sip.py`),
транспорт, SDP, прокси, B2BUA (`b2bua.py`), API MRF (`mrf.py`), языки абонентов
(`subscribers.py`) и вход (`dispatch.py`); `services/` — логические AS `translate.py`,
`record.py`, `numbers.py`. Voice Agent — `app/services/voice-agent/ims_voice/`
(`calls.py` — жизнь вызова и очередь озвучки, `media.py` — RTP, `api.py` — в том числе
WAV уведомления). Media Adapter — `app/services/media-adapter/ims_media/`
(`rtpengine.py` — запросы и `play media`). Файлы `worker.py`, `server.py`, `agent.py`,
`adapter.py` — короткие точки входа. Пакет `lab_common` копируется во все четыре
образа: после его изменения пересоберите их все.

## Тесты

Каждый тест начинается с описания того, что он проверяет.

Интеграционные (`app/tests/integration/`, на работающем стенде, строго по одному;
подробно — [туториал 2](guide-2-ims-ai.md#5-проверки)):

- `verify-ims.sh` — DNS, HSS и Cx, маршрут к UE, регистрация тестовых клиентов.
- `verify-ims-call.sh` — обычный вызов, iFC → SIP AS, RTPengine, fail-open при отказе AI.
- `verify-voice-agent.sh` — номер услуги, приветствие, RTP, BYE.
- `verify-translation.sh` — 1003: русская речь → английский перевод по RTP.
- `verify-transcription.sh` — 1004: нормализация, запись WAV и расшифровки.
- `verify_interpreter.py` — 1005/1006: перевод в обе стороны и задержка.
- `verify-services.sh` — услуги профиля: translate + record, `*номер`, обычный звонок, AS остановлен.
- `verify-security.sh` — изоляция и права контейнеров, токены, журналы.
- `verify-5g-ue.sh` — абоненты UE через OAI rfsim (`scripts/rfsim.sh`): 1003, UE2↔UE1, 1004, перевод и запись UE1 → UE2, `*номер`, AS остановлен.
- `common.sh` — общий код shell-проверок (загрузка `lab.env`, PASS/FAIL, PJSUA).

Unit (`app/tests/unit/`, без Docker; запускаются из `scripts/check.py`):

- `test_start.py` — проверка `lab.env`, разбор Cx-пиров, overlay CPU-режимов.
- `test_subscriber_provisioning.py` — проверка ключей до записи, сохранение AuC.
- `test_service_api.py` — HTTP-контракты сервисов и жизненный цикл очереди озвучки.
- `test_media_routing.py` — привязка RTP к вызову в Media Adapter.
- `test_phrase_boundaries.py` — целые фразы, независимые вызовы, хвост при BYE.
- `test_phone_sdp.py` — AS не соглашается на кодек, которого не было в offer.
- `test_bench_5g.py` — разбор ping и медианы бенчмарка.
- `test_cpu_ai_profiles.py` — направления OPUS-MT, без LLM в CPU-режимах.
- `sip_fakes.py` — не тест: фейковые сокет, HTTP и потоки, построители SIP для тестов SIP AS.
- `test_ifc_generation.py` — iFC из профилей `lab.env`, приоритеты, DNS логических AS.
- `test_sip_as_numbers.py` — 1003–1006 и наблюдение обычного вызова.
- `test_sip_as_dispatch.py` — логический AS по `Route`, языки, свои диалоги.
- `test_sip_as_mrf.py` — API MRF: места, ноги, озвучка, пара, запись, уведомление.
- `test_sip_as_translate.py` — нога B через S-CSCF, 180, ответ и пара перевода.
- `test_sip_as_b2bua_teardown.py` — 486/480/408, BYE с каждой стороны, CANCEL, re-INVITE.
- `test_sip_as_translate_bypass.py` — `*номер` и звонок без перевода.
- `test_sip_as_record.py` — record AS: пометка, уведомление, запись пары перевода.
- `test_ai_pairs.py` — пары ног перевода в AI Worker.
- `test_ai_recording.py` — запись обеих сторон в один `transcript.txt`.
- `test_announcements.py` — WAV уведомления и `play media` RTPengine.

## Правила

Перед коммитом — `python3 scripts/check.py` (нужны `pip install -r requirements-dev.txt`).
Остальные правила — в [CONTRIBUTING.md](../CONTRIBUTING.md).
