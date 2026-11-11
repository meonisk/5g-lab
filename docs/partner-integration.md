# Подключение IMS + AI к ядру партнёра: отчёт

Что сделано, чтобы наш IMS и голосовой AI работали через 5G-ядро партнёра (машина
`kopatych`, ядро OAI CN5G в `~/oai-cn5g`, стенд — `~/projects/5g-lab`, ветка
`partner-ims-ai`). Как повторить — [README](../README.md); правки ядра —
[partner-core.md](partner-core.md).

## Исходные условия

У партнёра было только ядро OAI CN5G (NRF, AMF, SMF, UPF, UDR, UDM, AUSF, MySQL,
ext-dn) в Docker-сети `oai-cn5g-public-net` (`192.168.70.128/26`). Задача: поставить
рядом наш IMS (Kamailio P/I/S-CSCF, PyHSS, RTPengine, DNS) и AI-сервисы и сделать так,
чтобы UE ходили в IMS через ядро.

## Как абоненты попадают в IMS

На стенде два вида абонентов, и это сделано намеренно:

| Абонент | Путь до P-CSCF | Зачем |
|---|---|---|
| `SIPUE1`, `SIPUE2` (`.170`, `.171`) | напрямую из сети ядра, без радио и UPF | быстрая проверка самого IMS и AI (`verify-ims.sh`) |
| `UE1`, `UE2` (rfsim) | gNB → AMF/SMF → туннель UE → UPF → P-CSCF | проверка через 5G (`verify-5g.sh`), как у настоящего телефона |

То есть замечание «sipue подключаются к IMS напрямую» верно: это тестовые клиенты.
Проверка через ядро — `scripts/verify-5g.sh`. Что трафик действительно идёт через
5G, видно по трём признакам:

- контакт абонента в S-CSCF — адрес туннеля UE из пула DNN `ims` (`10.0.9.x`), его
  выдал SMF;
- `ip route get` P-CSCF внутри namespace UE уходит в `oaitun_ue1`;
- счётчики пакетов туннеля UE растут на каждый ping и SIP-запрос
  (`scripts/bench_5g.py` проверяет это сам).

## Что изменено

В репозитории:

- `app/config/lab.env` — значения стенда партнёра: сеть `oai-cn5g-public-net`,
  адреса IMS и AI `.160`–`.172` (`.139` занят демо-IMS OAI), пулы `10.0.9.0/24` и
  `10.0.0.0/16`, `AI_MODE=compact`;
- `scripts/setup.sh` — установка одной командой (конвертер и модели перевода, затем
  запуск);
- `scripts/core-setup.sh` — настройка ядра партнёра (`check`, `apply`, `revert`);
- `scripts/verify-5g.sh` — проверка через 5G одной командой;
- `scripts/bench_5g.py` — бенчмарк задержек;
- `scripts/provision.py` — регистр ki в PyHSS приводится к `lab.env`;
- `verify-5g-ue.sh` — PJSUA с `--auto-update-nat=0`, подсказка при NAT UPF.

В ядре партнёра (`scripts/core-setup.sh apply`, подробно — [partner-core.md](partner-core.md)):
SNAT UPF выключен (NAT только в интернет через `post_start`), SMF отдаёт наш P-CSCF
`.166` и DNS `.160`, демо-IMS OAI выключен. Исходные файлы — в `*.bak-ims`.

На машине `kopatych`, вне репозитория: в `/etc/gai.conf` добавлено
`precedence ::ffff:0:0/96  100` (нет маршрута IPv6, иначе модели не скачиваются).

## Проблемы и решения

| Симптом | Причина | Решение |
|---|---|---|
| `start.py`: подсеть сети не совпадает, адреса вне `LAB_NETWORK_CIDR` | на `kopatych` был старый `lab.env` (`/24`, `.100`–`.110`) | `lab.env` из репозитория с адресами партнёра |
| P-CSCF не стартует на `.139` | адрес занят контейнером `ims` (демо-IMS OAI) | наш IMS на `.160`–`.172`, демо выключено |
| `setup.sh`: `Network is unreachable` при загрузке моделей | Python выбирал IPv6, маршрута нет | предпочтение IPv4 в `/etc/gai.conf` |
| UE через 5G: `401`, затем `403` | SNAT UPF: PJSUA посреди Digest перерегистрировался с адресом UPF | `--auto-update-nat=0`, NAT UPF только в интернет |
| `403 Authentication Failed` без NAT | ki в PyHSS строчными буквами, а Digest сравнивает строку как есть | `provision.py` приводит регистр к `lab.env` |
| Бенчмарк: переводчик молчит со второго раунда | плеер PJSUA продолжал с конца файла и слал тишину | клиент UE перезапускается перед каждым раундом |

## Результат

Проверено на `kopatych` в режиме `compact` (Whisper base, OPUS-MT, Piper):

- `bash app/tests/integration/verify-ims.sh` — PASS;
- `scripts/verify-5g.sh` — PASS: регистрация UE1/UE2 с адресом туннеля, перевод
  `1003`, вызов UE1 ↔ UE2 с аудио, расшифровка `1004`;
- `scripts/core-setup.sh check` — все значения как нужно, одно правило `MASQUERADE`.

Бенчмарк `python3 scripts/bench_5g.py --rounds 3`, 11.11.2026, медианы:

| Что | Время |
|---|---|
| RTT до P-CSCF через 5G | ~50 мс (почти всё — эмулятор радио rfsim; напрямую 0,04 мс) |
| REGISTER | 526 мс |
| INVITE UE1 → UE2 до 200 OK | 589 мс |
| INVITE в переводчик до 200 OK | 171 мс |
| конец речи → первый звук перевода | 4894 мс (3523–7309) |
| — распознавание (Whisper base) | 3556 мс (2654–5969) |
| — перевод (OPUS-MT) | 133 мс |
| — синтез (Piper) | 372 мс |

Главная задержка — распознавание: rfsim (gNB и два UE) делит CPU с AI Worker. Это
оценка на одной машине, не научное измерение.

## Открытые вопросы

- **Ускорение распознавания**: больше ядер для AI Worker (`AI_WORKER_CPU_LIMIT`,
  `AI_STT_CPU_THREADS` в профиле `compact`), пауза конца фразы
  `AI_UTTERANCE_SILENCE_MS` 700 → 500 мс, режим `minimal` или GPU.
- **Настоящий телефон**: IMS и ядро готовы. Нужны SDR и конфигурация gNB,
  программируемая SIM с IMSI/K/OPc из `lab.env` (и те же данные в UDR партнёра, DNN
  `ims`), телефон с VoNR. Не проверены IPsec между телефоном и P-CSCF, 100rel и
  preconditions, кодек EVS.
