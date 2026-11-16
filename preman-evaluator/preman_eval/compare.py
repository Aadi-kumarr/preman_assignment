"""Baseline-versus-candidate comparison and run-to-run equivalence, from saved results."""
from collections import Counter, OrderedDict

from .metrics import FIRST_PLAYBACK, INTERRUPTION_STOP

VERDICTS = ("PASS", "FAIL", "ERROR", "INCONCLUSIVE")
INVALID = ("ERROR", "INCONCLUSIVE")
CATEGORY_TITLES = OrderedDict([
    ("regression", "passes on baseline, fails on candidate"),
    ("improvement", "fails on baseline, passes on candidate"),
    ("changed_failure", "fails on both, with different verdicts or reasons"),
    ("unchanged_failure", "same failure on both"),
    ("invalid_or_unavailable", "at least one side has ERROR or INCONCLUSIVE attempts, so there is no valid comparison"),
    ("unchanged_pass", "passes on both"),
])


def _ratio(count, total):
    return {"count": count, "of": total}


def _fmt(ratio):
    count, total = ratio["count"], ratio["of"]
    return "%d/%d (%.1f%%)" % (count, total, 100.0 * count / total) if total else "0/0 (n/a)"


def _policy_codes(attempt):
    return sorted({r["code"] for r in attempt["reasons"] if r.get("category") == "policy" and r["verdict"] == "FAIL"})


def _case(attempts):
    """Summary of one scenario on one variant across its repeats."""
    verdicts = Counter(a["verdict"] for a in attempts)
    reasons = Counter(code for a in attempts for code in {r["code"] for r in a["reasons"]})
    return {"attempts": len(attempts),
            "verdicts": {v: verdicts[v] for v in VERDICTS if verdicts[v]},
            "status": next(iter(verdicts)) if len(verdicts) == 1 else ("MIXED" if verdicts else "NOT_RUN"),
            "reason_codes": dict(sorted(reasons.items())),
            "policy_failure_attempts": sum(1 for a in attempts if _policy_codes(a))}


def _categorise(base, cand):
    if not base["attempts"] or not cand["attempts"] or any(v in INVALID for v in list(base["verdicts"]) + list(cand["verdicts"])):
        return "invalid_or_unavailable"
    if base["verdicts"] == cand["verdicts"] and base["reason_codes"] == cand["reason_codes"]:
        return "unchanged_pass" if base["status"] == "PASS" else "unchanged_failure"
    if base["status"] == "PASS":
        return "regression"
    return "improvement" if cand["status"] == "PASS" else "changed_failure"


def _metric_summary(attempts, name):
    entries = [m for a in attempts for m in (a.get("metrics") or {}).get(name, [])]
    values = [m["value_ms"] for m in entries if m["status"] == "ok"]
    return {"available": _ratio(len(values), len(entries)),
            "mean_ms": round(sum(values) / len(values), 1) if values else None,
            "min_ms": min(values) if values else None, "max_ms": max(values) if values else None,
            "labels": sorted({m["label"] for m in entries if m["status"] == "ok"})}


def _variant_totals(attempts):
    verdicts = Counter(a["verdict"] for a in attempts)
    scenarios = OrderedDict()
    for attempt in attempts:
        scenarios.setdefault(attempt["scenario_id"], []).append(attempt)
    valid = verdicts["PASS"] + verdicts["FAIL"]
    return {"attempts": len(attempts), "distinct_scenarios": len(scenarios),
            "repeats_per_scenario": sorted({len(group) for group in scenarios.values()}),
            "verdicts": {v: _ratio(verdicts[v], len(attempts)) for v in VERDICTS},
            "pass_rate_all_attempts": _ratio(verdicts["PASS"], len(attempts)),
            "pass_rate_valid_attempts": _ratio(verdicts["PASS"], valid),
            "scenarios_passing_every_repeat": _ratio(
                sum(1 for group in scenarios.values() if all(a["verdict"] == "PASS" for a in group)), len(scenarios)),
            "policy_failure_attempts": _ratio(sum(1 for a in attempts if _policy_codes(a)), len(attempts)),
            "scenarios_with_policy_failure": _ratio(
                sum(1 for group in scenarios.values() if any(_policy_codes(a) for a in group)), len(scenarios))}


