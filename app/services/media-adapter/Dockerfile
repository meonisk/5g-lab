FROM python:3.13.7-alpine3.22@sha256:9ba6d8cbebf0fb6546ae71f2a1c14f6ffd2fdab83af7fa5669734ef30ad48844
WORKDIR /app
COPY adapter.py /app/adapter.py
COPY ims_media /app/ims_media
ENTRYPOINT ["python", "/app/adapter.py"]
