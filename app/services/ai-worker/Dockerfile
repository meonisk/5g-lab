FROM python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY worker.py /app/worker.py
COPY ims_ai /app/ims_ai
RUN mkdir -p /models && chown 65532:65532 /models
USER 65532:65532
ENTRYPOINT ["python", "/app/worker.py"]
