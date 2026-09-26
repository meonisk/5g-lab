# План реализации виртуального 5GS/IMS-стенда

2026-09-21. Детализация выполнена тремя агентами `gpt-5.6-sol` и сведена в единую очередь. Активная область — два эмулированных UE, один gNB, Docker, Open5GS, Kamailio/HSS и media/services. Это план реализации с частично выполненными runtime gates; подтверждённые результаты перечислены ниже. Физическое оборудование не требуется и не выбирается.

## Карта проектных документов

| Документ | На какой вопрос отвечает |
|---|---|
| [Профиль 5GS/IMS](3gpp-profile.md) | Границы LAB-VOICE-1, standards references и открытые решения |
| [40 требований](3gpp-requirements.md) | Что проверять и чем доказывать |
| [12 сценариев](3gpp-acceptance.md) | Положительные/отрицательные стимулы и ожидаемые результаты |
| [Core/access](virtual-core-design.md) | Сессии, идентичности, маршруты, readiness/recovery |
| [IMS](virtual-ims-design.md) | AKA/Cx, SIP transactions, binding клиента и Gm security |
| [Media/policy/services](virtual-media-policy-design.md) | Двустороннее audio, policy capability, QoS и услуги |
| [Runner/evidence](virtual-evidence-design.md) | Точные verdicts, журнал попытки, capture и совместимость research |

Документы дополняют друг друга. Идентификаторы W0–W8 и B/N/I/M/Q/A/E берутся из матрицы; T00–T11 из приёмки. Номер пакета ниже — план изменения кода, не дополнительная система требований.

## Решения и альтернативы

| Решение | Принято для текущей работы | Когда пересмотреть |
|---|---|---|
| Контейнеризация | Сохранить Docker и существующие entrypoints | Только воспроизводимое ограничение возможностей |
| IMS implementation | Сохранить Kamailio P/I/S-CSCF, документировать vendor delta | Version/module incompatibility в capability probe |
| HSS | Сначала проверить pinned PyHSS AKA/Cx/resync | Конкретный отсутствующий flow/ошибка, не предпочтение названия |
| UE client | PJSUA Digest остаётся regression; отдельный continuous AKA/media client spike | SIPp не выполняет требуемый registration-bound flow |
| Данные абонентов | Раздельные credentials каждого UE; preserve runtime state/SQN | Явная тестовая ротация с backup и rollback |
| Маршруты | Network readiness управляет актуальным IMS mapping | Изменение namespace/PDU generation инвалидирует readiness |
| PCMU/8000 | Сохранить контракт AI и локального media gate | Отдельный design change; физические codecs сейчас не задача |
| Policy path | Capability-first D06, кандидат Npcf Policy Authorization | Точные pinned версии не поддерживают нужный create/update/delete chain |
| Standards verdict | Только выбранные procedures с clause mapping | Новая версия профиля; полный 3GPP/NG.114 не заявляется |

## Последовательность изменений

Каждый пакет заканчивается reviewable diff, offline checks, соответствующим acceptance и явным rollback. План не создаёт PR/commit автоматически. Протокольные и runtime изменения далее требуют последовательных live gates на выделенном стенде.

