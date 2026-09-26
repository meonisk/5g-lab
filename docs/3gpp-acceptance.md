# Сценарии приёмки 5GS/IMS

Состояние: **спецификация тестов, не реализованный новый runner**. Идентификаторы соответствуют [матрице](3gpp-requirements.md). Целевой scope и источники — в [профиле](3gpp-profile.md).

Исполнение, versioned sidecar, журнал попытки и точная корреляция описаны в [runner/evidence design](virtual-evidence-design.md). Это дополнение к существующему research contract, не переинтерпретация прежних manifests.

Текущая кампания виртуальная: T00–T08, T10–T11 в применимой эмуляторам части. T09 — будущая кампания, не условие текущего завершения. Для T08 radio enforcement имеет отдельный отложенный verdict; core-side acceptance остаётся активной задачей.

## Общие правила verdict

Каждая карточка содержит profile revision, requirement IDs, spec/version/clause (для normative verdict), preconditions, stimulus, observation points, expected outcome, negative control, cleanup, timeout и result. Нормативная привязка без clause/условия помечается MAPPING_PENDING; это допускает engineering regression, но блокирует standards-profile acceptance.

Статусы: PASS, FAIL, NOT_TESTED, BLOCKED, NOT_APPLICABLE. N/A требует зафиксированного основания из scope/applicability; отсутствие инструмента означает BLOCKED. Для агрегата обязательный FAIL даёт FAIL; иначе BLOCKED, затем NOT_TESTED; PASS только если все обязательные применимые проверки PASS. Incomplete capture не превращается в PASS.

Измерять отдельно signalling establishment, media, teardown, security, policy и application outcome. Обычный звонок выполняется без необходимости загрузить AI. Последовательные integration runs получают exclusive lock; cleanup действует на свои Call-ID/resources. Перезапуски daemon и fault injection — отдельные явно отмеченные разрушительные для текущих вызовов сценарии, а не часть read-only readiness.

Предлагаемые инженерные бюджеты для первого локального пилота: 30 с registration/call setup, 60 с двустороннего аудио, 10 с проверки cleanup, 120 с восстановления после готовности dependency. Это не таймеры 3GPP и не основание менять SIP/NAS timers. Если negotiated protocol timer длиннее, тест ожидает именно его плюс записанный margin. После пилота freeze budgets до серии acceptance.

Предлагаемая серия: 10 последовательных успешных обычных вызовов в каждом направлении; по 3 каждого negative/recovery сценария. Все попытки сохраняются, неудачные не заменяются успехом без объяснения и повторной серии после исправления. Это local repeatability, не статистическое доказательство carrier-grade availability.

## T00 — runner и доказательства

- Предусловия: snapshot источников/образов, выделенный стенд, synthetic identities, новый run-id.
- Стимул: отдельно провалить DNS, route check, регистрационную проверку и один media assertion через изолированные mocks/контролируемый fault.
- Ожидается: ненулевой exit и FAIL конкретного requirement; READY не выводится как acceptance; stale PASS предыдущего run не учитывается.
- Отрицательный контроль: удалить обязательный файл capture; результат NOT_TESTED/BLOCKED, а не PASS.
- Сохранять verdict по каждой проверке, provenance, safe configuration и точку вмешательства. Тесты runner не доказывают сеть.

## T01 — recovery и отсутствие обходного маршрута

- Предусловия: действующие оба DNN и регистрация, сохранённая исходная карта UE/PDU/IP/TUN; нет чужих вызовов.
- Стимулы отдельными прогонами: перезапуск UE, DNS, SIP-клиента и Docker daemon; смена назначенного IMS IP при воспроизводимом сценарии.
- Проверить динамическое обнаружение TUN, возврат DNS и клиентов, re-registration, путь к P-CSCF/media anchor и обратный путь через UPF.
- Evidence: route/source-IP и packet observations на UE IMS context и UPF; no-bypass assertion. Номер uesimtun не фиксируется.
- Negative: удалить IMS /32 route, оставив доступную Docker-сеть. Readiness обязан отказать; пакет через bridge не засчитывается как IMS success.
- Cleanup: восстановить только изменённые test-owned параметры, убедиться в двух рабочих UE.

## T02 — 5GS регистрация, security и сессии

