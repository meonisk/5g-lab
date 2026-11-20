# Захват SIP для панели: только стандартная библиотека Python.
FROM python:3.13.7-alpine3.22@sha256:9ba6d8cbebf0fb6546ae71f2a1c14f6ffd2fdab83af7fa5669734ef30ad48844
COPY sipcap.py /app/sipcap.py
# AF_PACKET требует NET_RAW у процесса: root внутри, остальные способности сняты
# при запуске (--cap-drop ALL --cap-add NET_RAW), файловая система только для чтения.
ENTRYPOINT ["python", "-u", "/app/sipcap.py"]
