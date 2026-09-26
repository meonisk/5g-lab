# Виртуальный стенд: runner и доказательства

Статус: implementation design, 2026-09-21; базовые failure checks, OS lock и durable capture реализованы частично, полный acceptance runner ещё не принят. Scope — виртуальные LAB-VOICE-1 и SERVICE-VOICE-1 из [профиля](3gpp-profile.md). Покрывает B01/B02/E01–E03/E06, W0/W4 и обеспечивает остальные тесты [приёмки](3gpp-acceptance.md). Все правила этого документа — PROJECT engineering requirements, не новые нормы 3GPP.

## Ограничения, зафиксированные до начала реализации

Часть исправлена в текущем working tree; актуальная граница — [ход реализации](virtual-stand-plan.md). Таблица сохраняет основания проектирования.

| Файл | Наблюдение в исходнике | Требуемое изменение |
|---|---|---|
| [capture.py](../app/research/tools/ims_research/capture.py) | gates.json пишется после полного цикла; TimeoutExpired прерывает цикл | Durable result после каждого шага; timeout/interrupt явно завершают попытку |
| [capture.py](../app/research/tools/ims_research/capture.py) | Inventory Docker снимается после gates | PRE и POST inventory; detect recreations/image/config changes |
| [capture.py](../app/research/tools/ims_research/capture.py) | Логи берутся через общий tail, отсутствующий контейнер пропускается | Run-scoped cursors/time bounds, обязательные источники, missingness |
| [validation.py](../app/research/tools/ims_research/validation.py) | Проверяет количество gates и returncode, не точное соответствие IDs | Unique exact IDs/profile membership; duplicate/missing/foreign gate запрещены |
| [validation.py](../app/research/tools/ims_research/validation.py) | Schema-файлы читаются, в основном ручная проверка полей | Проверять versioned schema и семантические ограничения результата |
| [CLI](../app/research/tools/ims_research/cli.py) | Default design — замороженный language-services-smoke-v2 | Новый отдельный admission design для текущего профиля, historical design не переписывать |
| [design v2](../app/research/designs/local-language-services-smoke-v2.json) | Factors содержат qwen2.5/espeak, текущий публичный профиль Qwen3/Piper | Проверить design/effective-runtime match до вызова; несовпадение блокирует принятие |
| [start_lab.py](../scripts/start_lab.py) | Startup без AI не выделен; successful script exit принимается как gate success | Отдельные infrastructure/service readiness и структурированные verdicts |

Это статический анализ границ кода; не все описанные варианты были воспроизведены runtime. Подтверждённый ранее mock-пробой ложный exit=0 базового verify.sh нужно закрыть первым. Исторические manifests остаются историческими; новый schema/runner не переинтерпретирует их как более сильную приёмку.

## Модель execution

```text
PREPARED -> LOCKED -> PREFLIGHT -> CAPTURING -> STIMULUS -> ASSERTING
                                                     -> CLEANUP -> SEALED
Любая ошибка после lock -> CLEANUP -> SEALED с явным неполным verdict
```

1. PREPARED: immutable design/profile hash, уникальная попытка, source snapshot и planned cases; секреты не входят.
2. LOCKED: единственный владелец stand ID; PID/host/start/process identity. Stale lock нельзя снять одним проверенным номером PID: нужен marker identity и отсутствие живого владельца; crash recovery записывается отдельным событием.
3. PREFLIGHT: выбранные versions/client capabilities совпадают с profile; prerequisites готовы. Readiness не ставит тестовые звонки и не выполняет destructive recovery.
4. CAPTURING: запустить обязательные collectors до стимулов; сохранить clock metadata. Отсутствие collector до старта даёт BLOCKED, а потеря обязательного capture после старта делает outcome непринимаемым.
5. STIMULUS: только действия текущего scenario, заранее объявленные disruptive effects. Event содержит scenario/attempt ID и безопасные correlation aliases.
6. ASSERTING: независимые signalling/media/security/policy assertions; неизвестное не становится true.
7. CLEANUP: завершить собственные call IDs, recorder processes и test-owned faults; проверить возвращение заявленного baseline. Ошибка cleanup препятствует общему PASS и следующему dependent case.
8. SEALED: immutable итог, список всех файлов и hashes, сохранение interrupted/timeout outcomes. Повторный collect на тот же SEALED run запрещён; новая попытка имеет новый ID.

