# 5g-lab — IMS и голосовой перевод для сети 5G

IMS-телефония и обработка речи рядом с работающим ядром **OAI CN5G**: звонки между
абонентами, перевод русского и английского, голосовой ответ, запись и расшифровка
по запросу. Распознавание, перевод и синтез речи выполняются локально.

Ядро, радиосеть и SIM-карты — ваши. Проект добавляет к ядру IMS (DNS, PyHSS,
P/I/S-CSCF, RTPengine) и AI-услуги (SIP AS, Media Adapter, AI Worker, Voice Agent,
LLM). Все контейнеры подключаются к Docker-сети ядра.

## Запуск

Linux, Docker Engine 28+ с Compose 2.33+, Python 3.11+, запущенное ядро OAI.
Перед первым запуском сверьте [app/config/lab.env](app/config/lab.env) с ядром и
внесите изменения в SMF/UPF — [туториал 1](docs/guide-1-ims-core.md).

```bash
git clone --branch partner-ims-ai https://github.com/meonisk/5g-lab.git
cd 5g-lab
scripts/core-setup.sh apply
scripts/setup.sh
scripts/verify-5g.sh
```

`core-setup.sh` один раз настраивает ядро OAI под наш IMS (NAT UPF, P-CSCF и DNS в
SMF, отключение демо-IMS OAI) — что и зачем меняется, описано в
[docs/partner-core.md](docs/partner-core.md).
Что было сделано на стенде партнёра, какие проблемы встретились и результаты
проверок — [docs/partner-integration.md](docs/partner-integration.md).

`setup.sh` один раз готовит модели перевода OPUS-MT и запускает IMS + AI в лёгком
режиме `compact` (без Qwen; режим задаёт `AI_MODE` в `lab.env`). Повторный запуск
ничего не скачивает и не перезапускает работающую IMS. `verify-5g.sh` проверяет
путь телефон → gNB → AMF/SMF/UPF → IMS → AI через OAI RF Simulator
([туториал 5](docs/guide-5-5g-scripts.md)).

Задержки через 5G (сеть, SIP, перевод по этапам): `python3 scripts/bench_5g.py`.

Режим с Qwen: `scripts/setup.sh --mode baseline`; обратно — `scripts/setup.sh`.
Только проверка конфигурации: `python3 scripts/start.py --check`.

## Документация

Три туториала — одна последовательность на одном стенде, без повторных запусков:

1. [IMS рядом с ядром OAI](docs/guide-1-ims-core.md) — подключение к ядру, запуск IMS, регистрация телефонов,
   путь одного вызова, проверка шагов 1–6, диагностика.
2. [AI поверх работающей IMS](docs/guide-2-ims-ai.md) — добавление AI, схема сервисов
   и сетей, номера услуг, режимы AI, проверка шагов 7–12.
3. [SIP-серверы и клиенты](docs/guide-3-sip.md) — CSCF, HSS, RTPengine, DNS,
   тестовые клиенты, телефон; остановка стенда.

Проверка через 5G без телефона (OAI RAN в RF Simulator) — после туториала 3:

4. [Вручную](docs/guide-4-5g-manual.md) — gNB, UE и PJSUA по шагам в нескольких
   терминалах, вызовы в переводчик, между UE и в расшифровку.
5. [Скриптами](docs/guide-5-5g-scripts.md) — тот же прогон через `rfsim.sh` и
   `verify-5g-ue.sh`, журналы, диагностика.

Устройство репозитория — [карта проекта](docs/project-layout.md), правила разработки —
[CONTRIBUTING.md](CONTRIBUTING.md), сторонние компоненты — [THIRD_PARTY.md](THIRD_PARTY.md).

Работа штатного приложения телефона и задержка перевода 1–3 секунды пока не
подтверждены. Записи разговоров и модели хранятся в `local/` и не входят в репозиторий.
