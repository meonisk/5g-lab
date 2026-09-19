"""Bounded utterance queue and parallel per-call-safe inference workers."""

import queue
import threading
import time

from . import runtime
from .utterances import process_utterance


def enqueue_utterance(ulaw, event, received_at, end_reason):
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else "unbound"
    task = {
        "ulaw": ulaw,
        "event": event,
        "received_at": received_at,
        "end_reason": end_reason,
        "queued_at": time.time(),
        "call_id": call_id,
    }
    with runtime.pending_condition:
        runtime.pending_utterances[call_id] = runtime.pending_utterances.get(call_id, 0) + 1
        runtime.call_locks.setdefault(call_id, threading.Lock())
    try:
        runtime.utterance_work.put_nowait(task)
    except queue.Full:
        with runtime.pending_condition:
            runtime.pending_utterances[call_id] -= 1
            runtime.pending_condition.notify_all()
        raise


def wait_for_call(call_id):
    with runtime.pending_condition:
        while runtime.pending_utterances.get(call_id, 0):
            runtime.pending_condition.wait(timeout=1)


def process_utterances():
    while True:
        task = runtime.utterance_work.get()
        call_id = task["call_id"]
        try:
            with runtime.call_locks[call_id]:
                process_utterance(
                    task["ulaw"],
                    task["event"],
                    task["received_at"],
                    task["end_reason"],
                    task["queued_at"],
                )
        except Exception as exc:
            print(f"AI utterance_failed type={type(exc).__name__} error={exc}", flush=True)
        finally:
            with runtime.pending_condition:
                remaining = runtime.pending_utterances.get(call_id, 1) - 1
                if remaining:
                    runtime.pending_utterances[call_id] = remaining
                else:
                    runtime.pending_utterances.pop(call_id, None)
                runtime.pending_condition.notify_all()
            runtime.utterance_work.task_done()