| Пакет | Конкретный результат | Приёмка | Зависимости |
|---|---|---|---|
| 01 — честный verdict | Исправить verify.sh и exact gate-ID/schema validation; изолированные negative tests | T00: network fail, missing/duplicate ID, nonzero command не дают PASS | Нет |
| 02 — durable runner | Lock, case journal, explicit interruption/timeout, sealed attempts, safe PRE/POST inventory | T00: interruption/restart/parallel runner; старый run неизменен | 01 |
| 03 — infrastructure readiness | Убрать зависимость base-ready от AI warmup; DNS/UE/SIP lifecycle и актуальные маршруты | T01: daemon/UE/DNS restart, no-bypass, generation change | 01–02 |
| 04 — безопасный provisioning | Independent keys, upsert вместо delete/insert, SQN-preserving update, migration record | T02 и повторный provisioning; UE1 fault не ломает UE2 | 02, затем maintenance window |
| 05 — baseline media | Самостоятельный обычный Digest/PCMU call без AS/AI dependency, per-leg receiver evidence и cleanup | T05–T07, оба направления и односторонний fault | 03; это сохранение базы, не AKA PASS |
| 06 — AKA capability | Клиент/HSS/CSCF на согласованном профиле; снять MD5-default для AKA-профиля, сохранив explicit regression | T03: два UE, negative auth/resync; источник protocol metadata | 04; vendor edits имеют provenance |
| 07 — continuous AKA call | Та же registration binding и client transport выполняют INVITE/SDP/audio/BYE | T03+T05+T06 в одной попытке/эпохе | 05–06 |
| 08 — protocol evidence | SigDiag adapters + exact Cx/SIP/media correlation и separate lifecycle verdict | T03/T05/T06: missing events не превращаются в success arrows | 02; уточняется во время 05–07 |
| 09 — Gm security | Эмулированный client security agreement, namespace IPsec lifecycle | T04 включая negative negotiation и address change | 06; непрерывный protected call использует 07 |
| 10 — core policy | D06 capability spike, затем выбранная AF/PCF/SMF/UPF интеграция | T08 create/update/delete/deny, flow binding и PFCP evidence | 05, 02; radio verdict отдельно |
| 11 — service regression | iFC/ISC, AS lifecycle, OBSERVE failure isolation и TERMINATE | T10 + T06, отдельно каждый failure domain | 05/08; затем повторить на 07/09 profile |
| 12 — translation acceptance | Полный принимающий audio, clock uncertainty, coverage/meaning, first and accumulated lag | T11; 1–3 с не принимать без completeness | 11; оптимизация отдельно от IMS |

Работы по чтению стандартов и схемам можно вести параллельно. Стендовые сценарии и изменения общих сетевых ресурсов — последовательно. При невозможности выполнить dependent flow сохраняется BLOCKED и точная причина; результаты соседнего профиля не подставляются.

## Три приёмочных рубежа

**Рубеж A — воспроизводимая лабораторная база:** пакеты 01–05. Доказывает, что две эмулированные линии правильно проходят сеть и обычный audio, включая восстановление и честные negative outcomes. Не AKA и не защищённый IMS profile.

**Рубеж B — сопоставимые IMS-процедуры:** 06–08 поверх A. Нужны две AKA registrations и continuous registration-bound call, коррелированные Cx/SIP, per-leg audio и завершение. Это сильнее проверки одного REGISTER или c3e0d2b signalling-only scenario, но не объявляется полным соответствием 3GPP.

**Рубеж C — углублённый виртуальный профиль:** 09–10 и применимые clauses. Gm security и core policy приняты по фактическим возможностям эмулятора; radio scheduling не заявляется. Услуги 11–12 получают отдельные verdicts, не повышают автоматически уровень сетевого соответствия.

В каждой версии профиля публикуется список применимых и непроверенных свойств. Если normative mapping ещё не готов, engineering verdict может PASS, standards verdict остаётся BLOCKED/MAPPING_PENDING. Процент «реализации всего 3GPP» не вычисляется.

## Первая рабочая итерация

Начинать с пакета 01: исправить failure accumulation `app/tests/integration/verify.sh`; добавить controlled mocks, которые воспроизводят отсутствие TUN, неуспешный ping и успешный последующий список абонентов; валидатор research должен проверять точное множество gate IDs. Не менять одновременно HSS, Kamailio и AI: иначе нельзя связать улучшение/регрессию с конкретной причиной.

После этого пакет 02 закрепляет evidence и пакет 03 восстанавливает base readiness. Прежние неудачные/исторические результаты остаются неизменными; свежий базовый run выполняется после исправлений, с новыми IDs и inventory.

## Ход реализации: 2026-09-21

