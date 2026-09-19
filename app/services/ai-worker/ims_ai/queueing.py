"""Готовые реплики ждут в ограниченной очереди; звонки обрабатываются параллельно."""

import queue
import threading
import time
from dataclasses import dataclass

from . import runtime
from .utterances import process_utterance


@dataclass(frozen=True)
class UtteranceTask:
    """Явные поля задания вместо словаря со строковыми ключами."""

    ulaw: bytes
    event: dict
    received_at: float
    end_reason: str
    queued_at: float
    call_id: str


def enqueue_utterance(ulaw, event, received_at, end_reason):
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else "unbound"
    task = UtteranceTask(ulaw, event, received_at, end_reason, time.time(), call_id)
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
    """BYE завершает запись только после всех уже принятых реплик этого звонка."""
    with runtime.pending_condition:
        runtime.pending_condition.wait_for(lambda: not runtime.pending_utterances.get(call_id, 0))


def process_utterances():
    while True:
        task = runtime.utterance_work.get()
        call_id = task.call_id
        try:
            # Историю одного звонка меняет только один worker в каждый момент.
            with runtime.call_locks[call_id]:
                process_utterance(
                    task.ulaw,
                    task.event,
                    task.received_at,
                    task.end_reason,
                    task.queued_at,
                )
        except Exception as exc:
            print(f"AI utterance_failed type={type(exc).__name__}", flush=True)
        finally:
            with runtime.pending_condition:
                remaining = runtime.pending_utterances.get(call_id, 1) - 1
                if remaining:
                    runtime.pending_utterances[call_id] = remaining
                else:
                    runtime.pending_utterances.pop(call_id, None)
                runtime.pending_condition.notify_all()
            runtime.utterance_work.task_done()
