"""Integration: the complete path against the real supplied target over HTTP.

The target runs as a child process on an ephemeral port, started from the
starter folder with bytecode writing disabled so the starter is left untouched.
"""
import hashlib
import json
import re
import tempfile
import unittest
import wave
from pathlib import Path

from preman_eval.client import TargetClient
from preman_eval.config import RunConfig
from preman_eval.hashing import sha256_tree
from preman_eval.report import load_run
from preman_eval.runner import run_suite, split_runnable
from preman_eval.scenarios import load_scenarios
from preman_eval.target_process import launched_target

from support import EVALUATOR_ROOT, STARTER_AVAILABLE, STARTER_DIR, STARTER_RELATIVE


class RealTargetIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A missing starter is a failure, never a skip: these tests are required.
        if not STARTER_AVAILABLE:
            raise AssertionError("Starter kit not found at %s. Put it beside the evaluator or set PREMAN_STARTER_DIR "
                                 "(relative to the evaluator folder)." % STARTER_RELATIVE)
        cls.starter_hash_before = sha256_tree(STARTER_DIR)
        # 600 ms keeps the slow fixture above the supplied 400 ms deadline while keeping the test quick.
        cls.target = launched_target(STARTER_DIR, port=0, slow_ms=600)
        cls.base_url = cls.target.__enter__()
        cls.tmp = tempfile.TemporaryDirectory()
        files = [STARTER_RELATIVE + "/scenarios.json", "scenarios_added.json"]
        scenarios = load_scenarios([(f, EVALUATOR_ROOT / f) for f in files], STARTER_DIR)
        cls.scenarios, cls.skipped = split_runnable(scenarios)
        cls.files = files

    @classmethod
    def tearDownClass(cls):
        cls.target.__exit__(None, None, None)
        cls.tmp.cleanup()

    def run_suite(self, name, **config):
        cfg = RunConfig(root=EVALUATOR_ROOT, base_url=self.base_url, starter_dir=STARTER_RELATIVE,
                        scenario_files=self.files, runs_dir=Path(self.tmp.name) / name, **config).validate()
        run_dir = run_suite(cfg, self.scenarios, self.skipped)
        return (run_dir,) + load_run(run_dir)

    def verdicts(self, results):
        return {(a["scenario_id"], a["variant"], a["repeat"]): a["verdict"] for a in results["attempts"]}

    def test_chat_suite_end_to_end_both_variants(self):
        run_dir, manifest, results = self.run_suite("c1", concurrency=1)
        by_case = {(a["scenario_id"], a["variant"]): a for a in results["attempts"]}

        def outcome(scenario, variant):
            attempt = by_case[(scenario, variant)]
            return attempt["verdict"], sorted(r["code"] for r in attempt["reasons"])

        self.assertEqual(outcome("chat_booking", "baseline"), ("PASS", []))
        self.assertEqual(outcome("chat_booking", "faulty"), ("FAIL", ["booking_starts_at_mismatch"]))
        self.assertEqual(outcome("chat_false_success", "baseline"), ("PASS", []))
        self.assertEqual(outcome("chat_false_success", "faulty"), ("FAIL", ["booking_count_mismatch"]))
        self.assertEqual(outcome("chat_retry", "baseline"), ("PASS", []))
        self.assertEqual(outcome("chat_retry", "faulty"), ("FAIL", ["booking_count_mismatch"]))
        self.assertEqual(outcome("chat_unconfirmed_address", "baseline"), ("PASS", []))
        self.assertEqual(outcome("chat_unconfirmed_address", "faulty"), ("FAIL", ["address_mismatch", "unconfirmed_write"]))
        self.assertEqual(outcome("chat_state_error", "baseline"), ("ERROR", ["state_read_failed"]))
        self.assertEqual(outcome("chat_state_error", "faulty"), ("ERROR", ["state_read_failed"]))
        self.assertEqual(outcome("chat_timeout", "baseline"), ("FAIL", ["timeout"]))
        self.assertEqual(outcome("chat_timeout", "faulty"), ("FAIL", ["timeout"]))
        self.assertEqual(outcome("chat_address_confirmed", "baseline"), ("PASS", []))

        # Valid retry: two tool results in the trace, one persisted booking.
        retry = next(c for c in by_case[("chat_retry", "baseline")]["checks"] if c["check"] == "booking")
        self.assertEqual((retry["observed"]["count"], retry["observed"]["trace_tool_results"]["events"],
                          retry["observed"]["trace_tool_results"]["distinct_booking_ids"]), (1, 2, 1))

        # Evidence on disk: raw turn, state, trace, playable audio reference.
        evidence = json.loads((run_dir / by_case[("chat_booking", "baseline")]["evidence"]).read_text(encoding="utf-8"))
        self.assertEqual(evidence["turns"][1]["body"]["input_mode"], "chat")
        self.assertTrue(evidence["state"]["body"]["authoritative"])
        self.assertTrue(any(e["kind"] == "tool_commit" for e in evidence["trace"]["body"]["events"]))
        self.assertTrue((run_dir / by_case[("chat_booking", "baseline")]["artifacts"][0]).is_file())

        # Cleanup, including after the timeout: no sessions left, and the deleted session is gone.
        self.assertEqual(manifest["target"]["health_after"]["active_sessions"], 0)
        timed_out = json.loads((run_dir / by_case[("chat_timeout", "baseline")]["evidence"]).read_text(encoding="utf-8"))
        self.assertEqual((timed_out["turns"][0]["outcome"], timed_out["cleanup"]["outcome"]), ("timeout", "ok"))
        gone = TargetClient(self.base_url).get_state(timed_out["session"]["body"]["session_id"], 2000)
        self.assertEqual(gone.status, 404)

        self.assertEqual(manifest["skipped_scenarios"], [])
        self.assertTrue(manifest["starter"]["unchanged_during_run"])

    def test_audio_scenarios_end_to_end_both_variants(self):
        audio = [s for s in self.scenarios if s.modality == "audio"]
        cfg = RunConfig(root=EVALUATOR_ROOT, base_url=self.base_url, starter_dir=STARTER_RELATIVE,
                        scenario_files=self.files, runs_dir=Path(self.tmp.name) / "audio").validate()
        run_dir = run_suite(cfg, audio)
        manifest, results = load_run(run_dir)
        by_case = {(a["scenario_id"], a["variant"]): a for a in results["attempts"]}

        booking = by_case[("audio_booking", "baseline")]
        self.assertEqual((booking["verdict"], booking["reasons"]), ("PASS", []))
        self.assertEqual([(m["status"], m["value_ms"], m["label"], m["clock_domain"])
                          for m in booking["metrics"]["first_audio_playback_ms"]],
                         [("ok", 640, "simulated", "fixture_clock")] * 2)
        evidence_text = (run_dir / booking["evidence"]).read_text(encoding="utf-8")
        evidence = json.loads(evidence_text)
        turn = evidence["turns"][0]
        # Real WAV bytes were sent: the target's own event reports the hash and size of what it received.
        sent = (STARTER_DIR / "fixtures" / "audio" / "booking_request.wav").read_bytes()
        received = next(e for e in turn["body"]["events"] if e["kind"] == "input_received")
        self.assertEqual((received["mode"], received["audio_byte_count"], received["audio_sha256"]),
                         ("audio", len(sent), hashlib.sha256(sent).hexdigest()))
        self.assertEqual(turn["request"]["audio_sha256"], received["audio_sha256"])
        # The response WAV is saved, playable, hashed, and referenced by pointer rather than inline base64.
        saved = run_dir / booking["artifacts"][0]
        with wave.open(str(saved), "rb") as audio_file:
            self.assertGreater(audio_file.getnframes(), 0)
        self.assertEqual(turn["audio_artifact"]["sha256"], hashlib.sha256(saved.read_bytes()).hexdigest())
        self.assertTrue(turn["audio_artifact"]["playable"])
        self.assertGreater(turn["audio_artifact"]["duration_ms"], 0)
        self.assertEqual(turn["body"]["audio_base64"]["extracted_to"], "turn-01.response.wav")
        self.assertIsNone(re.search(r"[A-Za-z0-9+/]{400,}", evidence_text))

        self.assertEqual((by_case[("audio_booking", "faulty")]["verdict"],
                          [r["code"] for r in by_case[("audio_booking", "faulty")]["reasons"]]),
                         ("FAIL", ["booking_starts_at_mismatch"]))

        good, bad = by_case[("audio_interruption", "baseline")], by_case[("audio_interruption", "faulty")]
        self.assertEqual(good["verdict"], "PASS")
        self.assertEqual([(m["status"], m["value_ms"], m["interrupts_turn_index"]) for m in good["metrics"]["interruption_stop_ms"]],
                         [("ok", 320, 1)])
        self.assertEqual((bad["verdict"], sorted(r["code"] for r in bad["reasons"])),
                         ("FAIL", ["address_mismatch", "unconfirmed_write"]))
        steps = json.loads((run_dir / good["evidence"]).read_text(encoding="utf-8"))["turns"]
        self.assertEqual([(s["type"], s["outcome"]) for s in steps], [("audio", "ok"), ("interrupt", "ok"), ("audio", "ok")])
        self.assertEqual({e["kind"] for e in steps[1]["body"]["events"]},
                         {"user_speech_start", "cancellation_requested", "playback_stopped"})

        confirmed = by_case[("audio_address_confirmed", "baseline")]
        self.assertEqual((confirmed["verdict"], confirmed["reasons"]), ("PASS", []))
        self.assertIn("unconfirmed_write", [r["code"] for r in by_case[("audio_address_confirmed", "faulty")]["reasons"]])
        self.assertEqual(manifest["target"]["health_after"]["active_sessions"], 0)
        self.assertTrue((run_dir / "comparison.md").is_file())

    def test_concurrency_and_repeats_give_the_same_verdicts(self):
        _, _, serial = self.run_suite("serial", concurrency=1, repeats=2)
        _, manifest, parallel = self.run_suite("parallel", concurrency=3, repeats=2)
        self.assertEqual(self.verdicts(serial), self.verdicts(parallel))
        self.assertEqual(manifest["counts"]["attempts"], len(self.scenarios) * 2 * 2)
        self.assertEqual(manifest["target"]["health_after"]["active_sessions"], 0)

    def test_starter_folder_is_untouched_by_the_tests(self):
        self.assertEqual(sha256_tree(STARTER_DIR), self.starter_hash_before)
        self.assertFalse(list(STARTER_DIR.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