Пакет 01 реализован на уровне исходников и offline regression: `verify.sh`
накапливает ошибки; validator проверяет точный набор IDs, тип exit code,
execution status и набор контейнерных логов. Исторические результаты не изменялись.

Пакет 02 выполнен частично: OS lock, append-only журнал, atomic snapshots,
тайм-аут с остановкой дерева процессов, сохранение partial results, запрет
повторного collect, PRE/POST container IDs и bounded logs с stderr.
Остаются crash reconciliation, проверка cleanup внутри контейнеров, acceptance
sidecar/assertion schema и контроль смены runtime generation. Завершение host
процесса само по себе не доказывает завершение звонка или Docker exec внутри контейнера.

Начальный Docker audit: все 30 контейнеров были остановлены. После холодного
backup Mongo/MySQL и загрузки SCTP запущены 24 base containers. Последовательно
прошли live `verify.sh` (оба UE, все четыре ping-проверки без потерь), обновлённый
`verify-ims.sh` (current TUN/source routes, DNS, NAT, Cx listener) и
`verify-ims-registration.sh` (две свежие Digest регистрации, Cx callbacks).
У UE1 IMS TUN — uesimtun0, у UE2 — uesimtun1. Это подтверждение текущей базовой
связности/регистрации, не полный T01 restart matrix, не звонок и не AKA.

Добавлен `start_lab.py --base-only` без AI fixtures/models и без обхода обязательных
base gates. Provisioning сохраняет существующие Open5GS записи и PyHSS AuC/SQN;
на этом этапе раздельные ключи ещё не были реализованы. Новый
`virtual-base-connectivity-v1.json` отделяет базовую приёмку от старого AI design.
MySQL обнаружен без persistent volume; миграция должна сохранить холодный backup
и пройти отдельную проверку перед принятием package 03/04.

MySQL migration выполнена: свежий cold backup + local rollback image + receipt,
том `mysql-data` подключён; HSS сохранил 2 IMS и 3 regular/AuC записи. После
устранения startup race и лишней gateway-проверки SIP watcher обе регистрации
повторно прошли. Controlled P-CSCF route loss дал автоматический restart SIP UE
и восстановление route, после чего network/registration gates снова PASS.
Исторические failed attempts не отменяются. DNS restart policy ещё не применена
к работающему контейнеру; full base launcher и весь T01 restart matrix не приняты.

Следующий инкремент: 94 offline tests прошли. Для пакета 04 реализованы отдельные
ключи каждого UE и домена 5GS/IMS, совместимость с legacy secrets и явный
инструмент миграции с backup/rollback и сохранением SQN. Live ключи пока legacy;
T02 и runtime миграция не приняты.

Для пакета 05 добавлен отдельный plain-call gate: временный no-AS iFC,
инвалидация S-CSCF cache, negotiated Cx readiness, fresh Digest registrations,
call-specific SIP/relay evidence, receiver WAV обоих UE и восстановление профиля.
Прямой вызов `plain-call-20260921T204551662086Z` прошёл вместе с cleanup;
оба непрерывных восьмисекундных аудиомаркера приняты. Это база Digest/PCMU,
не continuous AKA call и не закрытие всей матрицы T05–T07.
Обратный вызов и строгий negative с отключением источника UE1 тоже прошли:
подтверждены тишина у UE2, рабочее обратное audio и cleanup с регистрацией.
Текущий подтверждённый объём и ограничения: [status](status.md).

## Инкремент 2026-09-22

Пакет 04: live ротация на четыре независимых набора ключей UE/домена выполнена
с приватным backup, проверкой SQN и принадлежности AuC. Дополнительный абонент
не изменён. REST скрывает ki/opc, поэтому verifier использует read-only SQL.
Устранены mongosh optional-call ошибка и зависимость Digest-клиентов от старого
общего пароля: этот PyHSS использует IMS ki для Digest. Полный T02, включая
изоляцию ошибки ключа UE1 от UE2, ещё не принят.
После исправлений полный `start_lab.py --base-only` прошёл со всеми тремя
обязательными gates; DNS restart policy применена. Ранние неудачные старты
сохранены отдельно. Это один полный startup/restart, не вся матрица T01.

