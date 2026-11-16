"""Client and runner tests against a scripted local fake (no real target needed)."""
import json
import tempfile
import time
import unittest
import wave
from pathlib import Path

from preman_eval.adapters import ChatAdapter
from preman_eval.client import TargetClient, TargetTimeout, TargetTransportError
from preman_eval.config import RunConfig
from preman_eval.report import build_observed_table, build_report, load_run
from preman_eval.runner import RunError, run_suite, split_runnable
from preman_eval.scenarios import load_scenarios

from support import BOOK, CONFIRM, SLOT, FakeTarget, booking, scenario_def, wav_bytes

HTML_501 = "<!DOCTYPE HTML><html><body><h1>Error response</h1><p>Error code: 501</p></body></html>"
BOOKED_STATE = (200, {"authoritative": True, "bookings": [booking()], "address": "10 Oak Street", "audit_log": []})
BOOKING_EXPECT = {"booking": {"count": 1, "customer_id": "C1", "starts_at": SLOT}}


class ClientTests(unittest.TestCase):
    def test_non_json_error_body_is_returned_not_raised(self):
        fake = FakeTarget({("PUT", "health"): (501, HTML_501)})
        self.addCleanup(fake.close)
        result = TargetClient(fake.base_url).request("PUT", "/health", {}, 2000)
        self.assertEqual((result.status, result.json), (501, None))
        self.assertIn("Error code: 501", result.text)

    def test_json_error_body_is_parsed(self):
        fake = FakeTarget({("GET", "state"): (503, {"error": {"code": "STATE_UNAVAILABLE", "message": "m"}})})
        self.addCleanup(fake.close)
        result = TargetClient(fake.base_url).get_state("s1", 2000)
        self.assertEqual((result.status, result.json["error"]["code"]), (503, "STATE_UNAVAILABLE"))

    def test_timeout_and_refused_connection_are_distinct_errors(self):
        fake = FakeTarget({("GET", "health"): lambda f, b: (time.sleep(0.5), (200, {}))[1]})
        self.addCleanup(fake.close)
        with self.assertRaises(TargetTimeout):
            TargetClient(fake.base_url).health(100)
        closed = FakeTarget()
        closed.close()
        with self.assertRaises(TargetTransportError):
            TargetClient(closed.base_url).health(3000)

    def test_requests_use_the_documented_bodies(self):
        fake = FakeTarget()
        self.addCleanup(fake.close)
        client = TargetClient(fake.base_url)
        session = client.create_session("r1", "baseline", "booking", 2000).json["session_id"]
        client.send_text(session, "Yes, confirm", 2000)
        client.delete_session(session, 2000)
        self.assertEqual(fake.calls[0], ("POST", "sessions", None, {"run_id": "r1", "variant": "baseline", "fixture": "booking"}))
        self.assertEqual(fake.calls[1], ("POST", "turn", session, {"text": "Yes, confirm"}))
        self.assertEqual(fake.calls[2], ("DELETE", "session", session, None))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "starter").mkdir()
        (self.root / "starter" / "target_server.py").write_text("# stand-in\n", encoding="utf-8")

    def run_with(self, routes, *definitions, adapters=None, **config):
        fake = FakeTarget(routes)
        self.addCleanup(fake.close)
        (self.root / "scenarios.json").write_text(
            json.dumps({"schema_version": 1, "scenarios": list(definitions)}), encoding="utf-8")
        cfg = RunConfig(root=self.root, base_url=fake.base_url, starter_dir="starter",
                        scenario_files=["scenarios.json"], runs_dir="runs",
                        **dict({"variants": ["baseline"], "harness_timeout_ms": 2000}, **config)).validate()
        scenarios = load_scenarios([("scenarios.json", self.root / "scenarios.json")], self.root / "starter")
        run_dir = run_suite(cfg, scenarios, adapters=adapters)
        manifest, results = load_run(run_dir)
        return fake, run_dir, manifest, results

    def evidence(self, run_dir, attempt):
        return json.loads((run_dir / attempt["evidence"]).read_text(encoding="utf-8"))

    def test_happy_path_order_evidence_and_artifacts(self):
        fake, run_dir, manifest, results = self.run_with({("GET", "state"): BOOKED_STATE}, scenario_def(BOOKING_EXPECT))
        attempt = results["attempts"][0]
        self.assertEqual(attempt["verdict"], "PASS")
        self.assertEqual([c[:2] for c in fake.calls[1:-1]], [("POST", "sessions"), ("POST", "turn"), ("POST", "turn"),
                                                              ("GET", "state"), ("GET", "trace"), ("DELETE", "session")])
        self.assertEqual([c[3] for c in fake.calls if c[1] == "turn"], [{"text": BOOK}, {"text": CONFIRM}])
        evidence = self.evidence(run_dir, attempt)
        self.assertEqual(evidence["turns"][1]["body"]["turn_id"], "turn-2")
        self.assertEqual(len(attempt["artifacts"]), 2)
        with wave.open(str(run_dir / attempt["artifacts"][0]), "rb") as audio:  # saved WAV is playable
            self.assertGreater(audio.getnframes(), 0)
        self.assertEqual(evidence["turns"][0]["body"]["audio_base64"]["extracted_to"], "turn-01.response.wav")
        self.assertEqual(manifest["attempts"][0]["artifacts"], attempt["artifacts"])

    def test_expectations_are_never_sent_to_the_target(self):
        fake, _, _, _ = self.run_with({}, scenario_def({"address": "10 Oak Street"}, turns=["hello"]))
        sent = json.dumps([call[3] for call in fake.calls])
        self.assertNotIn("expect", sent)
        self.assertNotIn("10 Oak Street", sent)

    def test_state_read_failure_is_error_and_session_is_still_deleted(self):
        routes = {("GET", "state"): (503, {"error": {"code": "STATE_UNAVAILABLE", "message": "m"}})}
        fake, run_dir, _, results = self.run_with(routes, scenario_def(BOOKING_EXPECT))
        attempt = results["attempts"][0]
        self.assertEqual((attempt["verdict"], [r["code"] for r in attempt["reasons"]]), ("ERROR", ["state_read_failed"]))
        self.assertEqual(fake.count("DELETE", "session"), 1)
        self.assertEqual(fake.sessions, set())
        self.assertEqual(self.evidence(run_dir, attempt)["state"]["body"]["error"]["code"], "STATE_UNAVAILABLE")

    def test_html_error_on_a_turn_is_error_and_later_turns_are_not_sent(self):
        fake, run_dir, _, results = self.run_with({("POST", "turn"): (501, HTML_501)}, scenario_def(BOOKING_EXPECT))
        attempt = results["attempts"][0]
        # The state mismatch is a verified FAIL; the broken turn is kept as an additional ERROR reason.
        self.assertEqual(attempt["verdict"], "FAIL")
        self.assertEqual([(r["code"], r["verdict"]) for r in attempt["reasons"]],
                         [("booking_count_mismatch", "FAIL"), ("turn_failed", "ERROR")])
        evidence = self.evidence(run_dir, attempt)
        self.assertIn("Error code: 501", evidence["turns"][0]["body_text"])
        self.assertEqual(evidence["turns"][1]["outcome"], "not_sent")
        self.assertEqual((fake.count("POST", "turn"), fake.count("DELETE", "session")), (1, 1))

    def test_timeout_is_fail_with_evidence_and_session_is_deleted(self):
        def slow(fake, body):
            time.sleep(0.6)
            return FakeTarget._turn(fake, body)
        fake, run_dir, manifest, results = self.run_with(
            {("POST", "turn"): slow}, scenario_def({"booking": {"count": 0}}, turns=[BOOK, CONFIRM], timeout_ms=150))
        attempt = results["attempts"][0]
        self.assertEqual((attempt["verdict"], [r["code"] for r in attempt["reasons"]]), ("FAIL", ["timeout"]))
        turn = self.evidence(run_dir, attempt)["turns"][0]
        self.assertEqual((turn["outcome"], turn["deadline_ms"], turn["deadline_exceeded"]), ("timeout", 150, True))
        self.assertGreaterEqual(turn["elapsed_ms"], 150)
        self.assertEqual(self.evidence(run_dir, attempt)["state"]["outcome"], "ok")  # evidence read before DELETE
        self.assertEqual((fake.count("POST", "turn"), fake.count("DELETE", "session")), (1, 1))
        self.assertEqual(manifest["target"]["health_after"]["active_sessions"], 0)

    def test_evaluator_fault_still_deletes_the_session(self):
        class Exploding(ChatAdapter):
            def send_turn(self, *args, **kwargs):
                raise RuntimeError("adapter blew up")
        fake, _, _, results = self.run_with({}, scenario_def({}, turns=["hello"]), adapters={"chat": Exploding()})
        attempt = results["attempts"][0]
        self.assertEqual((attempt["verdict"], [r["code"] for r in attempt["reasons"]]), ("ERROR", ["harness_exception"]))
        self.assertEqual(fake.count("DELETE", "session"), 1)

    def test_one_failed_attempt_does_not_stop_the_others(self):
        def create(fake, body):
            if body["fixture"] == "broken":
                return 500, "<html>kaput</html>"
            return FakeTarget._create(fake, body)
        _, _, _, results = self.run_with({("POST", "sessions"): create},
                                         scenario_def({}, turns=["a"], scenario_id="first", fixture="broken"),
                                         scenario_def({}, turns=["b"], scenario_id="second"), concurrency=2)
        self.assertEqual([(a["scenario_id"], a["verdict"]) for a in results["attempts"]],
                         [("first", "ERROR"), ("second", "PASS")])
        self.assertEqual(results["attempts"][0]["reasons"][0]["code"], "session_create_failed")

    def test_scenario_variant_repeat_matrix_uses_isolated_sessions(self):
        fake, _, manifest, results = self.run_with(
            {}, scenario_def({}, turns=["a"], scenario_id="one"), scenario_def({}, turns=["b"], scenario_id="two"),
            variants=["baseline", "faulty"], repeats=2, concurrency=3)
        self.assertEqual(manifest["counts"], {"distinct_scenarios": 2, "variants": 2, "repeats": 2, "attempts": 8})
        self.assertEqual(len(results["attempts"]), 8)
        self.assertEqual((fake.count("POST", "sessions"), fake.count("DELETE", "session")), (8, 8))
        self.assertEqual(len({c[2] for c in fake.calls if c[1] == "turn"}), 8)
        self.assertEqual(len({a["attempt_id"] for a in results["attempts"]}), 8)
        self.assertEqual([(a["scenario_id"], a["variant"], a["repeat"]) for a in results["attempts"][:3]],
                         [("one", "baseline", 1), ("one", "baseline", 2), ("one", "faulty", 1)])

    def test_manifest_fields_unique_runs_and_no_absolute_paths(self):
        _, first, manifest, _ = self.run_with({}, scenario_def({}, turns=["a"]))
        _, second, _, _ = self.run_with({}, scenario_def({}, turns=["a"]))
        self.assertNotEqual(first, second)
        self.assertTrue((first / "report.md").is_file() and (second / "report.md").is_file())
        self.assertEqual(manifest["status"], "completed")
        self.assertRegex(manifest["started_at_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertRegex(manifest["starter"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(manifest["starter"]["unchanged_during_run"])
        self.assertRegex(manifest["scenario_files"][0]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["evaluator"]["source_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(manifest["evaluator"]["git_commit"])
        self.assertEqual((manifest["concurrency"], manifest["repeats"], manifest["harness_timeout_ms"]), (1, 1, 2000))
        copy = first / manifest["scenario_files"][0]["copy"]
        self.assertEqual(copy.read_bytes(), (self.root / "scenarios.json").read_bytes())
        for path in first.rglob("*"):
            if path.suffix in (".json", ".md"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(str(self.root), text, path.name)
                self.assertNotIn(self.root.as_posix(), text, path.name)
                self.assertNotIn("\\\\", text, path.name)

    def test_unreachable_target_is_a_clear_error_before_any_run_directory(self):
        closed = FakeTarget()
        closed.close()
        cfg = RunConfig(root=self.root, base_url=closed.base_url, starter_dir="starter",
                        scenario_files=["scenarios.json"], harness_timeout_ms=3000).validate()
        with self.assertRaises(RunError) as caught:
            run_suite(cfg, [])
        self.assertIn("not reachable", str(caught.exception))
        self.assertFalse((self.root / "runs").exists())

    def test_report_shows_counts_denominators_and_reasons(self):
        routes = {("GET", "state"): (200, {"authoritative": True, "bookings": [], "address": "10 Oak Street", "audit_log": []})}
        _, run_dir, manifest, results = self.run_with(routes, scenario_def(BOOKING_EXPECT, scenario_id="needs_booking"),
                                                      scenario_def({}, turns=["a"], scenario_id="plain"), repeats=2)
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertEqual(report, build_report(manifest, results))
        self.assertIn("Attempts: **4** (= 2 x 1 x 2)", report)
        self.assertIn("| baseline | 4 | 2/4 (50.0%) | 2/4 (50.0%) | 0/4 (0.0%) | 0/4 (0.0%) |", report)
        self.assertIn("booking_count_mismatch (2/2)", report)
        self.assertIn("| baseline | booking_count_mismatch | FAIL | 2/4 (50.0%) |", report)
        self.assertIn("](attempts/0001-needs_booking-baseline-r1/evidence.json)", report)
        observed = build_observed_table(run_dir)
        self.assertIn("| `needs_booking` | baseline | 1 | ok (HTTP 200) | 0 |", observed)

    def test_every_supported_modality_is_runnable(self):
        (self.root / "starter" / "in.wav").write_bytes(wav_bytes())
        audio = {"id": "spoken", "fixture": "booking", "modality": "audio", "turn_timeout_ms": 3000,
                 "turns": [{"type": "audio", "path": "in.wav"}], "expect": {}}
        (self.root / "scenarios.json").write_text(json.dumps({"schema_version": 1, "scenarios": [
            audio, scenario_def({}, turns=["a"])]}), encoding="utf-8")
        scenarios = load_scenarios([("scenarios.json", self.root / "scenarios.json")], self.root / "starter")
        runnable, skipped = split_runnable(scenarios)
        self.assertEqual(([s.id for s in runnable], skipped), (["spoken", "case"], []))

    def test_changed_starter_refuses_to_run(self):
        fake = FakeTarget()
        self.addCleanup(fake.close)
        cfg = RunConfig(root=self.root, base_url=fake.base_url, starter_dir="starter", scenario_files=["scenarios.json"],
                        expected_starter_sha256="0" * 64).validate()
        with self.assertRaises(RunError) as caught:
            run_suite(cfg, [])
        self.assertIn("refusing to run", str(caught.exception))
        self.assertFalse((self.root / "runs").exists())


if __name__ == "__main__":
    unittest.main()
