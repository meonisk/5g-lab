# Виртуальный 5GS core и доступ: проект реализации

Обновление runtime 2026-09-29: локальный core заменяется на OAI; актуальные изменения и проверки — [oai-migration.md](oai-migration.md). Описание Open5GS ниже сохранено как исходный проект и не является текущей инструкцией запуска.

Статус: проект, 2026-09-21. Scope — два эмулированных UE и один gNB в Docker; физический NR, USIM и выбор оборудования сюда не входят. Документ конкретизирует [профиль](3gpp-profile.md), [требования](3gpp-requirements.md) и [сценарии T00–T03](3gpp-acceptance.md). Формат и ограничения наблюдений детализирует [проект evidence](virtual-evidence-design.md). Он не является протоколом успешной проверки.

## Исходная система и ответственность

| Узел | Текущий источник | Роль и интерфейс |
| --- | --- | --- |
| UERANSIM UE 1/2, gNB | [access.yml](../app/infrastructure/compose/access.yml), [ue.yaml](../app/infrastructure/configs/ueransim/ue.yaml) | Эмулированный радиообмен UE–gNB; N1 NAS через gNB, N2 NGAP к AMF, N3 GTP-U к UPF. Это не NR-Uu PHY/RF. |
| Open5GS | [core-open5gs.yml](../app/infrastructure/compose/core-open5gs.yml) | AMF/AUSF/UDM/UDR/NRF/SCP, SMF, PCF, UPF; N4 PFCP SMF–UPF. Логический N6 соединяет UPF с data networks; `ogstun` и `ogstun2` — локальные TUN endpoints реализации для двух DNN. Mongo хранит 5GS subscriber. |
| SIP clients | [access.yml](../app/infrastructure/compose/access.yml), [sip-ue-run.sh](../scripts/sip-ue-run.sh) | PJSUA делит network namespace с соответствующим UE, выбирает IMS TUN по выданному адресу и ставит /32 маршруты к P-CSCF и RTPengine. Текущий профиль — Digest, отдельно от будущего AKA клиента. |
| IMS domain | [ims.yml](../app/infrastructure/compose/ims.yml), [provision-ims-subscribers.sh](../scripts/provision-ims-subscribers.sh) | PyHSS/IMS subscriber и AuC отдельно от Open5GS Mongo, CSCF и media anchor. |

Сеть Docker связывает процессы и не доказывает прохождение пользовательского трафика через PDU session. Для каждого IMS вызова нужны route/source-IP на UE TUN и наблюдение N3/N6, иначе результат T01/T05 — FAIL. Имена `uesimtun*` нельзя фиксировать: UERANSIM создаёт TUN для каждой PDU session; текущий скрипт уже ищет адрес в IMS CIDR. `ogstun` для internet и `ogstun2` для ims создаёт [upf-ims-setup.sh](../scripts/upf-ims-setup.sh); второй пул без NAT. Сохранить это разделение, но при восстановлении проверять реальные PDU ID и адреса заново.

## Контракт сессии и корреляция

Один SUPI alias связывает UE и subscriber, но значения ключей у UE1 и UE2 различны. Для каждого UE ожидаются две IPv4 PDU session с DNN `internet` и `ims`, S-NSSAI SST 1. [SMF](../app/infrastructure/configs/open5gs/smf.yaml) задаёт два пула, DNS и P-CSCF; [UPF](../app/infrastructure/configs/open5gs/upf.yaml) привязывает DNN к TUN. Настроенный P-CSCF ещё не означает доставку PCO/EPCO и использование клиентом: эти три наблюдения разделить.

В evidence на один run записывать безопасную корреляционную строку: pseudonym SUPI → RAN/AMF UE IDs → PDU session ID → DNN/S-NSSAI → назначенный IPv4 → имя UE TUN → N3 UL/DL TEID и адрес endpoint → N4 PFCP SEID/PDR/FAR → UPF TUN → source-IP SIP/RTP. Значения брать из декодированного NAS/NGAP/PFCP/GTP и состояния конкретного запуска; не выводить их из порядка YAML или номера интерфейса. TEID относится к tunnel leg и может меняться после пересоздания сессии. Если observation отсутствует, поле `UNOBSERVED`, а protocol verdict заблокирован. Секреты, auth vectors и полный SUPI не писать в shareable evidence.

## Учётные данные и SQN