Пакет 06: [отдельный SIPp AKA image](sipp-aka-provenance.md) собран с pinned
source/patch, лицензией и binary-safe selftest. Следующий live этап — challenge,
MAR/MAA и две AKA-регистрации, затем один непрерывный registration/call endpoint.
Образ и синтетический тест сами по себе не закрывают T03.

Следующий инкремент пакета 06 выполнен: live AKAv1-MD5 регистрация обоих UE
прошла с OPc-capable SIPp. Для каждого UE подтверждены связанные UAR/MAR/SAR
и совпадение SIP challenge с его MAA-вектором; после опыта восстановлены
Digest-клиенты. Это registration gate, клиент завершается после REGISTER.
Пакет 07 (тот же endpoint от регистрации до двустороннего audio/BYE),
SQN/replay/resync и остальные negative/lifecycle cases остаются открыты.
Отрицательный bad-response gate также прошёл с Cx-корреляцией: UE1 получил
403, UE2 — 200; после опыта оба обычных клиента зарегистрированы заново.


Следующий инкремент пакета 07: `aka-call-20260921T213917277478Z` прошёл
для UE1 → UE2 вместе с cleanup. На каждом UE один SIPp process/socket выполнил
AKA REGISTER и звонок с отдельным Call-ID; Cx/SIP challenge связаны. Проверены
INVITE/ACK/BYE, IMS PDU media route, relay lifecycle и двусторонние receiver WAV
PCMU/8000. RTP helper работает отдельно в том же UE namespace. Это не физическое
воспроизведение и не SLA перевода. Первый FAIL сохранён; полные lifecycle,
negative, SQN/replay/resync, Gm и policy/QoS матрицы остаются открыты.

Обратный вызов UE2 → UE1: `aka-call-20260921T214530534792Z` — PASS,
включая cleanup. Предыдущая попытка `aka-call-20260921T214202102438Z` остаётся
FAIL: звонок и audio прошли, восстановление Digest UE2 не уложилось в 60 с
после 504. Последующий штатный retry успешен, но не меняет старый verdict.
Окно восстановления выделено в конфигурацию (90 с); причина transient 504
и полная restart matrix остаются открыты.


Инкремент lifecycle: `aka-lifecycle-20260921T220158073228Z` — PASS/cleanup PASS.
На обоих UE проверены AKA initial/refresh/Expires0, обновление expiry в S-CSCF
и физическое отсутствие Contact после удаления по таймеру. Шесть challenge
связаны с соответствующими MAA. Исправлен Digest URI клиента: теперь он
совпадает с REGISTER IMS domain; strict validator это проверяет. Две ранние
неудачные попытки сохранены. Это часть I05/T03; вызов после удаления и passive
expiry проверены ниже. Смена IP, SQN/replay/resync и Gm остаются отдельными
работами.

## I05: вызов после удаления регистрации

Explicit dereg UE1 без патча S-CSCF:
`aka-inactive-deregister-20260921T221955392251Z` — PASS/cleanup PASS.
Contact физически исчез через 86.296 с. При живом точном UDP socket старого
Contact вызов UE2 получил 404 и корректный ACK; INVITE к UE1 не доставлен,
relay session отсутствует. Ранний FAIL этого режима сохранён: harness ошибочно
применил 30-секундный предел passive expiry к 300-секундной регистрации.