Сохранять journal при переходах состояния и завершении каждого case, затем писать snapshot через temporary file + atomic replace. Crash recovery читает journal и выставляет незавершённые cases как NOT_TESTED с reason INTERRUPTED; уже сохранённые FAIL сохраняются. Cleanup не может задним числом превратить FAIL в PASS.

## Контракт результата

Предлагается additive sidecar `acceptance.json` с отдельной `acceptance_schema_version`. Старый manifest v1 и research stage semantics сохраняются. Перед реализацией создать schema для sidecar; пример ниже описательный, не настоящий PASS:

```json
{
  "acceptance_schema_version": "1.0",
  "run_id": "synthetic-example",
  "profile_id": "LAB-VOICE-1",
  "profile_revision": "candidate",
  "execution_status": "SEALED",
  "engineering_verdict": "NOT_TESTED",
  "standards_verdict": "BLOCKED",
  "standards_reason": "MAPPING_PENDING",
  "cases": [{
    "case_id": "T05.A-to-B",
    "attempt": 1,
    "requirements": ["I07", "M01", "M02"],
    "verdict": "NOT_TESTED",
    "reason": "EXAMPLE_ONLY",
    "command_exit": null,
    "assertions": [],
    "evidence_refs": []
  }]
}
```

В полной карточке assertion обязательны: уникальный ID, requirement ID, actual/expected, units и measurement boundary при метрике, status/reason, source references и временные границы. Case должен перечислить все ожидаемые assertions даже при раннем выходе. Каждый evidence ref указывает существующий artifact hash и, где возможно, event IDs/packet range, а не произвольную строку stdout.

Инвентаризация PRE/POST: git commit, tracked dirty patch hash, учёт untracked runtime-relevant файлов, immutable image IDs, версии бинарников/модулей, client version, безопасный effective config digest, scenario/fixture hashes, container IDs/network namespace IDs. Изменённый образ/контейнер допустим только если это stimulus recovery case; иначе профиль попытки недостоверен.

Статусы агрегируются по объявленному набору: FAIL > BLOCKED > NOT_TESTED > PASS. NOT_APPLICABLE исключается только по versioned applicability decision; пустой обязательный набор не даёт PASS. Command exit=0 необходим, но недостаточен: все обязательные assertions должны быть PASS, источники полны, cleanup принят. Exit!=0 несовместим с PASS. Standards verdict дополнительно требует spec/version/clause/условие применимости.

## Case registry и prerequisites

Registry хранит: case_id, requirements, profile membership, depends_on, required components/capabilities/collectors, disruption class, stimulus implementation reference, deadline source, expected assertions и cleanup implementation.

- Точное множество case IDs результата совпадает с expanded registry (направление/повтор указаны явно). Дубликаты и лишние IDs — schema/semantic FAIL.
- Неуспешный prerequisite не маскируется: dependent case получает BLOCKED с ссылкой на prerequisite, а не запускается на заведомо неверной базе.
- Independent diagnostics могут продолжаться, если не создают новый fault и cleanup безопасен. Их PASS не отменяет предыдущий FAIL.
- Registration/base call не зависит от моделей AI. Service case зависит от base acceptance и собственной readiness.
- Не смешивать identity одного клиента с регистрацией другого. Binding tuple включает UE alias, IMS identity alias, contact/transport, current UE address, registration flow и epoch.
- Шаблоны первых бюджетов/повторов остаются в profile revision; runner не подбирает threshold по полученному результату.

## Корреляция и clocks

Нужны разные уровни связей, а не один универсальный Call-ID:

