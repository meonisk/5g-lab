"""Подготовить две локальные OPUS-MT int8 модели; PyTorch нужен только здесь."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "ru-en": ("Helsinki-NLP/opus-mt-ru-en", "fbd6dc73284f95536648512cc21d57f19191961a"),
    "en-ru": ("Helsinki-NLP/opus-mt-en-ru", "bb09c99d180016eac6819df3dae68edb1690fdee"),
}


def prepare(destination):
    from ctranslate2.converters import TransformersConverter
    from huggingface_hub import snapshot_download

    for direction, (repository, revision) in MODELS.items():
        target = destination / direction
        if target.exists():
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if manifest["revision"] != revision or manifest["quantization"] != "int8":
                raise ValueError(f"Несовместимая модель: {target}")
            for name, digest in manifest["files"].items():
                if hashlib.sha256((target / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f"Повреждён файл: {target / name}")
            print(f"OPUS MODEL VERIFIED: {direction}", flush=True)
            continue

        source = snapshot_download(
            repository,
            revision=revision,
            cache_dir=str(ROOT / "local/benchmarks/cpu-ai/hf-cache"),
            allow_patterns=[
                "config.json",
                "pytorch_model.bin",
                "*.spm",
                "*vocab*",
                "tokenizer_config.json",
            ],
        )
        staging = destination / (direction + ".preparing")
        if staging.exists():
            raise ValueError(f"Незавершённая конверсия; проверьте каталог: {staging}")
        TransformersConverter(source).convert(str(staging), quantization="int8")
        for name in ("source.spm", "target.spm"):
            shutil.copyfile(Path(source) / name, staging / name)
        manifest = {
            "repository": repository,
            "revision": revision,
            "quantization": "int8",
            "converter_version": importlib.metadata.version("ctranslate2"),
            "files": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in staging.iterdir()
                if path.is_file()
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        staging.rename(target)
        print(f"OPUS MODEL READY: {direction}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    destination = ROOT / "local/models/opus-mt"
    destination.mkdir(parents=True, exist_ok=True)
    prepare(destination)


if __name__ == "__main__":
    main()
