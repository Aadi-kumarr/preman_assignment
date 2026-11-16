"""Audio grading verdicts, WAV playability, and the audio adapter's requests."""
import base64
import hashlib
import json
import re
import tempfile
import unittest
import wave
from pathlib import Path

from preman_eval.adapters import AudioAdapter, describe_wav, load_utterances
from preman_eval.client import TargetClient
from preman_eval.grader import grade_attempt

from support import (POLICY, STATE_503, FakeTarget, audio_evidence, audio_turn, commit, ev, interrupt_step, playback,
                     stop_events, wav_bytes)

ADDRESS_TEXT = "Change it to 14 Pine Street. Ask me before saving."


def grade(expect, evidence):
    scenario = {"id": "any", "fixture": "any", "modality": "audio", "turn_timeout_ms": 3000, "turns": [], "expect": expect}
    return grade_attempt(scenario, evidence, POLICY, "attempts/x/evidence.json")


def codes(result):
    return [reason["code"] for reason in result["reasons"]]


class AudioLimitGradingTests(unittest.TestCase):
    def test_within_limit_passes_and_limit_is_inclusive(self):
        evidence = audio_evidence([audio_turn(1, playback(1)), audio_turn(2, playback(2))])
        self.assertEqual(grade({"max_first_audio_playback_ms": 1000}, evidence)["verdict"], "PASS")
        self.assertEqual(grade({"max_first_audio_playback_ms": 640}, evidence)["verdict"], "PASS")

    def test_over_limit_fails_and_names_the_turn(self):
        evidence = audio_evidence([audio_turn(1, playback(1)), audio_turn(2, playback(2, latency=1200))])
        result = grade({"max_first_audio_playback_ms": 1000}, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["first_audio_playback_over_limit"]))
        self.assertIn("turn 2 was 1200 ms (fixture_clock clock, simulated), over the 1000 ms limit", result["reasons"][0]["message"])
        self.assertEqual(result["reasons"][0]["category"], "audio_metric")

    def test_every_audio_turn_must_be_within_the_limit(self):
        evidence = audio_evidence([audio_turn(1, playback(1, latency=1500)), audio_turn(2, playback(2, latency=1100))])
        self.assertEqual(codes(grade({"max_first_audio_playback_ms": 1000}, evidence)), ["first_audio_playback_over_limit"] * 2)

    def test_missing_telemetry_is_inconclusive_not_pass(self):
        evidence = audio_evidence([audio_turn(1, playback(1)), audio_turn(2, [])])
        result = grade({"max_first_audio_playback_ms": 1000}, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["first_audio_playback_unavailable"]))
        self.assertIn("turn 2 is unavailable", result["reasons"][0]["message"])

    def test_rejected_timestamps_are_inconclusive(self):
        events = [ev("user_utterance_end", 900, 1), ev("first_audio_played", 640, 1)]
        result = grade({"max_first_audio_playback_ms": 1000}, audio_evidence([audio_turn(1, events)]))
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["first_audio_playback_incompatible"]))
        self.assertIn("impossible timestamps", result["reasons"][0]["message"])

    def test_verified_failure_outranks_unavailable_metric_and_both_are_kept(self):
        evidence = audio_evidence([audio_turn(1, [])], address="40 Pine Street")
        result = grade({"address": "10 Oak Street", "max_first_audio_playback_ms": 1000}, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["address_mismatch", "first_audio_playback_unavailable"]))

    def test_breached_limit_stands_when_another_metric_is_unavailable(self):
        evidence = audio_evidence([audio_turn(1, playback(1, latency=2000)), audio_turn(2, [])])
        result = grade({"max_first_audio_playback_ms": 1000}, evidence)
        self.assertEqual((result["verdict"], codes(result)),
                         ("FAIL", ["first_audio_playback_over_limit", "first_audio_playback_unavailable"]))

    def test_state_error_with_unavailable_metric_is_error(self):
        evidence = audio_evidence([audio_turn(1, [])], state=dict(STATE_503))
        result = grade({"address": "10 Oak Street", "max_first_audio_playback_ms": 1000}, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("ERROR", ["state_read_failed", "first_audio_playback_unavailable"]))

    def test_interruption_limit_pass_fail_and_unavailable(self):
        def conversation(events):
            return audio_evidence([audio_turn(1, playback(1)), interrupt_step(2, events)])
        expect = {"max_interruption_stop_ms": 400}
        self.assertEqual(grade(expect, conversation(stop_events(1)))["verdict"], "PASS")
        slow = grade(expect, conversation(stop_events(1, latency=450)))
        self.assertEqual((slow["verdict"], codes(slow)), ("FAIL", ["interruption_stop_over_limit"]))
        missing = grade(expect, conversation(stop_events(1)[:1]))
        self.assertEqual((missing["verdict"], codes(missing)), ("INCONCLUSIVE", ["interruption_stop_unavailable"]))
        conflict = grade(expect, audio_evidence([audio_turn(1, playback(1)), interrupt_step(2, stop_events(1, serial=1)),
                                                 interrupt_step(3, stop_events(1, latency=390, serial=2))]))
        self.assertEqual((conflict["verdict"], codes(conflict)), ("INCONCLUSIVE", ["interruption_stop_incompatible"] * 2))

    def test_each_requested_interrupt_needs_a_metric(self):
        evidence = audio_evidence([audio_turn(1, playback(1)), interrupt_step(2, stop_events(1)),
                                   audio_turn(3, playback(2), number=2), interrupt_step(4, [])])
        result = grade({"max_interruption_stop_ms": 400}, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["interruption_stop_unavailable"]))
        self.assertIn("turn 4", result["reasons"][0]["message"])

    def test_failed_interrupt_is_a_harness_error_not_an_agent_timeout(self):
        failed = interrupt_step(2, [], outcome="timeout", error="no response within 5000 ms", body=None)
        result = grade({"max_interruption_stop_ms": 400}, audio_evidence([audio_turn(1, playback(1)), failed]))
        self.assertEqual((result["verdict"], codes(result)), ("ERROR", ["interrupt_failed", "interruption_stop_unavailable"]))

    def test_limits_are_not_checked_unless_the_scenario_asks(self):
        evidence = audio_evidence([audio_turn(1, playback(1, latency=99999)), interrupt_step(2, [])])
        result = grade({}, evidence)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["metrics"]["first_audio_playback_ms"][0]["value_ms"], 99999)  # still reported

    def test_changing_the_limit_changes_the_verdict_without_code_changes(self):
        evidence = audio_evidence([audio_turn(1, playback(1))])
        self.assertEqual(grade({"max_first_audio_playback_ms": 640}, evidence)["verdict"], "PASS")
        self.assertEqual(grade({"max_first_audio_playback_ms": 639.5}, evidence)["verdict"], "FAIL")