- Два UE с различными ключами; проверить NG Setup, независимые registrations, выбранные NAS algorithms и Authentication/Security Mode outcomes.
- У каждого UE создать internet и ims: сопоставить SUPI alias, AMF/RAN UE IDs, PDU session ID, DNN/S-NSSAI, IP, TEID и UPF rules.
- Проверить DNS и предлагаемый P-CSCF; различать параметр SMF config, доставку в PCO/EPCO и фактическое использование клиентом.
- Negative: неверный ключ одного UE, неразрешённый DNN, отсутствие DNS, освобождение одной PDU session. Второй UE/другая сессия сохраняются в заявленном scope.
- NAS/NGAP decode требуется для protocol verdict. Эмулированное radio не подтверждает physical access-stratum security.
- Отдельный capability probe: idle/service request/paging на UERANSIM 3.2.6. Если доступны, включить MT call after idle в LAB серию; если нет — записать limitation и не приписывать результат physical UE.

## T03 — IMS AKA, Cx и жизненный цикл регистрации

- Клиент подтверждённо поддерживает выбранный AKA profile; HSS данные согласованы, SQN persistent. Секреты не попадают в вывод runner.
- Для каждого UE наблюдать initial REGISTER, challenge, authenticated REGISTER, результат и live registrar state. Связать UAR/UAA, MAR/MAA, SAR/SAA там, где они применимы к конкретной процедуре.
- Записывать алгоритм, CSeq/Call-ID, current contact/expiry и Cx Session-Id/result codes. Ключи/векторы редактировать до shareable evidence; callback без wire IDs не дорисовывать как полный Diameter exchange.
- Negative: неизвестный IMPI/IMPU, неправильный ключ, stale/replayed response, controlled SQN desync; различать ожидаемый отказ и корректный AUTS/resync.
- Затем re-register, expiry, deregister и смена адреса: прежний контакт/доступ не остаются действительными. Вызов под просроченной регистрацией должен дать предусмотренный отказ.
- Важная граница: успешный SIPp AKA REGISTER и отдельный PJSUA Digest call не составляют доказательство AKA-аутентифицированного voice-сеанса.

## T04 — защита IMS access

- Предусловие: D04 и эмулированный клиент с нужным security agreement; Linux namespaces позволяют проводить этот этап без hardware. AKA success сам по себе не завершает этот тест.
- Проверить negotiation, выбранные параметры, созданные associations/policies и защищённые последующие SIP-сообщения на нужных адресах/портах.
- Negative: несогласованные security parameters, неподходящий Security-Verify, непредусмотренное незашифрованное/незащищённое продолжение после agreement. Expected response задаётся точным clause выбранного профиля.
- Re-register/IP change/expiry: проверить обновление и удаление associations. Установка WITH_IPSEC или нулевой/ненулевой счётчик SA отдельно не достаточны.
- Core Diameter/SBI transport protection и media SRTP — отдельные свойства; не засчитывать их вместо Gm protection.

## T05 — обычный двусторонний звонок

- Предусловия: свежая registration обоих UE, отдельная проверка caller/callee path, AI не является dependency базового режима.
- UE-A звонит UE-B, затем обратный отдельный прогон. Собрать SIP по диалогам, offer/answer, ACK, Route/Record-Route, Contact, negotiated codec/PT/ports.
- На каждой стороне отправлять различимый синтетический звук; записать receiving audio с известной временной базой. Проверить содержание каждого направления и отсутствие подмены local playback выходом.
- Снять RTP/RTCP по каждому leg/SSRC: packets, bytes, loss/sequence gaps, jitter, timestamps. Агрегированная сумма не заменяет две независимые проверки.
- Negative: блокировать одно направление media при сохранном SIP; signalling может PASS, media обязан FAIL. Нет общего PASS.
- Завершить BYE и передать cleanup в T06. Наличие RTCP, codec и качество оцениваются по frozen profile, не по произвольной константе.

## T06 — SIP lifecycle и ошибки

- Отдельные кейсы: normal BYE с каждой стороны, CANCEL до ответа, гонка CANCEL/200, busy, unregistered callee, no response, retransmitted INVITE, потеря ACK/ответа, re-INVITE/hold-resume по профилю.
- Для reliable provisional responses/session timers добавить PRACK/UPDATE/refresh согласно D02/device applicability. Не требовать 180 во всех допустимых flow и не считать любой 200 ответом именно на INVITE.
- Expected: согласованные tags/CSeq/transaction state, предусмотренные ответы и timers, отсутствие двойной AS/media session при повторе.
- Cleanup: проверить отсутствие конкретного dialog и RTP session, release service state/queues, отсутствие роста leaked ports после серии. Перезапуск peer не обязан сохранить активный звонок без такого требования; bounded failure и возможность нового звонка обязательны для local recovery.
- Собственный AS отдельно проверить на эти кейсы: обработка CANCEL как обычного BYE без завершения исходной INVITE-транзакции не является достаточной реализацией.

