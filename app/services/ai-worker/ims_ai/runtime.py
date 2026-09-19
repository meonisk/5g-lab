"""Mutable state owned by one worker process; pipeline modules share this instance."""

import os
import queue
import re
import threading

from . import settings

events = []
buffers = {}
lock = threading.Lock()
work = queue.Queue(maxsize=settings.queue_max)
utterance_work = queue.Queue(maxsize=settings.utterance_queue_max)
model = None
model_error = None
reply_counts = {}
turn_counts = {}
conversations = {}
recordings = {}
active_calls = {}
pending_utterances = {}
call_locks = {}
pending_condition = threading.Condition(lock)
call_id_pattern = re.compile(r"^[A-Za-z0-9_.+~-]{1,128}$")
with open(os.environ["SERVICE_CONTROL_TOKEN_FILE"], encoding="ascii") as token_source:
    control_token = token_source.read().strip()
