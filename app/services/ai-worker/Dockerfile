FROM python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY ai-worker/requirements.txt /app/requirements.txt
COPY requirements-http.txt /app/requirements-http.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/requirements-http.txt
COPY lab_common /app/lab_common
COPY ai-worker/worker.py /app/worker.py
COPY ai-worker/ims_ai /app/ims_ai
RUN mkdir -p /models && chown 65532:65532 /models
USER 65532:65532
ENTRYPOINT ["python", "/app/worker.py"]
