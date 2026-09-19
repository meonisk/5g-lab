"""Experimental local-agreement ASR: translate stable prefixes, never cut PCM words."""

import re
import time
from dataclasses import replace

from . import runtime, settings


def tokens(text):
    return [re.sub(r"[^\w]", "", word).casefold() for word in text.split()]


def stable_prefix(previous, current, final=False, holdback=1):
    """Final audio releases the remaining suffix; live audio needs two matching hypotheses."""
    current_words = current.split()
    if final:
        return current_words
    matching = 0
    for old, new in zip(tokens(previous), tokens(current)):
        if old != new:
            break
        matching += 1
    # Hold the end of the CURRENT hypothesis, not the end of an already
    # confirmed prefix. A changing name must not block a stable greeting.
    return current_words[: min(matching, max(0, len(current_words) - holdback))]


def process_snapshot(task):
    # Imported lazily to keep the assembler -> queue -> recognition dependency acyclic.
    from .utterances import process_utterance, recognize

    identity = (task.call_id, task.event["stream_phrase_id"])
    state = runtime.stream_hypotheses.setdefault(identity, {"previous": "", "committed": ""})
    final = task.end_reason != "stream-partial"
    processing_started_at = time.time()
    recognition = recognize(task.pcmu_audio, task.event["service_mode"])
    current = recognition.transcript
    prefix = stable_prefix(state["previous"], current, final, settings.stream_holdback_words)
    state["previous"] = current
    committed = tokens(state["committed"])
    # A revision of already spoken text cannot be repaired by silently repeating
    # the whole sentence. Flag the disagreement instead of pretending success.
    conflict = bool(committed and tokens(current)[: len(committed)] != committed)
    suffix = prefix[len(committed) :] if not conflict else []
    if suffix and (final or len(suffix) >= settings.stream_min_words):
        result = process_utterance(
            task.pcmu_audio,
            task.event,
            task.received_at,
            task.end_reason,
            task.queued_at,
            recognition_override=replace(recognition, transcript=" ".join(suffix)),
            processing_started_at=processing_started_at,
        )
        state["delivery_failed"] = state.get("delivery_failed", False) or not result.get(
            "reply_delivered"
        )
        state["committed"] = " ".join(prefix)
    if final:
        with runtime.lock:
            runtime.events.append(
                {
                    "event": "stream_finalized",
                    "processed_at": time.time(),
                    "call_ids": [task.call_id],
                    "stream_phrase_id": task.event["stream_phrase_id"],
                    "stream_conflict": conflict or state.get("delivery_failed", False),
                    "source_words": len(tokens(current)),
                    "committed_words": len(tokens(state["committed"])),
                }
            )
        runtime.stream_hypotheses.pop(identity, None)
        if conflict or state.get("delivery_failed", False):
            print("AI streaming_incomplete: revision or delivery failure; not accepted", flush=True)
