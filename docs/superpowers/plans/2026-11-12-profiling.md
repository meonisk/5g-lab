# План: профилирование стенда (CPU и задержки перевода)

Дизайн: [2026-11-12-profiling-design.md](../specs/2026-11-12-profiling-design.md).
Ветка `partner-ims-ai`. Хост — только stdlib Python; логика без Docker покрыта
unit-тестами в `app/tests/unit/` (TDD: сначала тест, затем код).

## Файлы

| Файл | Ответственность |
|---|---|
| `scripts/lib/ue5g.py` | общее с `bench_5g.py`: `sh`, `ns`, `tunnel_ip`, `query`, `wait_for`, клиент PJSUA в namespace UE (`Client`), jail и фраза, вызов переводчика `translator_call` |
| `scripts/lib/latency.py` | чистая логика: `summary` (медиана/min/max), `percentile`, `describe` (среднее, p95), `stage_row` (этапы из событий AI Worker и Voice Agent), `conference_ports` (порты PJSUA из `cl`) |
| `scripts/bench_5g.py` | прежнее поведение; импортирует общее из `lib/` |
| `scripts/profile/cpu_sampler.py` | разбор `cpu.stat`/`cpuacct.usage`, `cpu.max`, `/proc/<pid>/stat`, `/proc/stat`; занятые ядра между двумя отсчётами; поток-сэмплер (0,5 с) |
| `scripts/profile/quality.py` | нормализация текста, WER по словам, точность `1 − WER`; WAV → PCMU 8 кГц (линейная передискретизация, G.711 μ-law) |
| `scripts/profile/verdict.py` | оценка задержки варианта, правило «≤ 2000 мс и качество не хуже `compact` − 10 п.п.», до трёх вариантов по CPU, узкое место |
| `scripts/profile/report.py` | сборка `report.json` из файлов прогона и `report.md` |
| `scripts/profile/scenarios.py` | S1–S5: нагрузка, сэмплер CPU, раунды фразы, JSON сценария; SKIP с причиной |
| `scripts/profile/sweep.py` | перебор: фикстуры (espeak-ng из `lab-pjsua`), параметры контейнера сервиса из `docker inspect lab-ai-worker`, одноразовый контейнер, WER |
| `scripts/profile/sweep_worker.py` | внутри образа AI Worker: `WhisperModel` из локального кэша, `ims_ai.utterances.recognize`, `ims_ai.translation.translate`, имитация потокового режима |
| `scripts/profile.sh` | точка входа: preflight, сценарии, перебор, отчёт, журнал, `trap`-восстановление |
| `scripts/lib/verify-all-lib.sh` | + `have_5g`, `STEP SKIP:` в `run_step`, заголовок итога `RUN_TITLE` |
| `app/tests/unit/test_profile_*.py` | unit-тесты чистой логики |

## Интерфейсы

- `cpu_sampler.cores_between(a, b)`: два отсчёта `{"t", "nodes": {имя: cpu_s}, "host": (busy, total), "ncpu"}` → `{имя: ядра, "host": ядра}`.
- `cpu_sampler.summarize(rows)` → `{узел: {"mean", "p95", "max", "n"}}`.
- `quality.accuracy(reference, hypothesis)` → `1 − WER`, не меньше 0.
- `verdict.evaluate(sweep_rows, context)` → `{"reference", "candidates", "fits"[:3], "note"}`.
- `scenarios.py S1..S5 --rounds N --out DIR` → `DIR/scenarios/S?.json`, строка `SCENARIO S?: DONE|SKIP`.
- `sweep.py --load idle|rfsim [--quick] [--repeats N] --out DIR` → `DIR/sweep-<load>.json`, строка `SWEEP <load>: DONE`.
- `report.py DIR` → `DIR/report.json`, `DIR/report.md`, строка `REPORT: <путь>`.

## Задачи

1. Вынести общее из `bench_5g.py` в `scripts/lib/` (`ue5g.py`, `latency.py`); тест
   `stage_row`, `conference_ports`, `describe`; `test_bench_5g.py` зелёный.
2. `cpu_sampler.py` (TDD): разбор счётчиков, ядра, p95, лимит `cpu.max`.
3. `quality.py` (TDD): WER, нормализация, μ-law и передискретизация.
4. `verdict.py` (TDD): оценка, правило укладывания, сортировка по CPU, узкое место.
5. `report.py` (TDD на рендер из готовых JSON).
6. `scenarios.py`, `sweep.py`, `sweep_worker.py` — оркестрация (без unit-тестов Docker).
7. `profile.sh` + расширение `verify-all-lib.sh`; сухой прогон с заглушкой `docker`.
8. Документация: README, `docs/project-layout.md`, `docs/guide-5-5g-scripts.md`
   (как читать отчёт), `CHANGELOG.md`.

Проверка: `bash -n`, unit-тесты, `python scripts/check.py` → `OFFLINE CHECKS: PASS`.
