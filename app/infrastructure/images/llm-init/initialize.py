"""Download a pinned Unsloth GGUF; import locally without inference or credentials."""

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def verified_blob():
    digest = os.environ["LLM_GGUF_SHA256"]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("LLM_GGUF_SHA256 must be a full SHA-256")
    blob = Path("/root/.ollama/models/blobs") / ("sha256-" + digest)
    blob.parent.mkdir(parents=True, exist_ok=True)

    # Recheck cached bytes, not just existence: a partial or corrupted download
    # must never become an apparently successful model initialization.
    if blob.exists():
        with blob.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == digest:
                return digest

    partial = blob.with_suffix(".partial")
    checksum = hashlib.sha256()
    url = os.environ["LLM_GGUF_URL"]
    if not url.startswith("https://huggingface.co/unsloth/"):
        raise ValueError("Expected a pinned HTTPS Unsloth model URL")
    print("Downloading pinned GGUF", flush=True)
    with urllib.request.urlopen(url, timeout=120) as source, partial.open("wb") as target:
        while chunk := source.read(4 * 1024 * 1024):
            checksum.update(chunk)
            target.write(chunk)
    if checksum.hexdigest() != digest:
        partial.unlink()
        raise ValueError("GGUF SHA-256 mismatch; model not imported")
    partial.replace(blob)
    return digest


def main():
    digest = verified_blob()
    server = subprocess.Popen(["/bin/ollama", "serve"])
    try:
        endpoint = "http://127.0.0.1:11434"
        for _ in range(60):
            try:
                with urllib.request.urlopen(endpoint + "/api/version", timeout=1):
                    break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Initializer Ollama did not start")

        # Ollama reads GGUF tokenizer metadata and selects its native chat
        # template; no model-specific prompt template is duplicated here.
        payload = {
            "model": os.environ["LLM_MODEL"],
            "files": {"model.gguf": "sha256:" + digest},
            "stream": False,
        }
        request = urllib.request.Request(
            endpoint + "/api/create",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.load(response)
        if result.get("status") != "success":
            raise RuntimeError(f"Import failed: {result}")
        print(f"Verified and imported {os.environ['LLM_MODEL']} sha256={digest}")
    finally:
        server.terminate()
        server.wait(timeout=30)


if __name__ == "__main__":
    main()
