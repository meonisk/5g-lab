# Матрица требований 5GS/IMS

Версия проекта: 2026-09-22, кандидат. Источники S501/S502/... определены в [профиле](3gpp-profile.md). Сценарии T00–T11 — в [приёмке](3gpp-acceptance.md). PROJECT означает наше инженерное условие, а не обязательный пункт 3GPP.

Конкретная последовательность изменений и границы пакетов — в [плане реализации](virtual-stand-plan.md).

Статусы здесь отражают доступную реализацию и пробелы, а не новые результаты: IMPLEMENTED_UNACCEPTED — код есть, нужна свежая приёмка; GAP — известный пробел; CONDITIONAL — зависит от оборудования/профиля. PARTIAL_ACCEPTED означает только выполненный инженерный поднабор: конкретные run IDs и ограничения приведены в [status](status.md). Ни одна строка не получает PASS только за наличие кода. Нормативные подпункты уточняются по D02 до standards verdict.

Активный scope — виртуальный LAB-VOICE-1. M04/Q03/E04 и физические части N05/N06/N08/E05 отложены до DEVICE-VOICE-1; это не блокирует принятие явно ограниченного LAB-профиля. I04 (защита IMS access) и поддерживаемые paging/service-request процедуры нужно исследовать на эмулированных клиентах уже сейчас.

## База, сеть и 5GS

| ID | Требование и владелец | Источник / тест | Текущее состояние | Что является доказательством |
|---|---|---|---|---|
| B01 | Inventory source/image/config + exclusive test runner | PROJECT / T00 | GAP | Commit + dirty diff hash + image IDs + effective nonsecret config + lock |
| B02 | Любой обязательный FAIL даёт ненулевой exit | PROJECT / T00 | PARTIAL_ACCEPTED: fail-closed verify и negative tests; полный T00 открыт | Fault injection делает run FAIL, а не READY |
| B03 | DNS/UE/SIP и маршруты восстанавливаются согласованно | PROJECT / T01 | PARTIAL_ACCEPTED: один UE1 IMS PDU release/re-establishment и свежий обычный REGISTER 200; полный restart matrix открыт | Перезапуск daemon и UE; новая привязка адресов и зарегистрированные клиенты |
| B04 | Исключить передачу SIP/RTP через management bridge | PROJECT / T01 | GAP при остановленном client script | Route + source IP + capture IMS path; отсутствует bypass |
| N01 | Два независимых абонента и persistent provisioning | SEC5, SECI / T02 | PARTIAL_ACCEPTED: четыре UE/domain key profiles и SQN-preserving migration; полный T02 открыт | Разные credential refs, независимый отказ, сохранение SQN |
| N02 | NG Setup и current UE registration | S502 / T02 | IMPLEMENTED_UNACCEPTED | Текущая invocation, NAS/NGAP success, согласованные IDs |
| N03 | 5GS authentication и выбранная NAS security | SEC5 / T02 | IMPLEMENTED_UNACCEPTED | Наблюдаемый Security Mode и algorithms, negative auth; UE log alone недостаточен |
| N04 | Два DNN на каждом UE без путаницы сессий | S501/S502 / T02 | IMPLEMENTED_UNACCEPTED | 4 живые session mappings, DNN/PDU IDs/IP/TUN/TEID |
| N05 | IMS DNS/P-CSCF discovery | S502/SIP / T02,T09 | CONDITIONAL: SMF p-cscf есть, PJSUA использует static env | Полученные UE параметры, DNS query/answer, используемый адрес |
| N06 | Service Request/paging для входящего вызова после idle | S502 / T02,T09 | CONDITIONAL: сначала probe UERANSIM | Клиент возвращается из idle, получает вызов; physical отдельно |
| N07 | Release/re-establishment PDU session | S502 / T01,T02 | PARTIAL_ACCEPTED: UE1 IMS PDU адрес изменён при release/re-establishment, независимые UE2 и internet session сохранены; AKA/Contact/media после смены открыты | Старые route/contact IDs не используются; новые согласованы |
| N08 | IP family/MTU соответствуют UE-профилю | S501/MEDIA / T02,T09 | CONDITIONAL: сейчас IPv4/MTU 1400 | Принятые параметры, large SIP/packetization, отсутствие MTU blackhole |

