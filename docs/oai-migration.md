# Локальный OAI для проверки передаваемой части IMS + AI

Дата: 2026-09-29. Цель — проверить наш IMS + AI с OAI локально, затем
подключить ту же часть к уже работающему ядру партнёров.
Контракт передачи: [partner-integration.md](partner-integration.md).

## Изменения ядра

`app/infrastructure/compose/core-oai.yml` теперь описывает OAI CN5G v2.2.1:
NRF, AMF, SMF, UPF, AUSF, UDM, UDR и отдельную MySQL `oai-db`.
IMS MySQL/PyHSS остаются самостоятельными. Старый Mongo volume не удаляется.
Источник конфигурационного контракта и DDL закреплён в
[provenance](../app/infrastructure/vendor/oai-cn5g/PROVENANCE.md).

`initialize_local.py` создаёт приватные config-файлы `local/oai/*.yaml`
в JSON-синтаксисе YAML. OAI SBI использует HTTP/1.1; OAI 2.2.1 HTTP/2
AM-data handler неверно извлекал UE ID для наблюдавшегося запроса.
SBI timeout увеличен до `OAI_HTTP_TIMEOUT_MS` для локальной ВМ.
SM subscription хранит `FFFFFF` как представление отсутствующего SD,
которое использует OAI SMF при запросе UDR.

UPF simple-switch использует один `tun0` для обоих DNN. Общий SNAT OAI
отключён: wrapper UPF при каждом запуске устанавливает NAT только internet и отдельный
IMS gateway/route на tun0, включая обычный `docker restart`. Проверки больше не требуют Open5GS ogstun2.
Healthcheck UPF проверяет реальный TUN и UDP listeners N3/N4, а не успешный
разбор текста шаблона. Healthcheck не доказывает прохождение RTP.

`oai_subscribers.py` создаёт новые лабораторные записи, проверяет неизменность
существующих ключей и не перезаписывает их SQN. Новый OAI store получает
начальный SQN для пересозданных UERANSIM UE. Это **не перенос authentication
state из Mongo для существующей физической SIM**. Миграция физической SIM
требует отдельного согласования SQN/resynchronization. Старые Mongo и IMS
данные сохранены; `migrate_subscriber_keys.py` остаётся Open5GS-only утилитой.

OAI info/debug logs могут содержать ключи и auth vectors. Рабочий уровень
логирования — warning; полные диагностические логи не включать в передачу.

## Проверки

| Проверка на локальном OAI | Результат и граница |
| --- | --- |
| `quality/check.py` | PASS: 180 unit tests, форматирование, layout, документация, offline research tooling |
| Полный base launcher | PASS: два UE, по internet/ims PDU, internet connectivity, IMS DNS/route, Cx, две текущие Digest-регистрации |
| `verify-ims-call.sh` | PASS: SIP call, iFC → AS, обе RTP-ветви, AI observation; RTP продолжает идти при отключённом AI |
| `verify-real-ai-stream.sh` | PASS: русский IMS audio → Whisper → английский перевод Qwen → Piper → RTP, несколько реплик |
| `verify_aka_registration.py` | PASS: два UE с IMS AKA/Cx, восстановление Digest-клиентов |
| `verify_aka_call.py --caller 1` | PASS: same-process AKA registration + двусторонний PCMU, AS/AI отключены на время baseline |
| Повторный OAI provisioning | PASS: сравнение записей до/после — ключи и SQN не изменились |
| `docker restart lab-upf` + восстановление access chain | PASS: health/NAT/IMS route восстановились; затем все BASE_GATES снова PASS |
| Partner Compose | CONFIG PASS: только IMS + AI, без core/RAN/UE, next-hop передаётся DNS/CSCF/RTPengine |

Тесты выполнялись последовательно на одном стенде. Локальные machine overrides
сохранены: AI запуск использовал CUDA STT; CPU-профиль отдельно не измерялся.
Доказательство AI заканчивается на отправке TTS/RTP; это не измерение задержки
speech-start → far-end audible playback и не новый результат на 1–3 секунды.

Приватные логи: `local/oai-final-base.log`, `local/oai-recovery.log`,
`local/oai-ims-call.log`, `local/oai-real-ai.log`, `local/oai-final-ai.log`,
`local/oai-management-check.log`, `local/oai-quality-final.log`.
Контрольный AI-вызов после итоговых сетевых изменений также завершился PASS.
AKA evidence: `local/private/aka-register-20260929T095025225826Z` и
`local/private/aka-call-20260929T095201399667Z`. В Git и пакет передачи они не входят.

Внешний OAI партнёров, Linux macvlan deployment, реальные телефоны, AMR/EVS,
Gm IPsec и полный fault/lifecycle matrix не проверены. Partner CONFIG PASS
не подменяет эти проверки. Для партнёров понадобится их заполненный сетевой
контракт и IMS identity/credential profile из инструкции подключения.

## Откат

Остановить локальные новые сервисы без `-v`. Старое определение ядра сохранено
как `app/infrastructure/compose/core-open5gs.yml`, исходный Git revision доступен
в истории ветки. Для полного отката восстановить согласованную версию Compose,
launcher, env и gate-скриптов из исходной ревизии, сохранив `local/secrets` и тома.
Не переключать только образ UPF: маршруты и subscriber backend отличаются.
Операцию отката в этой миграции не выполняли.
