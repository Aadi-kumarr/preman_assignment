"""Audio timing metrics computed from saved events. Pure functions, no I/O.

Two metrics, both on the target's own clock (simulated for the supplied target):

- first_audio_playback_ms: user_utterance_end -> first_audio_played, per audio turn
- interruption_stop_ms:    user_speech_start  -> playback_stopped,  per interrupt

Events are correlated by session_id, turn_id and response_id, never by their
position in a list. A missing event makes the metric ``unavailable``; mismatched
IDs, conflicting duplicates, different clocks, or an end before its start make
it ``incompatible``. Neither is ever reported as zero.
"""
import math

FIRST_PLAYBACK = "first_audio_playback_ms"
INTERRUPTION_STOP = "interruption_stop_ms"
ID_FIELDS = ("session_id", "turn_id", "response_id")


def _events_of(record):
    body = record.get("body") if isinstance(record, dict) else None
    events = body.get("events") if isinstance(body, dict) else None
    return [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []


def collect_events(evidence):
    """Every event seen in turn responses, interrupt responses and the trace.

    The same event (same session and event_id) usually appears twice, once in a
    response and once in the trace; it is kept once. If two copies of one
    event_id disagree, the id is returned in ``conflicts``.
    """
    seen, order, conflicts = {}, [], set()
    records = list(evidence.get("turns") or []) + [evidence.get("trace") or {}]
    for record in records:
        for event in _events_of(record):
            key = (event.get("session_id"), event.get("event_id"))
            if event.get("event_id") is None:
                key = ("no-event-id", len(order))
            if key in seen:
                if seen[key] != event:
                    conflicts.add(key)
            else:
                seen[key] = event
                order.append(key)
    return [seen[key] for key in order], conflicts


def _pick(kind, scope, events, conflicts, own_events):
    """Find the single ``kind`` event for a scope. Returns (event, status, problems, deduped)."""
    related = [e for e in events if e.get("kind") == kind
               and (e.get("turn_id") == scope["turn_id"] or e.get("response_id") == scope["response_id"])]
    if not related:
        # Nothing matches the scope. If this very request returned such an event for some other
        # turn or response, that is an ID mismatch rather than missing telemetry.
        related = [e for e in own_events if e.get("kind") == kind]
    if not related:
        return None, "unavailable", ["no %s event for %s/%s" % (kind, scope["turn_id"], scope["response_id"])], 0
    for event in related:
        wrong = ["%s=%r (expected %r)" % (f, event.get(f), scope[f]) for f in ID_FIELDS if event.get(f) != scope[f]]
        if wrong:
            return None, "incompatible", ["%s event %s has mismatched IDs: %s" % (kind, event.get("event_id"), ", ".join(wrong))], 0
        if (event.get("session_id"), event.get("event_id")) in conflicts:
            return None, "incompatible", ["event %s was reported with conflicting contents" % event.get("event_id")], 0
    readings = {repr((e.get("at_ms"), e.get("clock_domain"), e.get("timing_source"))) for e in related}
    if len(readings) > 1:
        return None, "incompatible", ["conflicting duplicate %s events: %s" % (kind, ", ".join(
            "%s at %r ms" % (e.get("event_id"), e.get("at_ms")) for e in related))], 0
    event = related[0]
    at_ms = event.get("at_ms")
    if isinstance(at_ms, bool) or not isinstance(at_ms, (int, float)) or not math.isfinite(at_ms):
        return None, "incompatible", ["%s event %s has an unusable timestamp %r" % (kind, event.get("event_id"), at_ms)], 0
    return event, "ok", [], len(related) - 1


def _pair(metric, turn_index, scope, start_kind, end_kind, events, conflicts, own_events, extra=None):
    result = {"metric": metric, "turn_index": turn_index, "scope": scope, "status": "ok", "value_ms": None,
              "from": None, "to": None, "clock_domain": None, "timing_source": None, "label": "unknown",
              "duplicate_events_deduped": 0, "problems": []}
    result.update(extra or {})
    if scope is None:
        result["status"] = "unavailable"
        return result
    picked = {}
    for kind in (start_kind, end_kind):
        event, status, problems, deduped = _pick(kind, scope, events, conflicts, own_events)
        picked[kind] = event
        result["problems"] += problems
        result["duplicate_events_deduped"] += deduped
        if status == "incompatible" or (status == "unavailable" and result["status"] == "ok"):
            result["status"] = status
    start, end = picked[start_kind], picked[end_kind]
    for name, event in (("from", start), ("to", end)):
        if event is not None:
            result[name] = {"kind": event.get("kind"), "event_id": event.get("event_id"), "at_ms": event.get("at_ms")}
    if result["status"] != "ok":
        return result
    for field in ("clock_domain", "timing_source"):
        if start.get(field) != end.get(field):
            result["status"] = "incompatible"
            result["problems"].append("%s differs between %s (%r) and %s (%r)" % (
                field, start_kind, start.get(field), end_kind, end.get(field)))
    if result["status"] != "ok":
        return result
    result["clock_domain"], result["timing_source"] = start.get("clock_domain"), start.get("timing_source")
    result["label"] = start.get("timing_source") or "unknown"
    value = end["at_ms"] - start["at_ms"]
    if value < 0:
        result["status"] = "incompatible"
        result["problems"].append("impossible timestamps: %s at %s ms is before %s at %s ms" % (
            end_kind, end["at_ms"], start_kind, start["at_ms"]))
        return result
    result["value_ms"] = value
    return result


def compute_audio_metrics(evidence):
    """Return ``{"first_audio_playback_ms": [...], "interruption_stop_ms": [...]}``.

    One entry per audio turn and per interrupt action, in scenario order.
    """
    events, conflicts = collect_events(evidence)
    session = evidence.get("session") or {}
    session_id = (session.get("body") or {}).get("session_id") if isinstance(session.get("body"), dict) else None
    first, stops = [], []
    last_scope, last_index = None, None
    for turn in evidence.get("turns") or []:
        kind, index = turn.get("type"), turn.get("index")
        body = turn.get("body") if isinstance(turn.get("body"), dict) else {}
        answered = turn.get("outcome") == "ok"
        if kind in ("audio", "text") and answered:
            # The scope is this session plus the turn and response the target named in its reply.
            last_scope = {"session_id": session_id, "turn_id": body.get("turn_id"), "response_id": body.get("response_id")}
            last_index = index
        if kind == "audio":
            if answered:
                metric = _pair(FIRST_PLAYBACK, index, last_scope, "user_utterance_end", "first_audio_played",
                               events, conflicts, _events_of(turn))
                if body.get("session_id") != session_id:
                    metric["status"], metric["value_ms"] = "incompatible", None
                    metric["problems"].append("turn response names session %r, expected %r" % (body.get("session_id"), session_id))
            else:
                metric = _pair(FIRST_PLAYBACK, index, None, None, None, events, conflicts, [])
                metric["problems"].append("audio turn has no response (%s)" % turn.get("outcome"))
            first.append(metric)
        elif kind == "interrupt":
            extra = {"interrupts_turn_index": last_index}
            if not answered:
                metric = _pair(INTERRUPTION_STOP, index, None, None, None, events, conflicts, [], extra)
                metric["problems"].append("interrupt request has no response (%s)" % turn.get("outcome"))
            elif last_scope is None:
                metric = _pair(INTERRUPTION_STOP, index, None, None, None, events, conflicts, [], extra)
                metric["problems"].append("no answered turn precedes this interrupt")
            else:
                metric = _pair(INTERRUPTION_STOP, index, last_scope, "user_speech_start", "playback_stopped",
                               events, conflicts, _events_of(turn), extra)
            stops.append(metric)
    return {FIRST_PLAYBACK: first, INTERRUPTION_STOP: stops}