## IMS-регистрация и SIP

| ID | Требование и владелец | Источник / тест | Текущее состояние | Что является доказательством |
|---|---|---|---|---|
| I01 | IMS AKA двух UE | SECI/SIP / T03 | PARTIAL_ACCEPTED: два SIPp AKA UE и continuous call; native ISIM/SQN security открыты | Challenge с алгоритмом + проверенный response + 200 + current contact |
| I02 | Неверный ключ/identity, replay, resync | SECI / T03 | GAP в клиентах/приёмке | Ожидаемый отказ или resync; нет ложного контакта; SQN не откатывается |
| I03 | Cx authentication/assignment и корреляция | CX / T03 | PARTIAL_ACCEPTED: paired Cx + same-user MAA/SIP binding; assignment subtype открыт | Transaction/session IDs, команды, result codes, связь с регистрацией |
| I04 | Gm security agreement и состояние associations | SECI/SIP / T04 | CONDITIONAL; WITH_IPSEC не доказательство | Negotiation + state/policy + защищённый packet flow |
| I05 | Re-register, expiry, deregister и смена UE IP | SECI/SIP / T03,T04 | PARTIAL_ACCEPTED: AKA refresh, explicit dereg UE1 и passive expiry UE2 с отказом вызова старому Contact; смена IP открыта | Сначала отдельно доказать отсутствие положительного срока регистрации и отказ маршрутизации к старому Contact при живом сокете; затем физическое удаление записи по таймеру. При смене IP проверить полный состав Contact: новый REGISTER может сосуществовать со старым binding; старый удалить явным Expires:0 или дождаться его expiry, затем доказать маршрут только к новому адресу |
| I06 | Path/Service-Route и identity trust | SIP / T03,T05 | IMPLEMENTED_UNACCEPTED | Route set и originating/terminating leg; spoofed identity не принята |
| I07 | MO/MT диалог в обоих направлениях | SIP / T05 | PARTIAL_ACCEPTED: fresh continuous AKA calls в обоих направлениях | Общие Call-ID/tags/CSeq, INVITE/ответ/ACK; media отдельно |
| I08 | BYE/CANCEL и освобождение ресурсов | SIP / T06 | PARTIAL_ACCEPTED: BYE/relay removal; CANCEL/failure matrix открыта | Правильные транзакции; отсутствуют dialog/media leaks |
| I09 | Busy/unregistered/timeout/retransmission | SIP / T06 | GAP в систематической приёмке | Соответствующие причины/таймеры; нет двойных сессий |
| I10 | Session modification, reliable provisional responses и timers по выбранному профилю | SIP/NG114 / T06,T09 | CONDITIONAL | Проверены re-INVITE/UPDATE/PRACK и refresh там, где применимо |

## Media, policy и услуги

| ID | Требование и владелец | Источник / тест | Текущее состояние | Что является доказательством |
|---|---|---|---|---|
| M01 | SDP offer/answer соответствует реальному media | SIP/MEDIA / T05 | PARTIAL_ACCEPTED: PCMU/8000 SDP + negotiated receiver RTP; остальные профили открыты | Codec/PT/ports/addresses/direction до и после anchor |
| M02 | RTP в обе стороны и слышимое содержимое | MEDIA + PROJECT / T05 | PARTIAL_ACCEPTED: двусторонние receiver WAV; аудиоустройство/latency открыты | RX по каждому SSRC/leg + decoded output каждого абонента |
| M03 | RTCP, loss/jitter/DTX и отсутствие cross-call mixing | MEDIA + PROJECT / T05,T07 | Частичные unit tests | Метрики по потоку, контролируемая потеря и независимый звук |
| M04 | Phone codec и service interworking | MEDIA/NG114 / T09,T11 | GAP: PCMU-only service | Реально согласованный native codec, sound и проверенный bridge |
| Q01 | AF policy authorization | S503/POLICY / T08 | GAP: Rx/N5 отключены | Create/update/delete policy session; отказ блокирует нужный ресурс |
| Q02 | PCC→SMF→UPF правила и QFI | S501/S503 / T08 | GAP в доказательствах | Корреляция policy→PFCP PDR/FAR/QER→QoS flow |
| Q03 | Radio enforcement при конкурирующей нагрузке | S501 + PROJECT / T08,T09 | CONDITIONAL physical | QFI/DRB mapping + измерения до/после нагрузки |
| Q04 | Освобождение QoS при BYE/обрыве/отказе | S502/S503 / T08 | GAP | Удалены соответствующие associations/rules, другие звонки сохранены |
| A01 | iFC/ISC service trigger | SIP/CX / T10 | IMPLEMENTED_UNACCEPTED | Применённый профиль, AS request и связь с исходным диалогом |
| A02 | OBSERVE не ломает обычный вызов | PROJECT / T10 | Есть тест с агрегированным RTP | Оба audio outputs продолжаются при отказе AS/adapter/AI в заявленной конфигурации |
| A03 | TERMINATE корректно ведёт SIP lifecycle | SIP + PROJECT / T06,T10 | Частичная собственная SIP-реализация | Stateful response/CANCEL/BYE/retransmission сценарии |
| A04 | Translation coverage, meaning и E2E timing | PROJECT / T11 | GAP: цель 1–3 с не принята | Принимающий audio onset, общий clock, полные реплики и quality review |

