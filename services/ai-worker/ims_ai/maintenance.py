"""Expire bounded transient state without persisting speech content."""

from __future__ import annotations

from . import runtime, settings


def expire_events(now):
    runtime.events[:] = [
        item
        for item in runtime.events
        if now - item.get("processed_at", now) <= settings.retention_seconds
    ]
    del runtime.events[: -settings.event_retention]


def expire_transient(now):
    for stale_key in [
        key
        for key, value in runtime.buffers.items()
        if now - value["last_seen"] > settings.buffer_ttl
    ]:
        runtime.buffers.pop(stale_key, None)
    for call_id in [
        key
        for key, value in runtime.conversations.items()
        if now - value["last_seen"] > settings.conversation_ttl
    ]:
        runtime.conversations.pop(call_id, None)
        runtime.reply_counts.pop(call_id, None)
        runtime.turn_counts.pop(call_id, None)