def build_comparison(results, baseline, candidate):
    """Compare two variants of one run, scenario by scenario."""
    attempts = results["attempts"]
    order = list(OrderedDict.fromkeys(a["scenario_id"] for a in attempts))
    cases = []
    for scenario_id in order:
        mine = [a for a in attempts if a["scenario_id"] == scenario_id]
        sides = {v: [a for a in mine if a["variant"] == v] for v in (baseline, candidate)}
        base, cand = _case(sides[baseline]), _case(sides[candidate])
        metrics = {}
        for name in (FIRST_PLAYBACK, INTERRUPTION_STOP):
            left, right = _metric_summary(sides[baseline], name), _metric_summary(sides[candidate], name)
            if left["available"]["of"] or right["available"]["of"]:
                delta = None if left["mean_ms"] is None or right["mean_ms"] is None else round(right["mean_ms"] - left["mean_ms"], 1)
                metrics[name] = {"baseline": left, "candidate": right, "mean_delta_ms": delta}
        durations = {}
        for key, side in (("baseline", sides[baseline]), ("candidate", sides[candidate])):
            values = [a["runner_duration_ms"] for a in side if isinstance(a.get("runner_duration_ms"), (int, float))]
            durations[key] = round(sum(values) / len(values), 1) if values else None
        cases.append({"scenario_id": scenario_id, "modality": mine[0].get("modality"), "source": mine[0].get("source"),
                      "category": _categorise(base, cand),
                      "changed": base["verdicts"] != cand["verdicts"] or base["reason_codes"] != cand["reason_codes"],
                      "baseline": base, "candidate": cand, "metrics": metrics,
                      "evidence": {key: [{"repeat": a["repeat"], "path": a["evidence"]} for a in sides[variant]]
                                   for key, variant in (("baseline", baseline), ("candidate", candidate))},
                      "mean_runner_duration_ms_measured": durations})
    policy = []
    for attempt in attempts:
        if attempt["variant"] in (baseline, candidate) and _policy_codes(attempt):
            policy.append({"attempt_id": attempt["attempt_id"], "scenario_id": attempt["scenario_id"],
                           "variant": attempt["variant"], "repeat": attempt["repeat"],
                           "codes": _policy_codes(attempt), "evidence": attempt["evidence"]})
    counts = Counter(case["category"] for case in cases)
    return {"comparison_schema": 1, "run_id": results.get("run_id"), "baseline": baseline, "candidate": candidate,
            "totals": {baseline: _variant_totals([a for a in attempts if a["variant"] == baseline]),
                       candidate: _variant_totals([a for a in attempts if a["variant"] == candidate])},
            "category_counts": {name: _ratio(counts[name], len(cases)) for name in CATEGORY_TITLES},
            "cases": cases, "policy_failures": policy}


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    return lines + ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]


def _mix(case):
    if not case["attempts"]:
        return "not run"
    return ", ".join("%s %d/%d" % (v, n, case["attempts"]) for v, n in case["verdicts"].items())


def _codes(case):
    return ", ".join("%s (%d/%d)" % (code, n, case["attempts"]) for code, n in case["reason_codes"].items()) or "-"


def _evidence_links(case, base, cand):
    """Relative links to each attempt's evidence, in the same format as the policy-failures table."""
    evidence = case.get("evidence") or {}
    links = ["[%s r%s](%s)" % (name, item["repeat"], item["path"])
             for key, name in (("baseline", base), ("candidate", cand)) for item in evidence.get(key, [])]
    return " ".join(links) or "-"


