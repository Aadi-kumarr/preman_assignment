"""Markdown reporting from saved results. No target requests are made here."""
import json
from collections import Counter, OrderedDict
from pathlib import Path

VERDICTS = ("PASS", "FAIL", "ERROR", "INCONCLUSIVE")


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _rate(count, total):
    return "%d/%d (%.1f%%)" % (count, total, 100.0 * count / total) if total else "0/0 (n/a)"


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _verdict_mix(attempts):
    counts = Counter(a["verdict"] for a in attempts)
    return ", ".join("%s x%d" % (v, counts[v]) for v in VERDICTS if counts[v]) or "-"


def _replay_header(replay):
    expectations, reproduction = replay["expectations"], replay["reproduction"]
    out = ["# Offline replay `%s` of run `%s`" % (replay["replay_id"], replay["original_run_id"]), "",
           "Regraded from saved evidence in [%s](%s/manifest.json). The target was not contacted." % (
               replay["original_run_path"], replay["original_run_path"]), "",
           "- Replay started (UTC): %s; replay duration: %s ms (offline regrade time, not agent timing)" % (
               replay["started_at_utc"], replay.get("replay_duration_ms")),
           "- Replay evaluator: git commit `%s`, source sha256 `%s`" % (
               replay["evaluator"]["git_commit"], replay["evaluator"]["source_sha256"][:16]),
           "- Expectations: %s" % ("unchanged from the original run" if expectations["unchanged"] else
                                   "CHANGED for %d scenario(s)" % len(expectations["changed"]))]
    for change in expectations["changed"]:
        out.append("  - `%s`: `%s` -> `%s`" % (change["scenario_id"], json.dumps(change["original_expect"], sort_keys=True),
                                              json.dumps(change["replay_expect"], sort_keys=True)))
    for note in expectations.get("notes", []):
        out.append("  - note: %s" % note)
    out.append("- Outcomes identical to the original run: **%s** (%d attempts compared: %s)" % (
        "yes" if reproduction["identical_to_original"] else "no", reproduction["attempts_compared"], reproduction["meaning"]))
    if replay["artifact_problems"]:
        out.append("- Saved artifacts with problems: %d (listed below)" % len(replay["artifact_problems"]))
    else:
        out.append("- Saved audio artifacts: all present and matching their recorded SHA-256")
    if reproduction["differences"]:
        out += ["", "## Changes from the original run", "", "Original verdict and reasons, then the replay's.", ""]
        out += _table(["Attempt", "Original", "Replay", "Original reasons", "Replay reasons", "Checks that changed"],
                      [["`%s`" % d["attempt_id"], d["original_verdict"], d["replay_verdict"],
                        ", ".join(d["original_reasons"]) or "-", ", ".join(d["replay_reasons"]) or "-",
                        ", ".join(d["changed_checks"]) or "-"] for d in reproduction["differences"]])
    if replay["artifact_problems"]:
        out += ["", "## Artifact problems", ""]
        out += _table(["Attempt", "Artifact", "Problem"],
                      [["`%s`" % a["attempt_id"], a["artifact"], a["problem"]] for a in replay["artifact_problems"]])
    out += ["", "## Original run", ""]
    return out


def _metric_rows(attempts):
    grouped = OrderedDict()
    for attempt in attempts:
        for name, entries in (attempt.get("metrics") or {}).items():
            for metric in entries:
                grouped.setdefault((attempt["scenario_id"], attempt["variant"], name, metric["turn_index"]), []).append(
                    (metric, (attempt.get("expect") or {}).get("max_" + name)))
    rows = []
    for (scenario_id, variant, name, turn), items in grouped.items():
        values = [m["value_ms"] for m, _ in items if m["status"] == "ok"]
        statuses = Counter(m["status"] for m, _ in items)
        limit = items[0][1]
        rows.append(["`%s`" % scenario_id, variant, name, turn,
                     ", ".join("%s ms x%d" % (v, n) for v, n in Counter(values).items()) or "-",
                     "%d/%d" % (len(values), len(items)),
                     ", ".join("%s x%d" % (k, n) for k, n in statuses.items()),
                     "<= %s ms" % limit if limit is not None else "no limit set",
                     ", ".join(sorted({"%s (%s)" % (m["label"], m["clock_domain"]) for m, _ in items if m["status"] == "ok"})) or "-"])
    return rows


