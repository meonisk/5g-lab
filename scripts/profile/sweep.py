"""Перебор настроек AI без звонка: одноразовый контейнер из образа AI Worker.

  python3 scripts/profile/sweep.py --load idle|rfsim --out DIR [--quick] [--repeats N]

Образ, лимиты CPU и памяти, переменные и тома моделей берутся у работающего
lab-ai-worker (docker inspect): в любом режиме AI перебор идёт в тех же условиях, что
сервис. Фразы — голос Piper из образа Voice Agent (как в тесте диалога), PCMU 8 кГц:
espeak-ng тестовых клиентов Whisper распознаёт плохо, и замер STT уходит в мусор.
Недостающие tiny/base/small сначала докачиваются в кэш сервиса (fetch_models).
Результат — DIR/sweep-<load>.json; последняя строка — SWEEP <load>: DONE | SKIP.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/lib"), str(ROOT / "scripts"), str(ROOT / "app/tests/fixtures")]
from dialogue import phrase_wavs  # noqa: E402
from provision import read_env  # noqa: E402
from quality import accuracy, wav_to_pcmu  # noqa: E402

MODELS = ("tiny", "base", "small")
SERVICE = "lab-ai-worker"
WORKER = ROOT / "scripts/profile/sweep_worker.py"
DIALOGUE = ROOT / "app/tests/fixtures/interpreter-dialogue-v2.json"
# Загрузка как у models.load_model() сервиса: снимок models--Systran--faster-whisper-<size>.
FETCH = """import sys
from faster_whisper.utils import download_model
cache = sys.argv[1]
for size, revision in zip(sys.argv[2::2], sys.argv[3::2]):
    try:
        download_model(size, cache_dir=cache, revision=revision)
        print(f"модель {size}: в кэше", flush=True)
    except Exception as error:
        print(f"модель {size}: не скачана ({type(error).__name__})", flush=True)