## T07 — изоляция и повторяемость

- Переходы 1→2→1 звонок с разными synthetic signals и идентичностями. Проверять каждый dialog/port/SSRC и отсутствие перекрёстного аудио.
- Controlled loss/jitter/DTX внутри согласованных budgets; остановка одного клиента не очищает чужую сессию.
- После серии сравнить resource baseline: порты, registrar/dialog/media/AI state. Нулевой рост утечек в этой серии не является throughput benchmark.

## T08 — policy и QoS

- Предусловие: capability inventory и D06. Сначала доказать реальную обработку выбранного AF request сервисом PCF, а не доступность HTTP-порта.
- Проследить создание/обновление/удаление policy session, policy rules→SMF→PFCP→UPF, связанные flow descriptions и QFI; на physical — gNB/UE mapping к DRB.
- Добавить заранее заданную конкурирующую нагрузку и проверить применение согласованных QoS-параметров обоих направлений. 5QI/QFI/PDB не интерпретировать как end-to-end AI latency.
- Negative: policy deny/unavailable, insufficient resources, односторонний flow mismatch. Не объявлять гарантированный voice QoS при fallback на best effort.
- BYE/timeout/failure: правила освобождены, signalling и другие вызовы сохраняются согласно профилю. Если доступна только control-plane часть, итог CONTROL_PLANE_ONLY и физическая строка NOT_TESTED.

## T09 — физический UE

- Заблокирован до D01–D05. Записать модель, firmware, USIM/ISIM profile, bands, PLMN/TAC/slice, IP family, network profile и диагностические возможности.
- Native IMS registration через полученные сетевые параметры; MO/MT голос с согласованным codec и security; отдельный входящий вызов после idle с paging/service request.
- Проверить audio на принимающем устройстве, MTU/large SIP, длительный вызов/refresh, UE reconnect и изменение IP.
- Mobility/2nd cell, emergency, RTT/SMS и supplementary services расширяют профиль после applicability review; отсутствие их стендовой поддержки не скрывать за общим названием VoNR.

## T10 — услуги

- iFC/ISC trigger подтверждается применённым user profile и связанным AS dialog, а не одной строкой «AS received».
- OBSERVE: обычный звонок сохраняет оба направления при отключении AI и при других отказах, для которых заявлен fail-open. Если AS стоит в обязательном SIP-path, его отказ не считать автоматически переживаемым.
- TERMINATE: проверить lifecycle T06 и корректное завершение при недоступности media service. Очереди по вызовам независимы.
- Запись: отдельный сценарий с disclosure; приватный output и проверяемое удаление/retention по локальной политике. Не смешивать private audio с shareable signal evidence.

## T11 — переводчик и задержка

- Сначала accepted basic/service path. Фиксировать модели, hardware, fixture, warm/cold состояние и voice profile.
- Две отдельные language legs, полный source/output audio, проверка языков и смысла всех реплик. Утверждение «raw speech не пересылается» проверять по сигналу, не константой в JSON.
- Start latency = принимающий audio onset перевода минус onset исходной речи на согласованной временной базе. Сохранять clock uncertainty и границу measurement. RTP-send onset оставлять отдельной метрикой.
- Проверять не только первый фрагмент, но полноту хвостов, порядок, смысл и накопление отставания. Цель 1–3 с — требование проекта; не спецификация 3GPP.

## Контракт evidence

Предлагаемое расширение существующих `local/evidence/runs/<run-id>/`; имена ниже — контракт для реализации, не обещание уже созданных файлов:

```text
manifest.json              profile/revision, scenario, versions, safe parameters
assertions.json            per-requirement verdict and evidence references
inventory.json             images/packages/modules/patches/config hashes
clock.json                 time sources, offset/uncertainty, capture boundaries
shareable/events.jsonl     pseudonymized correlated protocol observations
shareable/diagrams/        only observed or explicitly labelled inferred steps
shareable/metrics.json     definitions, units, boundaries, missingness
private/                   protected traces; audio remains under local/private
```

Согласовать существующую research schema перед реализацией; не ломать уже сохранённые manifests. Shareable отчёт не содержит ключи, auth vectors, raw identifiers/audio/transcript. В нём есть ссылка на private artifact hash, а не секретное содержимое. Метрика без синхронизированных часов либо без нужного события UNAVAILABLE; её нельзя вычислять вычитанием несопоставимых WAV clocks.