def build_report(manifest, results):
    attempts = results["attempts"]
    replay = manifest if manifest.get("kind") == "replay" else None
    if replay:
        manifest = replay["original_manifest"]
    variants = manifest["target"]["variants"]
    counts = manifest["counts"]
    starter, evaluator, target = manifest["starter"], manifest["evaluator"], manifest["target"]
    out = _replay_header(replay) if replay else ["# Evaluation report: run `%s`" % manifest["run_id"], ""]
    out += [
        "- Started (UTC): %s; finished: %s" % (manifest["started_at_utc"], manifest.get("finished_at_utc")),
        "- Evaluator: git commit `%s`, source sha256 `%s`" % (evaluator["git_commit"], evaluator["source_sha256"][:16]),
        "- Starter folder sha256: `%s` (%d files); unchanged during run: **%s**" % (
            starter["sha256"], starter["files"], starter.get("unchanged_during_run")),
        "- Target: %s; variants: %s" % (target["base_url"], ", ".join(variants)),
        "- Concurrency: %d; repeats: %d; harness timeout: %d ms" % (
            manifest["concurrency"], manifest["repeats"], manifest["harness_timeout_ms"]),
        "- Target active sessions before/after: %s / %s" % (
            (target.get("health_before") or {}).get("active_sessions"),
            (target.get("health_after") or {}).get("active_sessions")),
        "- Verdict precedence: %s" % " > ".join(results.get("verdict_precedence", [])), "",
        "## Scope", "",
        "- Distinct scenarios: **%d**; variants: **%d**; repeats per scenario and variant: **%d**" % (
            counts["distinct_scenarios"], counts["variants"], counts["repeats"]),
        "- Attempts: **%d** (= %d x %d x %d). Repeats are repeated trials of the same scenario, not new scenarios." % (
            counts["attempts"], counts["distinct_scenarios"], counts["variants"], counts["repeats"]),
    ]
    for item in manifest.get("skipped_scenarios", []):
        out.append("- Not run: `%s` (%s): %s" % (item["scenario_id"], item["source"], item["reason"]))

    out += ["", "## Verdict counts by variant", "",
            "Each cell is attempts with that verdict / all attempts for the variant.", ""]
    rows = []
    for variant in variants:
        mine = [a for a in attempts if a["variant"] == variant]
        tally = Counter(a["verdict"] for a in mine)
        rows.append([variant, len(mine)] + [_rate(tally[v], len(mine)) for v in VERDICTS])
    tally = Counter(a["verdict"] for a in attempts)
    rows.append(["all", len(attempts)] + [_rate(tally[v], len(attempts)) for v in VERDICTS])
    out += _table(["Variant", "Attempts"] + list(VERDICTS), rows)

    out += ["", "## Results by scenario", ""]
    grouped = OrderedDict()
    for attempt in attempts:
        grouped.setdefault((attempt["scenario_id"], attempt["variant"]), []).append(attempt)
    rows = []
    for (scenario_id, variant), group in grouped.items():
        codes = Counter(r["code"] for a in group for r in {r["code"]: r for r in a["reasons"]}.values())
        durations = [a["runner_duration_ms"] for a in group if isinstance(a.get("runner_duration_ms"), (int, float))]
        rows.append(["`%s`" % scenario_id, group[0]["modality"], variant, len(group), _verdict_mix(group),
                     ", ".join("%s (%d/%d)" % (c, n, len(group)) for c, n in codes.items()) or "-",
                     round(sum(durations) / len(durations), 1) if durations else "-"])
    out += _table(["Scenario", "Modality", "Variant", "Attempts", "Verdicts", "Reasons (attempts affected)",
                   "Mean runner ms (measured)"], rows)

    out += ["", "## Audio metrics", "",
            "Computed from saved events, paired by session, turn and response IDs. The clock is the target's own: "
            "for the supplied target it is a simulated fixture clock, not real latency. "
            "Available = metrics with a usable value / metrics required. Runner time is the separate measured column above.", ""]
    rows = _metric_rows(attempts)
    if rows:
        out += _table(["Scenario", "Variant", "Metric", "Step", "Values", "Available", "Status", "Limit", "Provenance"], rows)
    else:
        out.append("No audio turns or interrupts in this run.")

    out += ["", "## Reasons", "",
            "Attempts affected / attempts for that variant. One attempt can have several reasons.", ""]
    rows = []
    for variant in variants:
        mine = [a for a in attempts if a["variant"] == variant]
        codes = Counter()
        for attempt in mine:
            for key in {(r["code"], r["verdict"]) for r in attempt["reasons"]}:
                codes[key] += 1
        for (code, verdict), number in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0])):
            rows.append([variant, code, verdict, _rate(number, len(mine))])
    out += _table(["Variant", "Reason", "Reason verdict", "Attempts affected"], rows) if rows else ["No non-PASS reasons."]

    out += ["", "## Attempts that did not pass", ""]
    failing = [a for a in attempts if a["verdict"] != "PASS"]
    if not failing:
        out.append("None.")
    for attempt in failing:
        out += ["### `%s`: %s" % (attempt["attempt_id"], attempt["verdict"]), "",
                "Scenario `%s`, variant `%s`, repeat %d. Evidence: [%s](%s). Runner duration (measured): %s ms." % (
                    attempt["scenario_id"], attempt["variant"], attempt["repeat"],
                    attempt["evidence"], attempt["evidence"], attempt.get("runner_duration_ms")), ""]
        for reason in attempt["reasons"]:
            refs = ", ".join("`%s`" % ref for ref in reason["evidence"])
            out.append("- **%s** `%s`: %s%s" % (reason["verdict"], reason["code"], reason["message"],
                                                " Evidence: %s" % refs if refs else ""))
        if attempt["artifacts"]:
            out.append("- Response audio: " + ", ".join("[%s](%s)" % (Path(p).name, p) for p in attempt["artifacts"]))
        out.append("")
    if ((replay or manifest).get("artifacts") or {}).get("comparison_report"):
        out += ["", "## Variant comparison", "", "See [comparison.md](comparison.md) for baseline versus candidate.", ""]
    out += ["", "## Notes", "",
            "- Verdicts come from authoritative state, the audit log, turn outcomes, and timing events; the trace is saved as evidence but is not authoritative.",
            "- Runner durations are wall-clock measurements by the evaluator, not agent latency metrics.", ""]
    return "\n".join(out)


