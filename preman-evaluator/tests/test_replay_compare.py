"""Offline replay (no target requests) and baseline-versus-candidate comparison."""
import json
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from preman_eval.compare import build_comparison, compare_runs, render_comparison
from preman_eval.config import RunConfig
from preman_eval.hashing import sha256_tree
from preman_eval.replay import ReplayError, replay_run
from preman_eval.report import build_observed_table, load_run
from preman_eval.runner import run_suite
from preman_eval.scenarios import load_scenarios

from support import BOOK, CONFIRM, SLOT, FakeTarget, booking, scenario_def, wav_bytes


def network_blocked():
    """Make any attempt to open a socket or URL fail the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("replay tried to use the network")
    return mock.patch.multiple(socket, socket=refuse, create_connection=refuse), \
        mock.patch.object(urllib.request, "urlopen", refuse), \
        mock.patch.object(urllib.request.OpenerDirector, "open", refuse)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "starter").mkdir()
        (self.root / "starter" / "in.wav").write_bytes(wav_bytes())
        self.definitions = [
            scenario_def({"booking": {"count": 1, "customer_id": "C1", "starts_at": SLOT}}, scenario_id="books"),
            {"id": "speaks", "fixture": "any", "modality": "audio", "turn_timeout_ms": 3000,
             "turns": [{"type": "audio", "path": "in.wav"}, {"type": "interrupt"}],
             "expect": {"max_first_audio_playback_ms": 1000, "max_interruption_stop_ms": 400}},
        ]
        (self.root / "scenarios.json").write_text(json.dumps({"schema_version": 1, "scenarios": self.definitions}),
                                                  encoding="utf-8")
        fake = FakeTarget({("GET", "state"): (200, {"authoritative": True, "bookings": [booking()],
                                                   "address": "10 Oak Street", "audit_log": []})})
        cfg = RunConfig(root=self.root, base_url=fake.base_url, starter_dir="starter", scenario_files=["scenarios.json"],
                        runs_dir="runs", repeats=2, harness_timeout_ms=2000).validate()
        scenarios = load_scenarios([("scenarios.json", self.root / "scenarios.json")], self.root / "starter")
        self.run_dir = run_suite(cfg, scenarios)
        self.requests_during_run = len(fake.calls)
        self.fake = fake
        fake.close()  # the target is stopped before any replay

    def replay(self, **kwargs):
        patches = network_blocked()
        for patch in patches:
            patch.start()
        try:
            replay_dir = replay_run(self.run_dir, **kwargs)
        finally:
            for patch in patches:
                patch.stop()
        return (replay_dir,) + load_run(replay_dir)

    def test_replay_reproduces_original_outcomes_with_no_target_requests(self):
        before = sha256_tree(self.run_dir)
        replay_dir, manifest, results = self.replay()
        _, original = load_run(self.run_dir)
        self.assertTrue(manifest["reproduction"]["identical_to_original"])
        self.assertEqual(manifest["reproduction"]["differences"], [])
        self.assertEqual(manifest["reproduction"]["attempts_compared"], 8)
        for old, new in zip(original["attempts"], results["attempts"]):
            self.assertEqual((old["verdict"], old["reasons"] and [r["code"] for r in old["reasons"]], old["metrics"]),
                             (new["verdict"], new["reasons"] and [r["code"] for r in new["reasons"]], new["metrics"]))
            self.assertEqual([(c["check"], c["verdict"], c["observed"]) for c in old["checks"]],
                             [(c["check"], c["verdict"], c["observed"]) for c in new["checks"]])
        self.assertEqual(len(self.fake.calls), self.requests_during_run)  # zero requests reached the (stopped) target
        self.assertFalse(manifest["target_contacted"])
        self.assertEqual(sha256_tree(self.run_dir), before)  # original run untouched

    def test_replay_is_saved_separately_and_points_at_the_original(self):
        replay_dir, manifest, results = self.replay()
        second, _, _ = self.replay()
        self.assertNotEqual(replay_dir, second)
        self.assertEqual(replay_dir.parent, self.root / "replays")
        original_manifest, _ = load_run(self.run_dir)
        self.assertEqual(manifest["original_run_id"], original_manifest["run_id"])
        self.assertEqual((replay_dir / manifest["original_run_path"]).resolve(), self.run_dir.resolve())
        self.assertTrue((replay_dir / results["attempts"][0]["evidence"]).is_file())  # evidence link resolves
        self.assertTrue((replay_dir / "comparison.md").is_file() and (replay_dir / "report.md").is_file())
        self.assertIsInstance(manifest["replay_duration_ms"], float)
        report = (replay_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("Offline replay `%s` of run `%s`" % (manifest["replay_id"], original_manifest["run_id"]), report)
        self.assertIn("offline regrade time, not agent timing", report)
        for path in replay_dir.iterdir():
            self.assertNotIn(str(self.root), path.read_text(encoding="utf-8"), path.name)

    def test_changed_threshold_changes_verdicts_and_is_recorded(self):
        _, manifest, results = self.replay(sets=["speaks.max_first_audio_playback_ms=500"])
        verdicts = {(a["scenario_id"], a["variant"], a["repeat"]): a["verdict"] for a in results["attempts"]}
        self.assertEqual({v for (s, _, _), v in verdicts.items() if s == "speaks"}, {"FAIL"})
        self.assertEqual({v for (s, _, _), v in verdicts.items() if s == "books"}, {"PASS"})
        self.assertFalse(manifest["expectations"]["unchanged"])
        self.assertEqual(manifest["expectations"]["changed"][0]["replay_expect"]["max_first_audio_playback_ms"], 500)
        self.assertEqual(manifest["expectations"]["changed"][0]["original_expect"]["max_first_audio_playback_ms"], 1000)
        differences = manifest["reproduction"]["differences"]
        self.assertEqual(len(differences), 4)
        self.assertEqual((differences[0]["original_verdict"], differences[0]["replay_verdict"], differences[0]["replay_reasons"],
                          differences[0]["changed_checks"]),
                         ("PASS", "FAIL", ["first_audio_playback_over_limit"], ["max_first_audio_playback_ms"]))
        self.assertEqual(results["attempts"][2]["original_verdict"], "PASS")

    def test_changed_expectation_from_a_scenario_file(self):
        changed = json.loads(json.dumps(self.definitions))
        changed[0]["expect"]["booking"]["starts_at"] = "2026-12-01T11:00:00Z"
        path = self.root / "changed.json"
        path.write_text(json.dumps({"schema_version": 1, "scenarios": changed}), encoding="utf-8")
        _, manifest, results = self.replay(scenario_files=[path])
        books = [a for a in results["attempts"] if a["scenario_id"] == "books"]
        self.assertEqual({a["verdict"] for a in books}, {"FAIL"})
        self.assertEqual(books[0]["reasons"][0]["code"], "booking_starts_at_mismatch")
        self.assertEqual([c["scenario_id"] for c in manifest["expectations"]["changed"]], ["books"])

    def test_wildcard_set_only_touches_scenarios_that_have_the_field(self):
        _, manifest, _ = self.replay(sets=["*.max_interruption_stop_ms=100"])
        self.assertEqual([c["scenario_id"] for c in manifest["expectations"]["changed"]], ["speaks"])

    def test_changing_conversation_inputs_is_refused(self):
        for field, value in (("turns", [{"type": "text", "text": "different"}]), ("fixture", "other"), ("turn_timeout_ms", 99)):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(self.definitions))
                changed[0][field] = value
                path = self.root / "inputs.json"
                path.write_text(json.dumps({"schema_version": 1, "scenarios": changed}), encoding="utf-8")
                with self.assertRaises(ReplayError) as caught:
                    replay_run(self.run_dir, scenario_files=[path])
                self.assertIn("requires a new target run", str(caught.exception))
        self.assertFalse((self.root / "replays").exists())

    def test_invalid_overrides_are_rejected_clearly(self):
        for sets, fragment in ((["speaks.max_first_audio_playback_ms=-1"], "positive number"),
                               (["speaks.sentiment=1"], "unsupported expectation type"),
                               (["nobody.address=x"], "does not name a scenario"), (["speaks.address"], "--set needs")):
            with self.subTest(sets=sets):
                with self.assertRaises(ReplayError) as caught:
                    replay_run(self.run_dir, sets=sets)
                self.assertIn(fragment, str(caught.exception))

    def test_missing_evidence_and_audio_stay_explicit(self):
        _, original = load_run(self.run_dir)
        (self.run_dir / original["attempts"][0]["evidence"]).unlink()
        (self.run_dir / original["attempts"][1]["artifacts"][0]).unlink()
        _, manifest, results = self.replay()
        first = results["attempts"][0]
        self.assertEqual((first["verdict"], [r["code"] for r in first["reasons"]]), ("INCONCLUSIVE", ["evidence_missing"]))
        self.assertFalse(manifest["reproduction"]["identical_to_original"])
        self.assertEqual((manifest["reproduction"]["differences"][0]["original_verdict"],
                          manifest["reproduction"]["differences"][0]["replay_verdict"]), ("PASS", "INCONCLUSIVE"))
        self.assertIn({"attempt_id": original["attempts"][1]["attempt_id"], "artifact": original["attempts"][1]["artifacts"][0],
                       "problem": "missing"}, manifest["artifact_problems"])

    def test_a_replay_cannot_be_replayed_and_observe_works_on_a_replay(self):
        replay_dir, _, _ = self.replay()
        with self.assertRaises(ReplayError):
            replay_run(replay_dir)
        table = build_observed_table(replay_dir, modality="audio")
        self.assertIn("| `speaks` | baseline | 1 | ok (HTTP 200) | 1 |", table)
        self.assertIn("640 ms", table)
        self.assertIn("320 ms", table)


def attempt(scenario, variant, repeat, verdict, reasons=(), playback=None):
    categories = {"unconfirmed_write": "policy"}
    metrics = {"first_audio_playback_ms": [], "interruption_stop_ms": []}
    if playback is not None:
        metrics["first_audio_playback_ms"] = [{"status": "ok" if playback else "unavailable", "value_ms": playback or None,
                                                "label": "simulated", "turn_index": 1}]
    return {"attempt_id": "%s-%s-%d" % (scenario, variant, repeat), "scenario_id": scenario, "variant": variant,
            "repeat": repeat, "verdict": verdict, "modality": "chat", "source": "s.json", "metrics": metrics,
            "reasons": [{"code": c, "verdict": "FAIL" if verdict == "FAIL" else verdict, "category": categories.get(c, "other")}
                        for c in reasons],
            "checks": [], "evidence": "attempts/x/evidence.json", "runner_duration_ms": 10.0}


def results_for(rows):
    return {"run_id": "run-1", "attempts": [attempt(*row) for row in rows for row in [row]]}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for repeat in (1, 2):
            rows += [("regresses", "baseline", repeat, "PASS"), ("regresses", "faulty", repeat, "FAIL", ["booking_count_mismatch"]),
                     ("improves", "baseline", repeat, "FAIL", ["address_mismatch"]), ("improves", "faulty", repeat, "PASS"),
                     ("same_fail", "baseline", repeat, "FAIL", ["timeout"]), ("same_fail", "faulty", repeat, "FAIL", ["timeout"]),
                     ("other_fail", "baseline", repeat, "FAIL", ["address_mismatch"]),
                     ("other_fail", "faulty", repeat, "FAIL", ["address_mismatch", "unconfirmed_write"]),
                     ("broken", "baseline", repeat, "ERROR", ["state_read_failed"]), ("broken", "faulty", repeat, "ERROR", ["state_read_failed"]),
                     ("fine", "baseline", repeat, "PASS", (), 640), ("fine", "faulty", repeat, "PASS", (), 700)]
        rows += [("unsure", "baseline", 1, "PASS"), ("unsure", "faulty", 1, "INCONCLUSIVE", ["first_audio_playback_unavailable"], 0)]
        self.comparison = build_comparison(results_for(rows), "baseline", "faulty")
        self.by_id = {c["scenario_id"]: c for c in self.comparison["cases"]}

    def test_each_case_lands_in_the_right_group(self):
        self.assertEqual({k: v["category"] for k, v in self.by_id.items()},
                         {"regresses": "regression", "improves": "improvement", "same_fail": "unchanged_failure",
                          "other_fail": "changed_failure", "broken": "invalid_or_unavailable", "fine": "unchanged_pass",
                          "unsure": "invalid_or_unavailable"})
        self.assertEqual(self.comparison["category_counts"]["invalid_or_unavailable"], {"count": 2, "of": 7})
        self.assertTrue(self.by_id["unsure"]["changed"])
        self.assertFalse(self.by_id["broken"]["changed"])

    def test_attempts_scenarios_and_repeats_are_separate_numbers(self):
        totals = self.comparison["totals"]["baseline"]
        self.assertEqual((totals["attempts"], totals["distinct_scenarios"], totals["repeats_per_scenario"]), (13, 7, [1, 2]))
        self.assertEqual(self.by_id["regresses"]["baseline"], {"attempts": 2, "verdicts": {"PASS": 2}, "status": "PASS",
                                                               "reason_codes": {}, "policy_failure_attempts": 0})

    def test_every_aggregate_carries_its_denominator(self):
        base, cand = self.comparison["totals"]["baseline"], self.comparison["totals"]["faulty"]
        self.assertEqual(base["verdicts"], {"PASS": {"count": 5, "of": 13}, "FAIL": {"count": 6, "of": 13},
                                            "ERROR": {"count": 2, "of": 13}, "INCONCLUSIVE": {"count": 0, "of": 13}})
        self.assertEqual(base["pass_rate_valid_attempts"], {"count": 5, "of": 11})
        self.assertEqual(cand["pass_rate_valid_attempts"], {"count": 4, "of": 10})
        self.assertEqual(base["scenarios_passing_every_repeat"], {"count": 3, "of": 7})
        self.assertEqual(cand["policy_failure_attempts"], {"count": 2, "of": 13})
        self.assertEqual(cand["scenarios_with_policy_failure"], {"count": 1, "of": 7})

    def test_policy_failures_stay_visible_when_aggregates_improve(self):
        # A candidate that passes more overall but introduces an unconfirmed write.
        rows = [("a", "baseline", 1, "FAIL", ["booking_count_mismatch"]), ("a", "faulty", 1, "PASS"),
                ("b", "baseline", 1, "FAIL", ["address_mismatch"]), ("b", "faulty", 1, "PASS"),
                ("c", "baseline", 1, "PASS"), ("c", "faulty", 1, "FAIL", ["unconfirmed_write"])]
        comparison = build_comparison(results_for(rows), "baseline", "faulty")
        self.assertGreater(comparison["totals"]["faulty"]["pass_rate_all_attempts"]["count"],
                           comparison["totals"]["baseline"]["pass_rate_all_attempts"]["count"])
        self.assertEqual([(p["scenario_id"], p["variant"], p["codes"]) for p in comparison["policy_failures"]],
                         [("c", "faulty", ["unconfirmed_write"])])
        text = render_comparison(comparison)
        self.assertIn("| `c` | faulty | 1 | unconfirmed_write |", text)
        self.assertIn("| Attempts with a policy failure / all attempts | 0/3 (0.0%) | 1/3 (33.3%) |", text)

    def test_metric_differences_and_unavailable_metrics(self):
        fine = self.by_id["fine"]["metrics"]["first_audio_playback_ms"]
        self.assertEqual((fine["baseline"]["mean_ms"], fine["candidate"]["mean_ms"], fine["mean_delta_ms"],
                          fine["candidate"]["available"]), (640.0, 700.0, 60.0, {"count": 2, "of": 2}))
        unsure = self.by_id["unsure"]["metrics"]["first_audio_playback_ms"]
        self.assertEqual((unsure["candidate"]["mean_ms"], unsure["candidate"]["available"], unsure["mean_delta_ms"]),
                         (None, {"count": 0, "of": 1}, None))

    def test_rendered_comparison_has_every_required_section(self):
        text = render_comparison(self.comparison)
        for heading in ("## Scope", "## Verdict counts", "## Policy failures", "## Changed cases (3 of 7 scenarios)",
                        "## Unchanged failures (1 of 7 scenarios)", "## Invalid or unavailable cases (2 of 7 scenarios)",
                        "## Audio metric differences", "## Measured runner duration"):
            self.assertIn(heading, text)
        self.assertIn("| baseline | 13 | 7 | 1, 2 |", text)
        self.assertIn("| baseline | 5/13 (38.5%) | 6/13 (46.2%) | 2/13 (15.4%) | 0/13 (0.0%) |", text)
        self.assertIn("| `same_fail` | unchanged_failure | FAIL 2/2 | FAIL 2/2 | timeout (2/2) | timeout (2/2) |", text)
        # Changed, unchanged and invalid case rows link to each attempt's evidence.
        for scenario in ("regresses", "same_fail", "broken"):
            row = next(line for line in text.splitlines() if line.startswith("| `%s` |" % scenario))
            self.assertIn("[baseline r1](attempts/x/evidence.json)", row)
            self.assertIn("[faulty r2](attempts/x/evidence.json)", row)
        self.assertIn("unavailable (0/1 (0.0%))", text)
        self.assertIn("+60.0 ms", text)

    def test_run_equivalence_detects_differences(self):
        left = results_for([("a", "baseline", 1, "PASS"), ("a", "faulty", 1, "FAIL", ["timeout"])])
        same = results_for([("a", "faulty", 1, "FAIL", ["timeout"]), ("a", "baseline", 1, "PASS")])
        other = results_for([("a", "baseline", 1, "PASS"), ("a", "faulty", 1, "FAIL", ["address_mismatch"])])
        self.assertEqual((compare_runs(left, same)["equivalent"], compare_runs(left, same)["differences"]), (True, []))
        result = compare_runs(left, other)
        self.assertFalse(result["equivalent"])
        self.assertEqual((result["differences"][0]["variant"], result["differences"][0]["a_reasons"],
                          result["differences"][0]["b_reasons"]), ("faulty", ["timeout"], ["address_mismatch"]))


if __name__ == "__main__":
    unittest.main()