Passive expiry UE2 сначала обнаружил stale-route дефект pinned S-CSCF:
истёкший Contact ещё находился в registrar, а `lookup()` переслал INVITE на
старый живой socket. Ранний FAIL не пересчитывается. После минимального guard
в отдельном [образе S-CSCF](kamailio-scscf-provenance.md) попытка
`aka-inactive-expire-20260921T223528557343Z` — PASS/cleanup PASS. Сначала
отсутствовал положительный остаток регистрации; затем UE1 получил 404/ACK,
старый socket UE2 оставался живым и не получил INVITE. Физическое удаление
Contact наблюдалось отдельно через 264.708 с. Рубеж принят в точной области:
маршрутизация к expired Contact запрещена сразу, а асинхронная уборка записи
имеет собственный bound. Это не проверяет смену IMS IP или всю T03/T04 матрицу.

Отдельное восстановление PDU `pdu-recovery-20260921T225423229625Z` прошло с
cleanup PASS: реальный release/new establishment IMS PDU UE1 сменил адрес
10.46.0.28 → 10.46.0.30, TUN и SIP process. Snapshot UE2 и internet session
UE1 не изменились; свежий обычный REGISTER получил 200. Это принятый узкий
инкремент T01/N07, не смена AKA Contact в одном непрерывном клиенте. Не
доказаны удаление старого Contact новым REGISTER, AKA/вызов/media в новой
эпохе и PFCP wire exchange. I05 остаётся частичным.

## Следующие виртуальные этапы

| Этап | Стимул и проверяемый результат | Граница результата |
|---|---|---|
| Смена IMS IP (I05/N07) | Зафиксировать полный состав Contact/Path и socket, сменить PDU/IMS IP одного UE, заново пройти AKA и Cx, сверить новый registrar binding вместе со старым. Новый REGISTER может оставить оба Contact: явно удалить старый через Expires:0 либо дождаться expiry и подтвердить отсутствие положительного binding. Вызвать UE при живом старом socket: INVITE и RTP должны идти только к новому адресу; старый Contact не может стать fallback. Повторить cleanup и rollback адреса. | Docker/UE namespace смена адреса не доказывает handover, paging или native phone behavior. |
| Replay и identity (I02) | Сохранить обезличенный challenge ID, затем повторить старый nonce/response и отдельно подменить IMPI/IMPU. Проверить SIP отказ, отсутствие нового Contact/assignment и неизменную успешную регистрацию второго UE; не выдавать один status code за полный отказ state machine. | Только тестовые credential profiles; реальные ключи, RAND/AUTN и полный Diameter payload не публиковать. |
| SQN/AUTS (I02) | На отдельной identity зафиксировать SQN до/после AKA, задать controlled desync, получить AUTS/resync, связать challenge с Cx и проверить монотонный SQN после рестарта. Неверный AUTS должен отвергаться без изменения SQN; backup/rollback не ресидят рабочие UE. | При отсутствии нужной функции pinned клиента/PyHSS записать конкретный capability gap, а не считать reset секретов resync. |
| Gm protection (I04) | Выбрать поддерживаемый security mechanism, проверить Security-Client/Server/Verify, SPI/algorithms и SA/policy UE/P-CSCF. Capture следующих REGISTER/INVITE подтверждает protected packets; неверный Verify и cleartext continuation отклоняются. При IP change/dereg проверить замену или удаление SA. | Это защита эмулированного Gm; native ISIM, radio, core Diameter/SBI и RTP protection требуют отдельных verdicts. |
| Core policy/QoS (Q01–Q04) | После capability probe AF/PCF/SMF связать SIP dialog и SDP flow с policy create/update/delete/deny, PCC, SM policy, PFCP PDR/FAR/QER и QFI. Проверить оба направления, конкурирующий второй вызов и cleanup после BYE/отказа. | При доказанных только правилах и UPF счётчиках verdict `CONTROL_PLANE_ONLY`; без radio enforcement нельзя заявить гарантированный voice QoS или QFI→DRB. |

Все новые сценарии сохраняют отдельные PASS/FAIL для регистрации, отказа
маршрутизации, физической уборки, security, media и cleanup. Ни один из этих
виртуальных этапов сам по себе не закрывает полный 3GPP/NG.114 профиль.