## Наблюдаемость и границы результата

| ID | Требование и владелец | Источник / тест | Текущее состояние | Что является доказательством |
|---|---|---|---|---|
| E01 | Run-scoped evidence и provenance | PROJECT / T00–T11 | Частично есть | Изолированный набор, timestamps/clock uncertainty, hashes |
| E02 | Privacy-safe correlated diagrams | PROJECT / T03,T05 | GAP: перенос SigDiag | Каждая стрелка имеет evidence ref; отсутствующие данные явны |
| E03 | Separate establishment/teardown/media/security/QoS verdicts | PROJECT / все | GAP | Общий PASS только после всех обязательных проверок профиля |
| E04 | Physical UE/RF отличается от emulation | PROJECT / T09 | CONDITIONAL | HW/firmware inventory и physical capture |
| E05 | Applicable NG.114 functions не исключены молча | NG114 / D02,T09 | GAP: applicability review | Mandatory/conditional list и обоснованный scope; deferred блокирует full claim |
| E06 | Повторяемость/recovery не равна carrier SLA | PROJECT / T01,T07 | GAP | Согласованное число повторов, все результаты/отказы сохранены |

Итого: 40 требований. Это стартовая матрица выбранного профиля, не полный перечень требований всех перечисленных TS. Добавление обязательных функций по D02 расширит её.

## План реализации и зависимости

| Работа | Требования | Изменяемые места | Зависимость и результат |
|---|---|---|---|
| W0: acceptance runner | B01/B02/E01/E03 | scripts/start_lab.py, app/tests/integration, research capture | Первой; faults дают FAIL и машинный verdict |
| W1: lifecycle/network | B03/B04/N04/N07 | compose/access.yml, compose/ims.yml, sip-ue-run.sh, readiness | После W0; daemon/UE recovery принят |
| W2: subscriber identity | N01/I02 | scripts/initialize_local.py, subscribers.js, provision-ims-subscribers.sh | Перед AKA; совместимая миграция existing local data, backup и rollback |
| W3: AKA/Cx | I01/I02/I03/I05 | новый client image/fixture, CSCF/HSS profile | После W2; capability probe PyHSS до решения о замене |
| W4: signal evidence | I06/E02/E03 | capture/SigDiag adapters, structured outcomes | Параллельно концептуально W3; один физический test runner последовательно |
| W5: basic call/media | I07–I10/M01–M03/A03 | CSCF routing, SIP AS, fixtures/tests | После W1; сначала без AI, затем AS регрессия |
| W6a: virtual Gm security | I04/I05 | эмулированный IMS client, namespace IPsec, CSCF security | D04 и W3; проверяется без физического hardware |
| W6b: future device/media | N05/N06/N08/M04/E04/E05 | physical profile, interworking | Отложено пользователем; не блокирует LAB-VOICE-1 |
| W7: policy | Q01–Q04 | PCF/SMF/AF integration + tests | D06, W5; обновление версии только после capability evidence |
| W8: services | A01/A02/A04 | AS/adapter/AI и audio evidence | После принятого basic path; QoS/device claim отдельно |