Сейчас [core-open5gs.yml](../app/infrastructure/compose/core-open5gs.yml) передаёт общие `SUBSCRIBER_K/OPC/AMF` в Mongo и оба UE; [subscribers.js](../scripts/subscribers.js) удаляет и вставляет строки при каждом provisioning. [initialize_local.py](../scripts/initialize_local.py) создаёт одну пару K/OPc и Digest password. [provision-ims-subscribers.sh](../scripts/provision-ims-subscribers.sh) обновляет/создаёт PyHSS AuC с `sqn: 96` при каждом старте. Это несовместимо с требованием независимых абонентов и надёжным повторным AKA после restart; 5GS и IMS — две отдельные базы и два отдельных счётчика, даже если выбранный тестовый профиль использует связанные identity.

Целевой контракт: отдельные UE1/UE2 5GS K/OPc/AMF и отдельные UE1/UE2 IMS AuC credentials в игнорируемом `local/secrets/ims.env`; публичные IMSI/MSISDN остаются в `app/config/lab.env`. Инициализатор генерирует недостающие значения один раз, валидирует формат, не печатает их и не меняет существующие ключи без явной операторской ротации. Mongo upsert изменяет только управляемые поля и сохраняет остальное состояние; PyHSS upsert связывает APN → subscriber → AuC → IMS subscriber. Для существующего AuC сохранять текущий SQN, а начальное значение ставить только при создании. При расхождении SQN применять документированную AKA resynchronization процедуру, не откатывать серверный счётчик. Прежде чем писать код, проверить точные поля и поведение PyHSS версии из закреплённого образа, включая PATCH и AUTS; до проверки это проектное требование, не утверждение о готовой функции.

Миграция старого состояния: сделать приватный backup двух баз, инвентаризировать только имена полей/связи без вывода ключей, выбрать отдельные тестовые credentials, обновить UE и обе базы согласованно в maintenance window, явно сбросить регистрации, затем выполнить T02/T03. Повторный `start` не должен менять credentials или SQN. Проверки: неверный ключ UE1 не нарушает UE2, чужой IMPI не проходит IMS AKA, replay/stale response отклоняется, допустимый AUTS восстанавливает одного абонента. Текущий Digest regression остаётся отдельным gate и не засчитывается за AKA.

## Готовность и восстановление

`compose depends_on` задаёт порядок запуска, но не доказательство сетевой готовности. [start_lab.py](../scripts/start_lab.py) сегодня поднимает всё, ожидает REST PyHSS, provisioning, принудительно перезапускает цепочку с фиксированными задержками, ждёт AI health и печатает `READY`; `--skip-verify` не проверяет 5GS/IMS. Разделить состояния:

1. `CONFIG_VALID`: синтаксис, совместимость версий/образов, наличие нужных секретных ключей, отсутствие конфликта пулов/адресов; никаких сетевых утверждений.
2. `CORE_READY`: NRF/SCP, subscriber stores, AMF NGAP listener, SMF–UPF PFCP association и gNB NG setup наблюдаются для текущего run.
3. `ACCESS_READY`: оба UE зарегистрированы с наблюдаемым NAS security outcome; у каждого обе PDU session с IP, TUN, N3/N4 rules и достижимым DNS/P-CSCF через IMS TUN. Отказ любого обязательного пункта блокирует переход.
4. `IMS_READY`: две текущие регистрации клиента с действующим contact/expiry и согласованным source-IP, после принятого T03 AKA — только AKA-клиента. Отдельный обычный test call остаётся acceptance, а не пассивной health probe.
5. `SERVICE_READY`: надстройка AI/AS по отдельному профилю; её отсутствие не снимает `IMS_READY` обычного звонка.

У каждого состояния есть generation ID, deadline, последние наблюдения и причина отказа. После рестарта UE, gNB, SMF, UPF или Docker daemon инвалидировать прежние `ACCESS_READY`/`IMS_READY`, повторно обнаружить TUN/IP/TEID, перепроверить маршрут и регистрации. DNS/SIP client restart инвалидирует IMS состояние. Смена IMS IP требует снять старый contact и создать новый. При timeout вернуть `BLOCKED` либо `FAIL` по сценарию, не печатать READY и не наследовать старый PASS. Никакого автоматического удаления Mongo/PyHSS или отката SQN при recovery. Startup может повторять идемпотентные операции с bounded retry; разрушительные restart/fault injection выполняются только в выделенном T01 run. Состояние одной сессии/UE не должно очищать другую.

## Порядок реализации