def render_comparison(comparison):
    base, cand = comparison["baseline"], comparison["candidate"]
    totals = comparison["totals"]
    out = ["# Variant comparison: `%s` (baseline) versus `%s` (candidate)" % (base, cand), "",
           "Run `%s`. Every rate shows its numerator and denominator." % comparison["run_id"], "",
           "## Scope", "",
           "Attempts, distinct scenarios, and repeats are three separate numbers. "
           "Repeats are repeated trials of one scenario, not additional scenarios.", ""]
    out += _table(["Variant", "Attempts", "Distinct scenarios", "Repeats per scenario"],
                  [[v, totals[v]["attempts"], totals[v]["distinct_scenarios"],
                    ", ".join(map(str, totals[v]["repeats_per_scenario"])) or "-"] for v in (base, cand)])
    out += ["", "## Verdict counts", "", "Attempts with each verdict / all attempts for the variant.", ""]
    out += _table(["Variant"] + list(VERDICTS), [[v] + [_fmt(totals[v]["verdicts"][x]) for x in VERDICTS] for v in (base, cand)])
    out += ["", "## Aggregates", ""]
    rows = [("PASS / all attempts", "pass_rate_all_attempts"),
            ("PASS / valid attempts (PASS + FAIL only)", "pass_rate_valid_attempts"),
            ("Scenarios passing every repeat / distinct scenarios", "scenarios_passing_every_repeat"),
            ("Attempts with a policy failure / all attempts", "policy_failure_attempts"),
            ("Scenarios with a policy failure / distinct scenarios", "scenarios_with_policy_failure")]
    out += _table(["Aggregate", base, cand], [[label, _fmt(totals[base][key]), _fmt(totals[cand][key])] for label, key in rows])

    out += ["", "## Policy failures", "",
            "Listed in full whatever the aggregates above show; an overall improvement does not hide these.", ""]
    if comparison["policy_failures"]:
        out += _table(["Scenario", "Variant", "Repeat", "Policy reason", "Evidence"],
                      [["`%s`" % p["scenario_id"], p["variant"], p["repeat"], ", ".join(p["codes"]),
                        "[evidence](%s)" % p["evidence"]] for p in comparison["policy_failures"]])
    else:
        out.append("None on either variant.")

    out += ["", "## Cases by outcome", "", "Scenarios in each group / distinct scenarios compared.", ""]
    out += _table(["Group", "Meaning", "Scenarios"],
                  [[name, title, _fmt(comparison["category_counts"][name])] for name, title in CATEGORY_TITLES.items()])
    sections = [("Changed cases", ("regression", "improvement", "changed_failure")),
                ("Unchanged failures", ("unchanged_failure",)),
                ("Invalid or unavailable cases", ("invalid_or_unavailable",)),
                ("Unchanged passes", ("unchanged_pass",))]
    for title, names in sections:
        cases = [c for c in comparison["cases"] if c["category"] in names]
        out += ["", "## %s (%d of %d scenarios)" % (title, len(cases), len(comparison["cases"])), ""]
        if not cases:
            out.append("None.")
            continue
        out += _table(["Scenario", "Group", base + " verdicts", cand + " verdicts", base + " reasons", cand + " reasons", "Evidence"],
                      [["`%s`" % c["scenario_id"], c["category"] + (" (differs)" if c["changed"] and c["category"] == "invalid_or_unavailable" else ""),
                        _mix(c["baseline"]), _mix(c["candidate"]), _codes(c["baseline"]), _codes(c["candidate"]),
                        _evidence_links(c, base, cand)] for c in cases])

    out += ["", "## Audio metric differences", "",
            "Values come from the target's event timeline. For the supplied target that is a simulated fixture clock, "
            "not a measurement of real latency. Available = metrics with a usable value / metrics required.", ""]
    rows = []
    for case in comparison["cases"]:
        for name, metric in case["metrics"].items():
            def cell(side):
                if side["mean_ms"] is None:
                    return "unavailable (%s)" % _fmt(side["available"])
                return "mean %s ms, range %s to %s, available %s, %s" % (
                    side["mean_ms"], side["min_ms"], side["max_ms"], _fmt(side["available"]), "/".join(side["labels"]))
            delta = "n/a" if metric["mean_delta_ms"] is None else "%+.1f ms" % metric["mean_delta_ms"]
            rows.append(["`%s`" % case["scenario_id"], name, cell(metric["baseline"]), cell(metric["candidate"]), delta])
    out += _table(["Scenario", "Metric", base, cand, "Mean difference (candidate - baseline)"], rows) if rows else ["No audio metrics in this run."]

    out += ["", "## Measured runner duration", "",
            "Wall-clock time per attempt measured by the evaluator (monotonic clock). It is kept separate from the audio metrics above.", ""]
    out += _table(["Scenario", base + " mean ms", cand + " mean ms"],
                  [["`%s`" % c["scenario_id"], c["mean_runner_duration_ms_measured"]["baseline"],
                    c["mean_runner_duration_ms_measured"]["candidate"]] for c in comparison["cases"]])
    return "\n".join(out) + "\n"


