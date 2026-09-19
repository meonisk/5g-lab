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

    pcmu_audio: bytes
    event: dict
    received_at: float
    end_reason: str
    queued_at: float
    call_id: str


def enqueue_utterance(pcmu_audio, event, received_at, end_reason):
    """Зарегистрировать ожидающую работу до помещения задания в очередь."""
    call_ids = event.get("call_ids") or []
    call_id = call_ids[0] if len(call_ids) == 1 else "unbound"
    task = UtteranceTask(
        pcmu_audio=pcmu_audio,
        event=event,
        received_at=received_at,
        end_reason=end_reason,
        queued_at=time.time(),
        call_id=call_id,
    )

    with runtime.pending_condition:
        runtime.pending_utterances[call_id] = runtime.pending_utterances.get(call_id, 0) + 1
        runtime.call_locks.setdefault(call_id, threading.Lock())

    try:
        runtime.utterance_work.put_nowait(task)
    except queue.Full:
        # Счётчик обязан соответствовать очереди, иначе BYE будет ждать вечно.
        with runtime.pending_condition:
            runtime.pending_utterances[call_id] -= 1
            runtime.pending_condition.notify_all()
        raise


def wait_for_call(call_id):
    """BYE завершает запись только после всех уже принятых реплик этого звонка."""
    with runtime.pending_condition:
        runtime.pending_condition.wait_for(lambda: not runtime.pending_utterances.get(call_id, 0))


def mark_task_finished(call_id: str) -> None:
    """Уменьшить счётчик и разбудить ожидающий завершения BYE."""
    with runtime.pending_condition:
        remaining_tasks = runtime.pending_utterances.get(call_id, 1) - 1

        if remaining_tasks:
            runtime.pending_utterances[call_id] = remaining_tasks
        else:
            runtime.pending_utterances.pop(call_id, None)

        runtime.pending_condition.notify_all()


def process_utterances():
    """Обрабатывать разные звонки параллельно, а один звонок — последовательно."""
    while True:
        task = runtime.utterance_work.get()

        try:
            # Историю одного звонка меняет только один worker в каждый момент.
            with runtime.call_locks[task.call_id]:
                if "stream_phrase_id" in task.event:
                    from .streaming import process_snapshot

                    process_snapshot(task)
                else:
                    process_utterance(
                        task.pcmu_audio,
                        task.event,
                        task.received_at,
                        task.end_reason,
                        task.queued_at,
                    )
        except Exception as error:
            print(
                f"AI utterance_failed type={type(error).__name__}",
                flush=True,
            )
        finally:
            mark_task_finished(task.call_id)
            runtime.utterance_work.task_done()