| Волна | Изменения и критерий выхода |
| --- | --- |
| W0 — acceptance runner | Новый read-only inventory/runner в `app/tests/integration/` с run ID, безопасной корреляцией, явными PASS/FAIL/BLOCKED и provenance; `scripts/start_lab.py` не подменяет acceptance своим health статусом. Сначала T00 mocks и baseline T01/T02: снимки N1/N2/N3/N4, TUN/IP/route, DNS/PCO. Подробности — в [проекте evidence](virtual-evidence-design.md). |
| W1 — lifecycle/network | `app/infrastructure/compose/access.yml`, `app/infrastructure/compose/ims.yml`, `scripts/sip-ue-run.sh` и readiness в `scripts/start_lab.py`: пересоздание и проверка текущих PDU/IP/TUN/route/registration после рестарта UE/DNS/client/daemon, без сохранения старого READY. T01 отрицательные сценарии и recovery должны пройти до заявления готовности. |
| W2 — subscriber identity | `scripts/initialize_local.py`, `scripts/subscribers.js`, `scripts/provision-ims-subscribers.sh`, `app/infrastructure/compose/core-open5gs.yml`, `app/infrastructure/compose/access.yml`, `app/infrastructure/configs/ueransim/ue.yaml`, `app/config/ims.env.example`; при необходимости `scripts/load-lab-env.sh`. Раздельные секреты, идемпотентный provisioning и сохранение SQN, совместимая миграция с backup/rollback; T02 отрицательные сценарии. Публичные адреса и таймауты — `app/config/lab.env`, секреты — только ignored `local/secrets/ims.env`. |
| W3 — AKA/Cx | После W2 и capability probe закреплённых версий PyHSS, CSCF, UERANSIM и выбранного Linux AKA SIP-клиента добавить отдельный AKA client config/image в `app/infrastructure/images/` и Compose access, корреляцию Cx/REGISTER и тесты T03. `scripts/sip-ue-run.sh` сохраняет Digest/PCMU regression; его нельзя молча переименовать в AKA. Gm security T04 относится к отдельной W6a; обычный звонок не зависит от AI. |

Файлы перечислены как места будущей работы; этот документ не меняет runtime. Действовать последовательно на общем стенде: W0 измеряет baseline, W1 закрепляет lifecycle, W2 мигрирует identities, W3 зависит от W2 и capability probe клиента. После code changes выполнить `python scripts/quality/check.py`, rebuild соответствующих образов и live gates последовательно согласно [AGENTS.md](../AGENTS.md); в текущем проектном проходе они не запускались.

## Отрицательные сценарии и пределы

T01: убрать IMS /32 route при доступном Docker bridge — readiness должен отказать; restart UE/DNS/client/daemon и смена IP требуют нового mapping. T02: неверный ключ одного UE, запрещённый DNN, DNS failure, release одной PDU session; второй UE/сессия должны оставаться наблюдаемыми. T03: неизвестный IMPI/IMPU, неправильный IMS ключ, replay и SQN desync. Каждая попытка получает отдельный verdict и cleanup; неудачный сценарий не исправлять пересозданием subscriber в середине серии.

UERANSIM моделирует UE/gNB и радиообмен по UDP RLS; этот стенд не измеряет RF, physical access security, paging на устройстве или radio QoS enforcement. Возможность idle/paging и выдачу PCO/EPCO проверить на закреплённом образе отдельно; отсутствие возможности записать как limitation. N4/QFI/core policy evidence может существовать без radio enforcement, но не даёт device VoNR verdict. PCMU/8000 остаётся контрактом текущего аудиостенда, не автоматическим подтверждением выбранного IMS voice profile.

## Источники и границы утверждений

Архитектурные понятия DNN/S-NSSAI/PDU session/N3/N4/N6 взяты из [3GPP TS 23.501 Release 18, опубликованной ETSI](https://www.etsi.org/deliver/etsi_TS/123500_123599/123501/18.07.00_60/ts_123501v180700p.pdf). Процедуры 5GS authentication/SQN требуют сверки с [3GPP TS 33.501](https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=3169) при замораживании точной ревизии и clause; этот документ не присваивает нормативный PASS. Наличие отдельного TUN на PDU session описано в [UERANSIM Usage](https://github.com/aligungr/UERANSIM/wiki/Usage), а применимость к закреплённому образу проверяется T02. Таймауты, state names, layout секретов, no-bypass assertion и очередность W0–W3 являются правилами этого проекта, не требованиями 3GPP.