class AudioPolicyAndEvidenceTests(unittest.TestCase):
    EXPECT = {"no_write_without_confirmation": True}

    def test_spoken_confirmation_counts_as_user_confirmation(self):
        turns = [audio_turn(1, playback(1), utterance=ADDRESS_TEXT), audio_turn(2, playback(2), utterance="Yes, confirm")]
        evidence = audio_evidence(turns, address="14 Pine Street", audit_log=[commit("update_address", 2)])
        self.assertEqual(grade(self.EXPECT, evidence)["verdict"], "PASS")

    def test_unconfirmed_write_in_audio_fails(self):
        turns = [audio_turn(1, playback(1), utterance=ADDRESS_TEXT), audio_turn(2, playback(2), utterance="Yes, confirm")]
        evidence = audio_evidence(turns, audit_log=[commit("update_address", 1, confirmed=False)])
        self.assertEqual(codes(grade(self.EXPECT, evidence)), ["unconfirmed_write"])

    def test_confirmed_write_without_a_spoken_confirmation_fails(self):
        turns = [audio_turn(1, playback(1), utterance=ADDRESS_TEXT)]
        evidence = audio_evidence(turns, audit_log=[commit("update_address", 1)])
        self.assertEqual(codes(grade(self.EXPECT, evidence)), ["write_without_user_confirmation"])

    def test_unknown_recording_makes_the_confirmation_unverifiable(self):
        turns = [audio_turn(1, playback(1), utterance=None)]
        result = grade(self.EXPECT, audio_evidence(turns, audit_log=[commit("update_address", 1)]))
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["confirmation_unverifiable"]))

    def test_unplayable_or_missing_response_audio_is_inconclusive(self):
        broken = audio_turn(1, playback(1))
        broken["audio_artifact"] = {"path": "turn-01.response.wav", "sha256": "0" * 64, "bytes": 3, "playable": False, "error": "bad"}
        result = grade({}, audio_evidence([broken]))
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["response_audio_unplayable"]))
        absent = audio_turn(1, playback(1))
        del absent["audio_artifact"]
        self.assertEqual(codes(grade({}, audio_evidence([absent]))), ["response_audio_missing"])


