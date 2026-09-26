# Проект виртуального IMS

Состояние: **проект реализации, не приёмка**, 2026-09-21. Область — виртуальные LAB-VOICE-1 и SERVICE-VOICE-1 из [профиля](3gpp-profile.md), [матрицы](3gpp-requirements.md) и [сценариев](3gpp-acceptance.md). Физические UE/RF сейчас не требуются. Версии, применимость и пункты 3GPP замораживаются по D02/D04 до нормативного verdict. W0/W4 и общий формат доказательств описаны в [проекте evidence](virtual-evidence-design.md). Этот текст не объявляет соответствие конкретному пункту стандарта.

## Текущая граница и целевой сценарий

[Access Compose](../app/infrastructure/compose/access.yml) запускает два PJSUA-клиента в UE namespaces с Digest-паролем. [Регистрационный тест](../app/tests/integration/verify-ims-registration.sh) проверяет `200/REGISTER` в их выводе: это регрессия, не доказательство AKA, Cx, живого Contact, media либо Gm security. В [S-CSCF `route[REGISTER]`](../app/infrastructure/vendor/docker_open5gs/scscf/kamailio_scscf.cfg) MD5 подставляется **только если `$aa` пуст**. При выключенном `WITH_AUTH` вызов `ims_www_authenticate` также ограничен условием `$avp(alg) == "MD5"`. Поэтому проверить фактически собранный конфиг и AKA wire flow; это не безусловный запрет AKA. [P-CSCF](../app/infrastructure/vendor/docker_open5gs/pcscf/pcscf.cfg) имеет `WITH_IPSEC`, но само наличие define не доказывает защищённый сеанс. Соседний `../ims` содержит [патч SIPp AKA](https://git.miem.hse.ru/2508/ims/-/blob/c3e0d2bf846dc9077c8d7f0f98488d0b099cf8be/patches/sipp-3.7.7-aka-binary-safe-v3.patch) и [заметки развёртывания](https://git.miem.hse.ru/2508/ims/-/blob/c3e0d2bf846dc9077c8d7f0f98488d0b099cf8be/docs/operations/phase4-ims-deployment.md); это кандидаты с отдельной provenance, а не готовый результат для данного стенда.

Цепочка для **каждого** независимо provisioned UE: IMS PDU address и найденный P-CSCF → начальный REGISTER → 401 AKA challenge → авторизованный REGISTER → 200 и актуальный binding → INVITE/SDP тем же endpoint и identity → ACK → различимый звук, принятый в обоих RTP направлениях → BYE/200 → отсутствие старого dialog/media state. Выполнить A→B и B→A. SIPp AKA REGISTER вместе с отдельным PJSUA Digest call — два опыта, не один AKA voice-сеанс.

## W3: AKA, Cx и непрерывный клиент

Инкремент 2026-09-22: подготовлен отдельный [SIPp AKA image](sipp-aka-provenance.md)
с pinned source/patch и синтетическим binary-safe тестом. Сборка и version smoke
прошли; live AKA/Cx и continuous media ещё не проверены. В текущем S-CSCF уже
включён `WITH_AUTH`; сначала наблюдать реальный challenge, а не менять switches.
На время такого опыта остановить Digest-клиенты: лимит одного Contact с overwrite
позволяет их регистрации вытеснить binding AKA-клиента.

Продолжение того же дня: добавлен явный OPc-path с Milenage vectors; live gate
`verify_aka_registration.py` подтвердил обе AKA-регистрации и связанный Cx,
включая fingerprint SIP 401 nonce ↔ MAA RAND/AUTN. Свежие результаты и границы
перечислены в [status](status.md); это ещё не непрерывный AKA/media клиент.

1. До изменения БД инвентаризировать PyHSS schema/provisioner. Для обоих UE сопоставить IMPI/IMPU с разными key/OPc/SQN, auth scheme, связанными строками и iFC; предусмотреть backup/rollback. Секреты хранить только в игнорируемом каталоге. Отдельной тестовой identity проверить выдачу векторов, AUTS/resync, сохранение SQN и Diameter results; менять HSS только при воспроизводимом ограничении.
2. Закрепить SIPp source/version, patch, checksum, license и image digest. Синтетическими векторами проверить собранный AKA algorithm и binary-safe challenge parsing. **Одним процессом/сценарием на UE** пройти REGISTER, поддерживаемый Contact, INVITE/answer либо originate, SDP, отправку RTP **и RX capture**, ACK и BYE. Подтвердить путь от UE IMS PDU через UPF, без management bridge. [Документация SIPp media](https://sipp.readthedocs.io/en/latest/media.html) описывает playback; приём и stateful поведение выбранной сборки ещё надо доказать.
3. Если SIPp не держит вместе регистрацию, dialog и media, записать точный провал capability probe и выбрать/реализовать stateful IMS-клиент. PJSUA/Digest сохранить отдельно. Не снижать требование AKA и принимаемого аудио ради инструмента.
4. Сопоставить два REGISTER по Call-ID, CSeq, algorithm, обезличенному nonce ID, IMPI/IMPU, Contact/expiry, Cx Session-Id/result. Наблюдать UAR/UAA, MAR/MAA, SAR/SAA **там, где реально применимы**; callback без wire IDs не доказывает весь Diameter exchange. Negative cases: неизвестная identity, неверный key, replay/stale response, SQN desync и AUTS recovery при поддержке, expiry, re-register, deregister, смена IMS IP.

Поведение `ims_auth`/HSS проверять на закреплённой сборке. [Документация Kamailio](https://www.kamailio.org/docs/modules/stable/modules/ims_auth.html) описывает Cx-зависимость, но не доказывает выполнение процедуры в стенде. Frozen profile указывает реально согласованный алгоритм: `MD5`, `AKAv1-MD5`, `AKAv2-MD5` не взаимозаменяемы.

## W5: маршруты, identity, dialog и media

P-CSCF остаётся UE ingress и управляет media anchoring; сами RTP-пакеты передаёт RTPengine. I-CSCF/HSS участвуют в применимых регистрационных и routing-процедурах, а не обязательно в каждом in-dialog сообщении; S-CSCF выполняет routing/iFC. Проверить, что Path из REGISTER достиг registrar, Service-Route из успешной регистрации стал originating route set клиента, terminating request пришёл к текущему Contact через сохранённый Path. Record-Route задаёт маршрут in-dialog запросов (ACK/BYE) и не заменяет регистрационный Path: [RFC 3327](https://www.rfc-editor.org/rfc/rfc3327.html), [RFC 3608](https://www.rfc-editor.org/rfc/rfc3608.html). Снять реальные route sets после refresh, expiry, deregistration и смены IMS IP.

Network asserted identity доверен только после принятой регистрации и внутри доверенной сетевой границы. P-CSCF удаляет/проверяет UE-supplied P-Asserted-Identity; S-CSCF выводит identity из served-user binding. Проверить spoofed From/P-Preferred/P-Asserted и незарегистрированного отправителя. Одного правила в [P-CSCF originating route](../app/infrastructure/vendor/docker_open5gs/pcscf/route/mo.cfg) и [S-CSCF route](../app/infrastructure/vendor/docker_open5gs/scscf/kamailio_scscf.cfg) недостаточно: нужен trace.

Обычный звонок проходит без AI. Проверить offer/answer PT/codec/ports, два разных принятых синтетических сигнала, sequence/timestamps/SSRC каждого RTP leg и удаление его RTPengine session. PCMU/8000 — текущий регрессионный media contract; нормативные кодеки ждут D02. INVITE 200 без ACK и RX audio — лишь частичное signalling evidence.

Собственный [SIP AS router](../app/services/sip-as/ims_sip/routing.py) хранит состояние по branch/Call-ID, создаёт agent call до 200 и отправляет CANCEL в тот же cleanup, что BYE. При победе CANCEL здесь не видно final response исходной INVITE transaction. `route_response` не удаляет transaction entries; нужны bounded timers и политика retransmit/late response. [messages.py](../app/services/sip-as/ims_sip/messages.py) копирует Record-Route в local response; полученный route set проверить. Реализация должна различать transaction key (top Via branch + method + sent-by) и dialog key (Call-ID + local/remote tags), управлять переходами/timers и идемпотентно освобождать resources. Один Call-ID не различает forks/early dialogs. Проверки: повтор INVITE, CANCEL до final, гонка CANCEL/200, поздний ACK, потеря 200/ACK, busy/unregistered/no response, BYE обеих сторон, re-INVITE/hold-resume при применимости. 200 на CANCEL не означает, что INVITE отменён: [RFC 3261](https://www.rfc-editor.org/rfc/rfc3261.html), [RFC 5407](https://www.rfc-editor.org/rfc/rfc5407.html). Ожидаемые исходы закрепить до реализации.

## W6a: виртуальная защита Gm

D04 выбирает Gm security mechanism и параметры, поддерживаемые **эмулированным** IMS-клиентом. Linux namespaces позволяют создать client-side associations без телефона. Capability probe: согласовать Security-Client/Server/Verify, адреса/порты/SPI/algorithms; проверить kernel policies/associations UE и P-CSCF; захватом доказать защищённый путь последующих SIP; отклонить неверный Security-Verify и запрещённое cleartext-продолжение. Повторить после re-register, expiry, deregister и смены IMS IP, подтвердив замену/удаление associations. [Kamailio IPsec module](https://kamailio.org/docs/modules/devel/modules/ims_ipsec_pcscf.html) показывает доступные средства, но `WITH_IPSEC` или SA counter не являются приёмкой. Core Diameter/SBI transport и media protection получают отдельные verdict. Совместимость будущего телефона — другая D04/device задача.

## Карта реализации и gates

| Работа | Кандидатные файлы | Gate |
| --- | --- | --- |
| W3 subscriber/auth | `scripts/initialize_local.py`, IMS provisioner, `app/infrastructure/vendor/docker_open5gs/{pyhss,scscf,icscf}/`, новый pinned client image/fixtures | T03: wire AKA/Cx, живой binding, negatives, отсутствие ключей в отчёте |
| W5 call/AS | `app/infrastructure/vendor/docker_open5gs/{pcscf,scscf}/route/`, `app/services/sip-as/ims_sip/{routing,messages,runtime}.py`, `app/tests/integration/` | T05/T06: оба направления/service modes, RX audio, transaction faults, cleanup |
| W6a Gm | client image/namespace setup, `app/infrastructure/vendor/docker_open5gs/pcscf/`, `app/tests/integration/` | T04: negotiation, protected packets, negatives, association lifecycle |

Это места для анализа, не разрешение править vendor без причины/provenance. Собственные файлы соблюдают лимит 300 логических строк; vendor patch документируется отдельно. Перед review — `python scripts/quality/check.py`; live gates проводить по одному в ходе реализации. Сохранять profile revision, builds/patches, обезличенные SIP/Cx/SDP/media observations, route proof и verdict по [T00–T06](3gpp-acceptance.md) и [W0/W4 evidence contract](virtual-evidence-design.md). Отсутствующий capture либо разделённый AKA/Digest тест дают BLOCKED/NOT_TESTED, не PASS.
