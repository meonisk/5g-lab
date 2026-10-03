"""Единая UTF-8 кодировка русских сообщений в терминале и перенаправленных журналах."""

import os
import sys


def configure_output():
    # Дочерние Python-команды должны писать в той же кодировке, что и запускатель.
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