| Уровень | Идентификаторы в приватном capture | Shareable связь |
|---|---|---|
| Access | UE identity, RAN/AMF UE IDs, PDU session ID, DNN, TEID | run-scoped aliases + session epoch |
| IMS registration | IMPI/IMPU, Contact, Call-ID/CSeq, transport, expiry | registration alias + client/UE binding |
| Cx | Session-Id, command code, hop-by-hop/end-to-end IDs | связанный transaction alias; без wire данных callback остаётся callback |
| SIP call | Call-ID + From/To tags, Via branch, CSeq/method | dialog и transaction aliases раздельно |
| Media | tuples, SSRC, sequence/timestamp, SDP origin/session version | dialog leg + stream epoch; SSRC сам по себе не уникален |
| Services | AS session, adapter session, utterance/reply ID | parent dialog alias, phrase/reply links |

Single-host shared clock не предполагается автоматически по слову Docker: записать механизм timestamp на host/container/client, UTC origin и monotonic duration source. Между разными clock domains вычитать время можно только после оценки offset/uncertainty. Audio samples→time требуют sample rate и capture origin. При отсутствии связи — UNAVAILABLE, не ноль и не отрицательная исправленная задержка.

## Capture и privacy

Существующий v1 research contract запрещает raw payloads в research evidence. Для новых приватных PCAP/SIP auth traces сначала определить отдельное защищённое хранилище `local/private/protocol/<run-id>/` и правила redaction; не помещать их в v1 shareable/raw tree. Ключ псевдонимизации сохранять по прежнему отдельному пути `local/evidence/private/`.

Shareable: нормализованные события без секретов, схема и hashes, метрики, диаграммы с явными missing events. Secret/auth-header redaction выполняется до записи shareable. Нельзя выводить полный docker inspect/env или SIP auth headers в обычный лог runner. Приватные аудио остаются `local/private/`; retention и доступ наследуют согласованную локальную политику.

Capture bounded по времени и объёму, но truncation фиксируется; tail=1000 не объявлять полным capture. Каждому required source назначены start/stop и capture_result. Пропущенный container source не игнорируется. При sealed run inventory содержит полный набор разрешённых файлов, чтобы checksums не могли скрыть пропуск обязательного artifact.

## Порядок изменений W0/W4

| Пакет | Изменения | Приёмка до перехода |
|---|---|---|
| R1 | verify.sh: explicit failure accumulation; tests с mock network fail | Отсутствие TUN и failed ping дают nonzero; positive mock проходит |
| R2 | Versioned case registry/sidecar schema/reducer | Wrong/missing/duplicate IDs, exit/JSON disagreement, empty result отвергнуты |
| R3 | Runner lock/journal/deadline/cleanup | Прерывание после первого case сохраняет его; второго runner не допускает |
| R4 | PRE/POST inventory/profile binding | Runtime/design mismatch блокирует; controlled recreation записана |
| R5 | Run-scoped capture + safe correlation | Старые события не проходят assertions; отсутствующий source не PASS |
| R6 | Separate base/service readiness | Base can start/check без STT/LLM warmup; legacy command entrypoints сохранены |
| R7 | SigDiag adapters и structured media checks | 1-to-1 link assertion→events/artifact; независимые legs и teardown |

Пример будущих отдельных модулей — registry, execution, results и evidence adapters под `app/tests/integration/`; реальные пути выбрать при реализации с соблюдением лимита 300 логических строк. Research capture должен вызывать этот runner, а не дублировать его verdict logic. Старые shell entrypoints можно оставить thin adapters на время миграции; нельзя сохранять альтернативный более слабый путь к PASS.

## Замораживание и незавершённые решения

До первого нормативного verdict нужны: agreed requirements subset и clauses, новый admission design с действительными factors, runner schema, list of required collectors, timeouts и permissible recovery changes. Все MAIN/AI scientific claims остаются отдельно. Эта детализация закрывает интерфейс проектирования W0/W4, но не исправляет существующий код и не повышает исторические результаты до нового уровня приёмки.
