"""Диалоги, созданные самим SIP AS (нога B), и звонки, помеченные record AS."""

import secrets

from .. import runtime


def new_call_id() -> str:
    """Call-ID ноги B без '@': проходит valid_call_id Media Adapter и Voice Agent."""
    call_id = "b2b-" + secrets.token_hex(12)
    runtime.own_call_ids.add(call_id)
    return call_id


def is_own(call_id: str) -> bool:
    return call_id in runtime.own_call_ids


def forget(call_id: str) -> None:
    runtime.own_call_ids.discard(call_id)
    runtime.record_marks.discard(call_id)


def mark_record(call_id: str) -> None:
    runtime.record_marks.add(call_id)


def is_marked_record(call_id: str) -> bool:
    return call_id in runtime.record_marks
