FROM python:3.13.7-alpine3.22@sha256:9ba6d8cbebf0fb6546ae71f2a1c14f6ffd2fdab83af7fa5669734ef30ad48844
RUN apk add --no-cache espeak-ng ffmpeg
WORKDIR /app
COPY requirements-http.txt /app/requirements-http.txt
RUN pip install --no-cache-dir -r /app/requirements-http.txt
COPY lab_common /app/lab_common
COPY voice-agent/agent.py /app/agent.py
COPY voice-agent/ims_voice /app/ims_voice
ENTRYPOINT ["python", "/app/agent.py"]
