ARG OLLAMA_IMAGE
FROM ${OLLAMA_IMAGE} AS ollama
FROM python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1
COPY --from=ollama /bin/ollama /bin/ollama
COPY initialize.py /app/initialize.py
ENTRYPOINT ["python", "-u", "/app/initialize.py"]
