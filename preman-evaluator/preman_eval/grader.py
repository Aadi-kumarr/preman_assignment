"""Evidence-based grading. Pure functions: saved evidence in, verdict out.

Nothing here reads the scenario id, run id, variant, or fixture name. A verdict
comes only from the scenario's ``expect`` block, its deadline, and what was
observed (authoritative state, audit log, turn outcomes, timing events).

Precedence: FAIL > ERROR > INCONCLUSIVE > PASS. Every reason is kept, so a
verified failure stands even when a timeout, harness error, or missing
evidence is also present.
"""
from datetime import datetime

from .metrics import FIRST_PLAYBACK, INTERRUPTION_STOP, compute_audio_metrics

PRECEDENCE = ("FAIL", "ERROR", "INCONCLUSIVE", "PASS")
_RANK = {verdict: rank for rank, verdict in enumerate(reversed(PRECEDENCE))}

# What kind of problem each reason code is; used to keep policy failures visible in reports.
CATEGORIES = {
    "timeout": "deadline",
    "booking_count_mismatch": "business_state", "booking_customer_mismatch": "business_state",
    "booking_starts_at_mismatch": "business_state", "address_mismatch": "business_state",
    "unconfirmed_write": "policy", "write_without_user_confirmation": "policy",
    "write_turn_uncorrelated": "evidence", "confirmation_unverifiable": "evidence",
    "state_evidence_missing": "evidence", "evidence_missing": "evidence",
    "response_audio_missing": "evidence", "response_audio_unplayable": "evidence",
    "first_audio_playback_over_limit": "audio_metric", "interruption_stop_over_limit": "audio_metric",
    "first_audio_playback_unavailable": "evidence", "interruption_stop_unavailable": "evidence",
    "first_audio_playback_incompatible": "evidence", "interruption_stop_incompatible": "evidence",
}  # anything else (state_read_failed, turn_failed, ...) is "harness"


def worst(verdicts, default="PASS"):
    verdicts = [v for v in verdicts if v is not None]
    return max(verdicts, key=_RANK.__getitem__) if verdicts else default


def normalize_utterance(text):
    return " ".join(str(text).lower().strip().rstrip(".!?").split())


def _same_instant(expected, observed):
    """Compare timestamps as instants when both parse; otherwise as exact strings."""
    if expected == observed:
        return True
    try:
        left = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        return left == right
    except (ValueError, TypeError):
        return False