def load_run(run_dir):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    return manifest, results


def build_observed_table(run_dir, sources=None, modality=None):
    """Observed behaviour per attempt, read from saved evidence (verification gate)."""
    run_dir = Path(run_dir)
    manifest, results = load_run(run_dir)
    rows = []
    for attempt in results["attempts"]:
        if (sources and attempt["source"] not in sources) or (modality and attempt["modality"] != modality):
            continue
        try:
            evidence = json.loads((run_dir / attempt["evidence"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            evidence = {}
        state = evidence.get("state") or {}
        body = state.get("body") if state.get("outcome") == "ok" else None
        if body is not None:
            bookings = body.get("bookings") or []
            state_read, count = "ok (HTTP %s)" % state.get("status"), len(bookings)
            times = ", ".join(str(b.get("starts_at")) for b in bookings) or "-"
            address = body.get("address")
            unconfirmed = sum(1 for e in body.get("audit_log") or [] if e.get("confirmed") is not True)
            writes = "%d (%d unconfirmed)" % (len(body.get("audit_log") or []), unconfirmed)
        else:
            detail = "HTTP %s" % state["status"] if "status" in state else state.get("outcome", "missing")
            state_read, count, times, address, writes = "FAILED (%s)" % detail, "unknown", "unknown", "unknown", "unknown"
        timeouts = sum(1 for t in evidence.get("turns") or [] if t.get("outcome") == "timeout" or t.get("deadline_exceeded"))
        metrics = attempt.get("metrics") or {}

        def shown(name):
            return ", ".join("%s ms" % m["value_ms"] if m["status"] == "ok" else m["status"] for m in metrics.get(name, [])) or "-"
        wavs = [t.get("audio_artifact") for t in evidence.get("turns") or []
                if t.get("type") in ("text", "audio") and t.get("outcome") == "ok"]
        if any(w and "playable" in w for w in wavs):
            playable = "%d/%d playable" % (sum(1 for w in wavs if w and w.get("playable")), len(wavs))
        else:
            playable = "%d saved" % sum(1 for w in wavs if w)
        rows.append(["`%s`" % attempt["scenario_id"], attempt["variant"], attempt["repeat"], state_read, count, times,
                     address, writes, timeouts, shown("first_audio_playback_ms"), shown("interruption_stop_ms"), playable,
                     "`%s`" % json.dumps(attempt["expect"], sort_keys=True),
                     attempt["verdict"], ", ".join(r["code"] for r in attempt["reasons"]) or "-"])
    replay = manifest if manifest.get("kind") == "replay" else None
    base = replay["original_manifest"] if replay else manifest
    out = ["# Verification gate: observed %s behaviour" % (modality or "target"), "",
           "Generated from saved evidence of run `%s` (started %s UTC). Starter sha256 `%s`, unchanged during run: %s." % (
               base["run_id"], base["started_at_utc"], base["starter"]["sha256"], base["starter"].get("unchanged_during_run")), ""]
    if replay:
        out += ["Verdicts are from offline replay `%s` with the current grader. The saved evidence was not modified and the "
                "target was not contacted. Outcomes identical to the original results: **%s**." % (
                    replay["replay_id"], "yes" if replay["reproduction"]["identical_to_original"] else "no"), ""]
        for d in replay["reproduction"]["differences"]:
            out.append("- `%s`: original %s (%s), now %s (%s)" % (
                d["attempt_id"], d["original_verdict"], ", ".join(d["original_reasons"]) or "-",
                d["replay_verdict"], ", ".join(d["replay_reasons"]) or "-"))
    out += ["Observed columns come from `GET /state` (authoritative), turn outcomes, and timing events. "
            "Expected is the scenario's own `expect` block.", ""]
    out += _table(["Scenario", "Variant", "Repeat", "State read", "Booking count", "Booking starts_at", "Address",
                   "Audited writes", "Turn timeouts", "First playback (simulated)", "Interruption stop (simulated)",
                   "Response WAVs", "Expected", "Verdict", "Reasons"], rows)
    return "\n".join(out) + "\n"
