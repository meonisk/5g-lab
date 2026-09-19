FROM python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-http.txt /app/requirements-http.txt
RUN pip install --no-cache-dir -r /app/requirements-http.txt
ARG PIPER_VERSION
RUN pip install --no-cache-dir piper-tts==${PIPER_VERSION}
ARG PIPER_MODEL_URL
ARG PIPER_MODEL_SHA256
ARG PIPER_CONFIG_SHA256
ARG PIPER_MODEL_PATH
ARG PIPER_EN_MODEL_URL
ARG PIPER_EN_MODEL_SHA256
ARG PIPER_EN_CONFIG_SHA256
ARG PIPER_EN_MODEL_PATH
COPY voice-agent/prepare_voice.py /app/prepare_voice.py
RUN python /app/prepare_voice.py
COPY lab_common /app/lab_common
COPY voice-agent/agent.py /app/agent.py
COPY voice-agent/ims_voice /app/ims_voice
ENTRYPOINT ["python", "/app/agent.py"]
