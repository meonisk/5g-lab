"""Streaming acceptance uses phrase identities and start-of-speech, not fragment counts."""


def finalized(events, calls):
    return [
        event
        for event in events
        if event.get("event") == "stream_finalized"
        and any(call in calls.values() for call in event.get("call_ids", []))
    ]


def all_audio_sent(voice_events, source_events):
    expected = {event["reply_id"] for event in source_events}
    sent = {event.get("reply_id") for event in voice_events if event.get("event") == "tts_sent"}
    return bool(expected) and expected <= sent


def acceptance(rows, endings, limit):
    first_by_phrase = {}
    for row in rows:
        key = row.get("stream_phrase_id")
        delay = row.get("speech_start_to_audible_rtp_ms")
        if key and delay is not None:
            first_by_phrase[key] = min(first_by_phrase.get(key, delay), delay)
    complete = len(endings) == 4 and all(
        not event["stream_conflict"]
        and event["source_words"] > 0
        and event["source_words"] == event["committed_words"]
        for event in endings
    )
    return {
        "phrase_start_delays_ms": first_by_phrase,
        "source_text_coverage_pass": complete,
        "start_latency_pass": len(first_by_phrase) == 4
        and all(0 <= delay <= limit for delay in first_by_phrase.values()),
        "limit_ms": limit,
        "boundary": "first source speech capture to first audible translated RTP sent; NOT handset playback",
        "finalized": endings,
    }
