# 5g-lab — IMS и голосовой перевод для сети 5G

IMS-телефония и обработка речи рядом с работающим ядром **OAI CN5G**: звонки между
абонентами, перевод русского и английского, голосовой ответ, запись и расшифровка
по запросу. Распознавание, перевод и синтез речи выполняются локально.

Ядро, радиосеть и SIM-карты — ваши. Проект добавляет к ядру IMS (DNS, PyHSS,
P/I/S-CSCF, RTPengine) и AI-услуги (SIP AS, Media Adapter, AI Worker, Voice Agent,
LLM). Все контейнеры подключаются к Docker-сети ядра.

## Запуск

Linux, Docker Engine 28+ с Compose 2.33+, Python 3.11+, запущенное ядро OAI.

```bash
git clone https://github.com/meonisk/5g-lab.git
cd 5g-lab
python3 scripts/start.py --check
python3 scripts/start.py
```

Перед первым запуском сверьте [app/config/lab.env](app/config/lab.env) с ядром и
внесите изменения в SMF/UPF — [туториал 1](docs/guide-1-ims-core.md).

## Документация

1. [IMS + AI рядом с ядром OAI](docs/guide-1-ims-core.md) — подключение, путь одного
   вызова, проверка по шагам, диагностика.
2. [IMS и AI](docs/guide-2-ims-ai.md) — схема сервисов и сетей, номера услуг, режимы
   AI, проверки.
3. [SIP-серверы и клиенты](docs/guide-3-sip.md) — CSCF, HSS, RTPengine, DNS,
   тестовые клиенты, телефон.

Устройство репозитория — [карта проекта](docs/project-layout.md), правила разработки —
[CONTRIBUTING.md](CONTRIBUTING.md), сторонние компоненты — [THIRD_PARTY.md](THIRD_PARTY.md).

Работа штатного приложения телефона и задержка перевода 1–3 секунды пока не
подтверждены. Записи разговоров и модели хранятся в `local/` и не входят в репозиторий.