"""


def plan_threads(nproc, service_threads, quick):
    """Потоки распознавания: 1, 2, 4, 8 не больше nproc; --quick — потоки сервиса и 4."""
    wanted = {service_threads, 4} if quick else {1, 2, 4, 8}
    return sorted(t for t in wanted if t <= nproc) or [min(nproc, service_threads)]


def model_revisions(profiles, settings):
    """Закреплённые ревизии tiny/base/small из режимов AI и lab.env."""
    found = {}
    for values in [*profiles.values(), settings]:
        size, revision = values.get("AI_MODEL_SIZE"), values.get("AI_MODEL_REVISION")
        if size in MODELS and revision:
            found.setdefault(size, revision)
    return {size: found[size] for size in MODELS if size in found}


def service_spec(inspect):
    """Условия сервиса: образ, лимиты, env и только тома моделей — только для чтения."""
    env = dict(item.split("=", 1) for item in inspect["Config"]["Env"])
    targets = {env.get("AI_MODEL_CACHE"), env.get("AI_TRANSLATION_MODEL_ROOT")} - {None}
    mounts = []
    for mount in inspect.get("Mounts", []):
        if mount["Destination"] not in targets:
            continue
        source = mount["Name"] if mount["Type"] == "volume" else mount["Source"]
        mounts.append(f"type={mount['Type']},src={source},dst={mount['Destination']},readonly")
    # Токен сервиса не нужен: runtime читает пустышку; сети нет — кэш HF только локальный.
    env.update(SERVICE_CONTROL_TOKEN_FILE="/sweep/token", HF_HUB_OFFLINE="1")
    nano = inspect["HostConfig"].get("NanoCpus") or 0
    return {
        "image": inspect["Config"]["Image"],
        "cpus": nano / 1e9 if nano else None,
        "cpuset": inspect["HostConfig"].get("CpusetCpus") or None,
        "memory": inspect["HostConfig"].get("Memory") or None,
        "stt_threads": int(env.get("AI_STT_CPU_THREADS", "4")),
        "model": env.get("AI_MODEL_SIZE"),
        "mounts": mounts,
        "env": [f"{key}={value}" for key, value in env.items()],
    }


def _median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def aggregate(raw, phrases, load):
    """Строки отчёта: медианы времени и CPU, средняя точность по фразам и повторам."""
    texts = {phrase["id"]: phrase["text"] for phrase in phrases}
    groups = {}
    for run in raw["runs"]:
        groups.setdefault((run["model"], run["threads"]), []).append(run)
    rows = []
    for (model, threads), runs in groups.items():
        scores = [accuracy(texts[r["phrase"]], r["transcript"]) for r in runs]
        rows.append({"load": load, "model": model, "threads": threads, "streaming": 0,
                     "n": len(runs), "stt_ms": _median(r["stt_ms"] for r in runs),
                     "translation_ms": _median(r["translation_ms"] for r in runs),
                     "accuracy": round(statistics.fmean(scores), 3),
                     "cpu_ms": _median(r["cpu_ms"] for r in runs),
                     "first_partial_ms": None})  # fmt: skip
    streams = {}
    for run in raw.get("streaming", []):
        streams.setdefault((run["model"], run["threads"]), []).append(run)
    for (model, threads), runs in streams.items():
        rows.append({"load": load, "model": model, "threads": threads, "streaming": 1,
                     "n": len(runs), "stt_ms": None, "translation_ms": None, "accuracy": None,
                     "cpu_ms": None,
                     "first_partial_ms": _median(r["first_partial_ms"] for r in runs)})  # fmt: skip
    return rows


def run(*command, timeout=600):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def prepare_phrases(folder, settings):
    """Эталонные фразы: SIP_UE_TEST_UTTERANCE и русские реплики фикстуры диалога (Piper)."""
    dialogue = json.loads(DIALOGUE.read_text(encoding="utf-8"))
    texts = [settings["SIP_UE_TEST_UTTERANCE"], *dialogue["tracks"]["ue1"]["turns"]]
    if not all((folder / f"p{n}.ulaw").is_file() for n in range(1, len(texts) + 1)):
        for number, wav in enumerate(phrase_wavs(texts, folder), 1):
            (folder / f"p{number}.ulaw").write_bytes(wav_to_pcmu(wav)[0])
    return [{"id": f"p{n}", "file": f"p{n}.ulaw", "text": text,
             "seconds": (folder / f"p{n}.ulaw").stat().st_size / 8000}
            for n, text in enumerate(texts, 1)]  # fmt: skip


def fetch_models(spec, models):
    """Закреплённые tiny/base/small в кэш сервиса: как при старте AI Worker, с сетью.

    Перебор идёт без сети; модель, которой нет в кэше, он пропускает. Ошибка загрузки —
    не обрыв профиля: модель останется SKIP с причиной.
    """
    env = dict(item.split("=", 1) for item in spec["env"])
    cache = env.get("AI_MODEL_CACHE")
    mount = next((m for m in spec["mounts"] if f"dst={cache}," in m), None)
    if not cache or not mount:
        return
    arguments = [item for pair in models.items() for item in pair]
    try:
        result = run("docker", "run", "--rm", "--user", "65532:65532", "--cap-drop", "ALL",
                     "-e", "HOME=/tmp", "-e", f"HF_HUB_DISABLE_XET={env.get('HF_HUB_DISABLE_XET', '1')}",
                     "--mount", mount.replace(",readonly", ""), "--entrypoint", "python",
                     spec["image"], "-c", FETCH, cache, *arguments, timeout=1800)  # fmt: skip
    except subprocess.TimeoutExpired:
        print("WARN: загрузка моделей Whisper не уложилась в 30 мин", flush=True)
        return
    print(result.stdout + result.stderr[-1500:], end="", flush=True)


def finish(path, data, line):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(line, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--load", choices=("idle", "rfsim"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--quick", action="store_true", help="меньше вариантов потоков, без потокового"
    )
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    settings = read_env()
    output = args.out / f"sweep-{args.load}.json"
    skip = {"load": args.load, "status": "skip"}

    inspect = run("docker", "inspect", SERVICE)
    if inspect.returncode or not json.loads(inspect.stdout)[0]["State"]["Running"]:
        return finish(output, {**skip, "reason": f"{SERVICE} не запущен"},
                      f"STEP SKIP: {SERVICE} не запущен")  # fmt: skip
    spec = service_spec(json.loads(inspect.stdout)[0])
    folder = args.out / "sweep"
    folder.mkdir(parents=True, exist_ok=True)
    phrases = prepare_phrases(folder, settings)
    profiles = json.loads((ROOT / "app/config/ai-profiles.json").read_text(encoding="utf-8"))
    fetch_models(spec, model_revisions(profiles, settings))
    nproc = os.cpu_count()
    plan = {
        "phrases": phrases,
        "models": model_revisions(profiles, settings),
        "threads": plan_threads(nproc, spec["stt_threads"], args.quick),
        "default_threads": spec["stt_threads"],
        "streaming": not args.quick,
        "repeats": args.repeats,
        "stream_interval_ms": int(settings["AI_STREAM_INTERVAL_MS"]),
        "holdback": int(settings["AI_STREAM_HOLDBACK_WORDS"]),
    }
    (folder / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    (folder / "token").write_text("profile-sweep\n", encoding="ascii")
    env_file = folder / f"service-{args.load}.env"
    env_file.write_text("".join(f"{line}\n" for line in spec["env"]), encoding="utf-8")

    # Те же ограничения, что у сервиса: лимит и ядра CPU, память, без сети, только чтение.
    command = ["docker", "run", "--rm", "--name", f"lab-profile-sweep-{args.load}",
               "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
               "--user", "65532:65532", "--cap-drop", "ALL", "--security-opt",
               "no-new-privileges:true", "--env-file", str(env_file)]  # fmt: skip
    if spec["cpus"]:
        command += ["--cpus", f"{spec['cpus']:g}"]
    if spec.get("cpuset"):
        command += ["--cpuset-cpus", spec["cpuset"]]
    if spec["memory"]:
        command += ["--memory", str(spec["memory"])]
    for mount in spec["mounts"]:
        command += ["--mount", mount]
    command += ["-v", f"{folder}:/sweep:ro", "-v", f"{WORKER}:/sweep-code/sweep_worker.py:ro",
                "--entrypoint", "python", spec["image"], "/sweep-code/sweep_worker.py",
                "/sweep/plan.json"]  # fmt: skip
    print(f"{args.load}: образ {spec['image']}, CPU {spec['cpus']}, ядра {spec.get('cpuset') or 'все'}, модели "
          f"{', '.join(plan['models'])}, потоки {plan['threads']}", flush=True)  # fmt: skip
    result = run(*command, timeout=5400)
    print(result.stderr[-3000:], end="", flush=True)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError(f"контейнер перебора завершился с кодом {result.returncode}")
    raw = json.loads(result.stdout.strip().splitlines()[-1])

    rows = aggregate(raw, phrases, args.load)
    data = {"load": args.load, "status": "done", "service": {k: v for k, v in spec.items()
            if k != "env"}, "plan": plan, "models": raw["models"],
            "translation": raw["translation"], "rows": rows, "raw": raw}  # fmt: skip
    if not rows:
        return finish(output, {**data, "status": "skip", "reason": "нет ни одной модели в кэше"},
                      "STEP SKIP: нет ни одной модели Whisper в кэше")  # fmt: skip
    finish(output, data, f"SWEEP {args.load}: DONE ({len(rows)} вариантов)")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