class _Context:
    def __init__(self, scenario, evidence, policy, ref):
        self.scenario, self.evidence, self.policy, self.ref = scenario, evidence, policy, ref
        self.turns = evidence.get("turns") or []
        self.metrics = compute_audio_metrics(evidence)

    def at(self, pointer):
        return "%s#%s" % (self.ref, pointer)

    def state(self):
        """Return ``(state_body, None)`` or ``(None, reason)`` when it cannot be used."""
        record = self.evidence.get("state") or {}
        outcome = record.get("outcome")
        if outcome == "ok" and isinstance(record.get("body"), dict):
            return record["body"], None
        if outcome in ("http_error", "timeout", "transport_error"):
            body = record.get("body") if isinstance(record.get("body"), dict) else {}
            detail = "HTTP %s" % record["status"] if "status" in record else record.get("error", outcome)
            code = (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None
            return None, _reason("state_read_failed", "ERROR",
                                 "Authoritative state read failed (%s%s); the trace is not authoritative and is not used instead."
                                 % (detail, ", " + code if code else ""), [self.at("/state")])
        return None, _reason("state_evidence_missing", "INCONCLUSIVE",
                             "No authoritative state was read for this attempt.", [self.at("/state")])


def _reason(code, verdict, message, evidence):
    return {"code": code, "verdict": verdict, "category": CATEGORIES.get(code, "harness"),
            "message": message, "evidence": list(evidence)}


def _check(name, expected, observed, reasons):
    return {"check": name, "verdict": worst(r["verdict"] for r in reasons), "expected": expected,
            "observed": observed, "reasons": reasons}


def _trace_tool_results(ctx):
    """Supplementary, non-authoritative: how many tool results refer to how many bookings."""
    trace = ctx.evidence.get("trace") or {}
    events = (trace.get("body") or {}).get("events") if trace.get("outcome") == "ok" else None
    if not isinstance(events, list):
        return None
    results = [e for e in events if isinstance(e, dict) and e.get("kind") == "tool_result"]
    return {"events": len(results), "distinct_booking_ids": len({e.get("booking_id") for e in results}),
            "authoritative": False}


def check_booking(expected, ctx):
    state, problem = ctx.state()
    if problem:
        return _check("booking", expected, None, [problem])
    bookings = state.get("bookings")
    if not isinstance(bookings, list):
        return _check("booking", expected, None, [_reason(
            "state_evidence_missing", "INCONCLUSIVE", "State has no bookings list.", [ctx.at("/state/body")])])
    refs = [ctx.at("/state/body/bookings")]
    observed = {"count": len(bookings), "bookings": bookings, "trace_tool_results": _trace_tool_results(ctx)}
    reasons = []
    if len(bookings) != expected["count"]:
        kind = "more" if len(bookings) > expected["count"] else "fewer"
        reasons.append(_reason("booking_count_mismatch", "FAIL",
                               "Expected %d persisted booking(s), authoritative state has %d (%s than expected)."
                               % (expected["count"], len(bookings), kind), refs))
    for index, booking in enumerate(bookings):
        booking = booking if isinstance(booking, dict) else {}
        where = [ctx.at("/state/body/bookings/%d" % index)]
        if "customer_id" in expected and booking.get("customer_id") != expected["customer_id"]:
            reasons.append(_reason("booking_customer_mismatch", "FAIL", "Booking %s has customer_id %r, expected %r."
                                   % (booking.get("id"), booking.get("customer_id"), expected["customer_id"]), where))
        if "starts_at" in expected and not _same_instant(expected["starts_at"], booking.get("starts_at")):
            reasons.append(_reason("booking_starts_at_mismatch", "FAIL", "Booking %s starts_at %r, expected %r."
                                   % (booking.get("id"), booking.get("starts_at"), expected["starts_at"]), where))
    return _check("booking", expected, observed, reasons)


def check_address(expected, ctx):
    state, problem = ctx.state()
    if problem:
        return _check("address", expected, None, [problem])
    if "address" not in state:
        return _check("address", expected, None, [_reason(
            "state_evidence_missing", "INCONCLUSIVE", "State has no address.", [ctx.at("/state/body")])])
    reasons = []
    if state["address"] != expected:
        reasons.append(_reason("address_mismatch", "FAIL", "Final address is %r, expected %r."
                               % (state["address"], expected), [ctx.at("/state/body/address")]))
    return _check("address", expected, state["address"], reasons)


def _user_utterance(turn):
    """What the user said in a turn: the text sent, or the manifest script of the WAV sent."""
    request = turn.get("request") or {}
    if turn.get("type") == "text":
        return request.get("text")
    if turn.get("type") == "audio":
        return request.get("utterance_text")
    return None


def check_no_write_without_confirmation(expected, ctx):
    """Every audited write needs ``confirmed: true`` AND an earlier user confirmation turn.

    "Earlier" means a confirmation turn at or before the turn the write was
    committed in: the user's confirmation is the input of the turn that commits.
    """
    name = "no_write_without_confirmation"
    if expected is not True:
        return {"check": name, "verdict": None, "expected": expected, "observed": None, "reasons": [],
                "note": "not applied: expectation is false"}
    state, problem = ctx.state()
    if problem:
        return _check(name, expected, None, [problem])
    audit = state.get("audit_log")
    if not isinstance(audit, list):
        return _check(name, expected, None, [_reason(
            "state_evidence_missing", "INCONCLUSIVE", "State has no audit_log.", [ctx.at("/state/body")])])
    phrases = {normalize_utterance(p) for p in ctx.policy.get("confirmation_phrases", [])}
    position_of, confirmations, unknown = {}, [], []
    for position, turn in enumerate(ctx.turns, 1):
        if turn.get("outcome") != "ok" or turn.get("type") not in ("text", "audio"):
            continue
        turn_id = (turn.get("body") or {}).get("turn_id")
        if turn_id is not None:
            position_of[turn_id] = position
        said = _user_utterance(turn)
        if said is None:
            unknown.append(position)  # audio whose words the evaluator does not know
        elif normalize_utterance(said) in phrases:
            confirmations.append(position)
    reasons, writes = [], []
    for index, entry in enumerate(audit):
        entry = entry if isinstance(entry, dict) else {}
        where = [ctx.at("/state/body/audit_log/%d" % index)]
        label = "%s (%s, %s)" % (entry.get("action"), entry.get("event_id"), entry.get("turn_id"))
        position = position_of.get(entry.get("turn_id"))
        writes.append({"action": entry.get("action"), "event_id": entry.get("event_id"),
                       "turn_id": entry.get("turn_id"), "confirmed": entry.get("confirmed"),
                       "user_confirmation_turns_before": [c for c in confirmations if position and c <= position]})
        if entry.get("confirmed") is not True:
            reasons.append(_reason("unconfirmed_write", "FAIL",
                                   "Write %s was committed with confirmed=%r in the audit log." % (label, entry.get("confirmed")), where))
        elif position is None:
            reasons.append(_reason("write_turn_uncorrelated", "INCONCLUSIVE",
                                   "Write %s cannot be matched to a turn this run sent, so a preceding confirmation cannot be verified." % label,
                                   where + [ctx.at("/turns")]))
        elif any(c <= position for c in confirmations):
            continue
        elif any(u <= position for u in unknown):
            reasons.append(_reason("confirmation_unverifiable", "INCONCLUSIVE",
                                   "Write %s is marked confirmed, but the words of an earlier audio turn are unknown to the evaluator." % label,
                                   where + [ctx.at("/turns")]))
        else:
            reasons.append(_reason("write_without_user_confirmation", "FAIL",
                                   "Write %s is marked confirmed, but no user confirmation turn occurred at or before it." % label,
                                   where + [ctx.at("/turns")]))
    return _check(name, expected, {"writes": writes, "user_confirmation_turns": confirmations}, reasons)


def _limit_check(name, metric_name, prefix, what, item):
    """A check that every measured value of one metric is within the scenario's limit."""
    def check(expected, ctx):
        metrics = ctx.metrics[metric_name]
        reasons = []
        if not metrics:
            reasons.append(_reason(prefix + "_unavailable", "INCONCLUSIVE",
                                   "The conversation has no %s, so there is nothing to measure against the limit." % item,
                                   [ctx.at("/turns")]))
        for metric in metrics:
            where = [ctx.at("/turns/%d/body/events" % (metric["turn_index"] - 1)), ctx.at("/trace/body/events")]
            detail = "; ".join(metric["problems"])
            if metric["status"] == "ok":
                if metric["value_ms"] > expected:
                    reasons.append(_reason(prefix + "_over_limit", "FAIL",
                                           "%s for turn %d was %s ms (%s clock, %s), over the %s ms limit."
                                           % (what, metric["turn_index"], metric["value_ms"], metric["clock_domain"],
                                              metric["label"], expected), where))
            elif metric["status"] == "unavailable":
                reasons.append(_reason(prefix + "_unavailable", "INCONCLUSIVE",
                                       "%s for turn %d is unavailable: %s." % (what, metric["turn_index"], detail), where))
            else:
                reasons.append(_reason(prefix + "_incompatible", "INCONCLUSIVE",
                                       "%s for turn %d was rejected: %s." % (what, metric["turn_index"], detail), where))
        observed = [{"turn_index": m["turn_index"], "status": m["status"], "value_ms": m["value_ms"],
                     "label": m["label"], "clock_domain": m["clock_domain"]} for m in metrics]
        return _check(name, expected, observed, reasons)
    return check


CHECKS = {
    "booking": check_booking,
    "address": check_address,
    "no_write_without_confirmation": check_no_write_without_confirmation,
    "max_first_audio_playback_ms": _limit_check("max_first_audio_playback_ms", FIRST_PLAYBACK, "first_audio_playback",
                                                "First audio playback latency", "audio turns"),
    "max_interruption_stop_ms": _limit_check("max_interruption_stop_ms", INTERRUPTION_STOP, "interruption_stop",
                                             "Interruption stop latency", "interrupts"),
}


def _turn_deadline_check(ctx):
    """The turn deadline applies to text and audio turns, not to interrupts."""
    reasons, observed = [], []
    for turn in ctx.turns:
        if turn.get("type") == "interrupt":
            continue
        observed.append({"turn": turn.get("index"), "outcome": turn.get("outcome"), "elapsed_ms": turn.get("elapsed_ms")})
        if turn.get("deadline_exceeded") or turn.get("outcome") == "timeout":
            got = "no response" if turn.get("outcome") == "timeout" else "response"
            reasons.append(_reason("timeout", "FAIL", "Turn %s exceeded its %s ms deadline (%s after %s ms)."
                                   % (turn.get("index"), turn.get("deadline_ms"), got, turn.get("elapsed_ms")),
                                   [ctx.at("/turns/%d" % (turn.get("index", 1) - 1))]))
    return _check("turn_deadline", {"turn_timeout_ms": ctx.scenario.get("turn_timeout_ms")}, observed, reasons)


def _response_audio_check(ctx):
    """Audio turns must come back with a playable WAV saved as evidence."""
    reasons, observed = [], []
    for turn in ctx.turns:
        if turn.get("type") != "audio" or turn.get("outcome") != "ok":
            continue
        artifact = turn.get("audio_artifact")
        where = [ctx.at("/turns/%d" % (turn.get("index", 1) - 1))]
        if not artifact:
            reasons.append(_reason("response_audio_missing", "INCONCLUSIVE", "Turn %s returned no usable response audio%s."
                                   % (turn.get("index"), ": " + turn["audio_error"] if turn.get("audio_error") else ""), where))
        elif artifact.get("playable") is not True:
            reasons.append(_reason("response_audio_unplayable", "INCONCLUSIVE", "Turn %s response audio is not a playable WAV (%s)."
                                   % (turn.get("index"), artifact.get("error")), where))
        observed.append({"turn": turn.get("index"), "playable": bool(artifact and artifact.get("playable")),
                         "duration_ms": (artifact or {}).get("duration_ms"), "sha256": (artifact or {}).get("sha256")})
    return _check("response_audio", "playable WAV for every answered audio turn", observed, reasons)


def _describe(record):
    if "status" in record:
        code = None
        if isinstance(record.get("body"), dict) and isinstance(record["body"].get("error"), dict):
            code = record["body"]["error"].get("code")
        return "HTTP %s%s" % (record["status"], ", " + code if code else "")
    return record.get("error") or record.get("outcome") or "not attempted"


def _harness_reasons(ctx):
    evidence, reasons = ctx.evidence, []
    session = evidence.get("session") or {}
    created = session.get("outcome") == "ok"
    if not created:
        reasons.append(_reason("session_create_failed", "ERROR", "Session could not be created (%s)."
                               % _describe(session), [ctx.at("/session")]))
    for turn in ctx.turns:
        where = [ctx.at("/turns/%d" % (turn.get("index", 1) - 1))]
        if turn.get("type") == "interrupt":
            if turn.get("outcome") in ("http_error", "transport_error", "timeout"):
                reasons.append(_reason("interrupt_failed", "ERROR", "Interrupt at step %s did not get a valid response (%s)."
                                       % (turn.get("index"), _describe(turn)), where))
        elif turn.get("outcome") in ("http_error", "transport_error"):
            reasons.append(_reason("turn_failed", "ERROR", "Turn %s did not get a valid response (%s)."
                                   % (turn.get("index"), _describe(turn)), where))
    if created:
        for key, code in (("trace", "trace_read_failed"), ("cleanup", "session_cleanup_failed")):
            record = evidence.get(key) or {}
            if record.get("outcome") != "ok":
                reasons.append(_reason(code, "ERROR", "%s request failed (%s)." % (key.capitalize(), _describe(record)), [ctx.at("/" + key)]))
    for index, message in enumerate(evidence.get("harness_errors") or []):
        reasons.append(_reason("harness_exception", "ERROR", "Evaluator fault: %s" % message, [ctx.at("/harness_errors/%d" % index)]))
    return reasons


def grade_attempt(scenario, evidence, policy, evidence_ref="evidence.json"):
    """Grade one attempt. ``scenario`` is the definition dict; ``evidence`` the saved record."""
    if evidence.get("evidence_missing"):
        reason = _reason("evidence_missing", "INCONCLUSIVE", "The saved evidence for this attempt could not be read (%s)."
                         % evidence.get("evidence_error", "missing"), [evidence_ref])
        return {"verdict": "INCONCLUSIVE", "reasons": [reason], "checks": [],
                "metrics": {FIRST_PLAYBACK: [], INTERRUPTION_STOP: []}}
    ctx = _Context(scenario, evidence, policy or {}, evidence_ref)
    checks = [_turn_deadline_check(ctx)]
    if any(turn.get("type") == "audio" for turn in ctx.turns):
        checks.append(_response_audio_check(ctx))
    for name, expected in (scenario.get("expect") or {}).items():
        check = CHECKS.get(name)
        if check is None:
            checks.append(_check(name, expected, None, [_reason(
                "unsupported_check", "ERROR", "Unsupported expectation type %r." % name, [])]))
        else:
            checks.append(check(expected, ctx))
    reasons, seen = [], set()
    for reason in [r for c in checks for r in c["reasons"]] + _harness_reasons(ctx):
        key = (reason["code"], reason["message"])
        if key not in seen:
            seen.add(key)
            reasons.append(reason)
    reasons.sort(key=lambda r: -_RANK[r["verdict"]])
    return {"verdict": worst(r["verdict"] for r in reasons), "reasons": reasons,
            "checks": [dict(c, reasons=[r["code"] for r in c["reasons"]]) for c in checks],
            "metrics": ctx.metrics}


def build_attempt_result(meta, definition, source, evidence, policy, evidence_ref, artifacts):
    """One row of results.json: identity, verdict, reasons, checks, metrics, evidence pointers."""
    graded = grade_attempt(definition, evidence, policy, evidence_ref)
    return {
        "attempt_id": meta["attempt_id"], "scenario_id": meta["scenario_id"], "source": source,
        "modality": definition.get("modality"), "variant": meta["variant"], "repeat": meta["repeat"],
        "verdict": graded["verdict"], "reasons": graded["reasons"], "checks": graded["checks"],
        "metrics": graded["metrics"], "metrics_note": "audio metrics use the target's event clock (see each metric's label); "
                                                      "runner_duration_ms is measured by the evaluator",
        "expect": definition.get("expect"), "turn_timeout_ms": definition.get("turn_timeout_ms"),
        "evidence": evidence_ref, "artifacts": list(artifacts),
        "runner_duration_ms": evidence.get("runner_duration_ms"),
    }