class WavPlayabilityTests(unittest.TestCase):
    def test_valid_wav_is_playable_with_duration(self):
        info = describe_wav(wav_bytes())
        self.assertEqual((info["playable"], info["duration_ms"], info["sample_rate_hz"], info["channels"],
                          info["sample_width_bits"], info["frames"]), (True, 10.0, 16000, 1, 16, 160))

    def test_garbage_empty_and_truncated_audio_is_not_playable(self):
        good = wav_bytes()
        for name, data in (("garbage", b"not a wav at all"), ("empty", b""), ("header only", good[:44]),
                           ("truncated", good[:-100])):
            with self.subTest(case=name):
                info = describe_wav(data)
                self.assertFalse(info["playable"])
                self.assertTrue(info["error"])


class AudioAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wav = wav_bytes()
        (self.root / "audio").mkdir()
        (self.root / "audio" / "in.wav").write_bytes(self.wav)
        (self.root / "manifest.json").write_text(json.dumps({"files": [{"path": "audio/in.wav", "text": "Yes, confirm"}]}),
                                                 encoding="utf-8")
        self.fake = FakeTarget()
        self.addCleanup(self.fake.close)
        self.client = TargetClient(self.fake.base_url)
        self.adapter = AudioAdapter(self.root, load_utterances(self.root, "manifest.json"))
        self.session = self.client.create_session("r", "baseline", "booking", 2000).json["session_id"]

    def test_sends_the_wav_bytes_as_base64_and_nothing_else(self):
        record = self.adapter.send_turn(self.client, self.session, {"type": "audio", "path": "audio/in.wav"}, 1, 3000, self.root)
        sent = self.fake.calls[-1][3]
        self.assertEqual(set(sent), {"audio_base64", "audio_format"})  # no text, transcript, or expectations
        self.assertEqual(sent["audio_format"], "wav")
        self.assertEqual(base64.b64decode(sent["audio_base64"]), self.wav)
        self.assertEqual(record["request"]["audio_sha256"], hashlib.sha256(self.wav).hexdigest())
        self.assertEqual((record["request"]["utterance_text"], record["outcome"], record["deadline_exceeded"]),
                         ("Yes, confirm", "ok", False))

    def test_response_wav_is_saved_playable_and_referenced_by_pointer(self):
        record = self.adapter.send_turn(self.client, self.session, {"type": "audio", "path": "audio/in.wav"}, 3, 3000, self.root)
        artifact = record["audio_artifact"]
        saved = self.root / artifact["path"]
        self.assertEqual(artifact["path"], "turn-03.response.wav")
        with wave.open(str(saved), "rb") as audio:
            self.assertEqual(audio.getnframes(), artifact["frames"])
        self.assertEqual(artifact["sha256"], hashlib.sha256(saved.read_bytes()).hexdigest())
        self.assertEqual((artifact["playable"], artifact["duration_ms"]), (True, 10.0))
        self.assertEqual(record["body"]["audio_base64"]["extracted_to"], artifact["path"])
        self.assertIsNone(re.search(r"[A-Za-z0-9+/=]{200,}", json.dumps(record)))  # no inline base64 in the JSON
        self.assertEqual([e["kind"] for e in record["body"]["events"]], ["user_utterance_end", "first_audio_played"])

    def test_interrupt_goes_to_the_interrupt_endpoint_with_the_harness_timeout(self):
        self.adapter.send_turn(self.client, self.session, {"type": "audio", "path": "audio/in.wav"}, 1, 3000, self.root)
        record = self.adapter.send_turn(self.client, self.session, {"type": "interrupt"}, 2, 3000, self.root, harness_timeout_ms=1234)
        self.assertEqual(self.fake.calls[-1], ("POST", "interrupt", self.session, {"action": "interrupt"}))
        self.assertEqual((record["type"], record["outcome"], record["timeout_ms"]), ("interrupt", "ok", 1234))
        self.assertNotIn("deadline_exceeded", record)
        self.assertEqual({e["kind"] for e in record["body"]["events"]}, {"user_speech_start", "playback_stopped"})

    def test_unplayable_response_audio_is_recorded(self):
        self.fake.routes[("POST", "turn")] = (200, {"turn_id": "turn-1", "response_id": "response-1", "audio_format": "wav",
                                                   "audio_base64": base64.b64encode(b"junk").decode(), "events": []})
        record = self.adapter.send_turn(self.client, self.session, {"type": "audio", "path": "audio/in.wav"}, 1, 3000, self.root)
        self.assertFalse(record["audio_artifact"]["playable"])

    def test_text_step_is_refused(self):
        with self.assertRaises(ValueError):
            self.adapter.send_turn(self.client, self.session, {"type": "text", "text": "hi"}, 1, 3000, self.root)

    def test_missing_manifest_means_unknown_utterances(self):
        self.assertEqual(load_utterances(self.root, "nope.json"), {})


if __name__ == "__main__":
    unittest.main()