W0–W5 дают сопоставимость выбранных процедур с ims c3e0d2b и более строгую приёмку существующего audio. W6a/W7 углубляют виртуальный профиль; core QoS можно исследовать без радио. W6b и radio enforcement отложены. Процент «соответствия 3GPP» по этим 40 строкам не вычислять: строки имеют разную область, а полный denominator ещё не определён.

## Принятый поднабор I05 и следующие доказательства

У AKA lifecycle оба UE прошли initial → refresh → Expires: 0 с проверкой срока
Contact и Cx challenge. Отдельный вызов после explicit dereg UE1
`aka-inactive-deregister-20260921T221955392251Z` — PASS/cleanup PASS:
Contact удалён, старый точный UDP socket оставался живым, UE2 получил 404 и
отправил соответствующий ACK, INVITE на старый socket не пришёл. Passive expiry
UE2 после исправления S-CSCF прошёл в
`aka-inactive-expire-20260921T223528557343Z`: отсутствие положительного срока
регистрации и 404/no-INVITE при живом старом socket доказали отказ
**маршрутизации** до физического удаления. Отдельное наблюдение подтвердило
**физическое удаление** записи через 264.708 с. Это две разные проверки:
задержка уборки записи не разрешает вызов по истёкшему Contact. Ранние FAIL,
включая stale-route INVITE до патча, сохраняют свои verdicts. I05 остаётся
частичным до смены UE IP и полного T03/T04.

Отдельный `pdu-recovery-20260921T225423229625Z` — PASS/cleanup PASS:
реальный release/new establishment IMS PDU UE1 сменил адрес 10.46.0.28 →
10.46.0.30, TUN и SIP process; snapshot UE2 и internet session UE1 остались
неизменными, свежий обычный REGISTER получил 200. Это узкий инкремент T01/N07:
он не доказывает замену старого Contact новым, AKA/вызов/media в той же эпохе
или PFCP wire exchange. I05 остаётся частичным.

| Следующая виртуальная проверка | Необходимое доказательство и граница |
|---|---|
| I05: смена IMS IP | В одной попытке сменить адрес/эпоху PDU у одного UE, зарегистрировать новый Contact и Path, сопоставить Cx/SIP и полный registrar inventory. Новый REGISTER сам по себе не удаляет старый Contact: явно удалить старый через Expires:0 либо дождаться expiry и подтвердить отсутствие положительного binding. Затем послать вызов при живом старом socket и показать доставку только на новый адрес; проверить rollback. Это поведение двух Linux UE namespaces, не mobility/paging физического телефона. |
| I02: replay | Повторить контролируемый старый nonce/response и неверную identity отдельно от текущего успешного UE; требовать отказа без нового Contact/Cx assignment и сохранение рабочего второго UE. Хранить в общей evidence только обезличенные идентификаторы challenge, не ключи или RAND/AUTN. Один 403 без проверки registrar и state недостаточен. |
| I02: persistent SQN и AUTS | На выделенной тестовой identity измерить SQN до/после успешной AKA, воспроизвести controlled desync, проверить AUTS/resync по SIP и HSS/Cx и монотонное состояние после рестарта клиента/HSS; отрицательный AUTS не должен менять SQN. Если закреплённый клиент или PyHSS не поддерживает flow, зафиксировать точный capability gap, не подменять его переинициализацией ключей. |
| I04: защищённый Gm | После выбора поддерживаемого механизма проверить Security-Client/Server/Verify, SPI/алгоритмы, kernel SA/policy с обеих сторон и packet capture последующего REGISTER/INVITE; неверный Verify и cleartext continuation должны отвергаться. Проверить обновление/удаление SA при re-register, dereg и IP change. Это защита эмулированного Gm; не доказывает native ISIM, радиодоступ или защиту media/core transport. |
| Q01–Q04: policy/QoS | Сначала capability probe закреплённых PCF/AF/SMF. Затем для реального SIP dialog/SDP flow связать create→update→delete и deny с policy association, PCC, SM policy, PFCP PDR/FAR/QER, QFI и освобождением на BYE/отказе; проверить оба направления и изоляцию второго звонка. Без radio QFI/DRB enforcement verdict ограничить core control/user plane; best effort, `netem` и счётчики UPF не доказывают гарантированный voice QoS. |