def compare_runs(results_a, results_b):
    """Are two runs' outcomes equivalent, attempt by attempt (scenario, variant, repeat)?"""
    def index(results):
        return {(a["scenario_id"], a["variant"], a["repeat"]):
                (a["verdict"], sorted({(r["code"], r["verdict"]) for r in a["reasons"]}),
                 sorted((c["check"], str(c["verdict"])) for c in a["checks"])) for a in results["attempts"]}
    left, right = index(results_a), index(results_b)
    differences = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            differences.append({"scenario_id": key[0], "variant": key[1], "repeat": key[2],
                                "a": left.get(key, ("missing",))[0], "b": right.get(key, ("missing",))[0],
                                "a_reasons": [c for c, _ in left[key][1]] if key in left else None,
                                "b_reasons": [c for c, _ in right[key][1]] if key in right else None})
    return {"a": results_a.get("run_id"), "b": results_b.get("run_id"), "attempts_a": len(left),
            "attempts_b": len(right), "equivalent": not differences, "differences": differences}


def render_run_equivalence(result, info_a, info_b, results_a, results_b):
    out = ["# Run equivalence: `%s` versus `%s`" % (result["a"], result["b"]), "",
           "Compared per scenario, variant and repeat: verdict, reason codes, and every check outcome.", ""]
    rows = []
    for label, info, results in (("A", info_a, results_a), ("B", info_b, results_b)):
        variants = OrderedDict.fromkeys(a["variant"] for a in results["attempts"])
        for variant in variants:
            mine = [a for a in results["attempts"] if a["variant"] == variant]
            tally = Counter(a["verdict"] for a in mine)
            rows.append([label, "`%s`" % results.get("run_id"), info.get("concurrency"), variant, len(mine),
                         len({a["scenario_id"] for a in mine}), info.get("repeats")] +
                        ["%d/%d" % (tally[v], len(mine)) for v in VERDICTS])
    out += _table(["Run", "Run ID", "Concurrency", "Variant", "Attempts", "Distinct scenarios", "Repeats"] + list(VERDICTS), rows)
    out += ["", "**Equivalent: %s** (%d differing attempts out of %d compared)." % (
        "yes" if result["equivalent"] else "NO", len(result["differences"]), max(result["attempts_a"], result["attempts_b"])), ""]
    if result["differences"]:
        out += _table(["Scenario", "Variant", "Repeat", "A verdict", "B verdict", "A reasons", "B reasons"],
                      [[d["scenario_id"], d["variant"], d["repeat"], d["a"], d["b"],
                        ", ".join(d["a_reasons"] or []) or "-", ", ".join(d["b_reasons"] or []) or "-"] for d in result["differences"]])
    return "\n".join(out) + "\n"
