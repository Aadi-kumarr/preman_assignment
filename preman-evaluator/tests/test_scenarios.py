"""Scenario and config validation: invalid input gives clear errors, never a crash."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from preman_eval.config import ConfigError, RunConfig, load_config
from preman_eval.scenarios import ScenarioValidationError, load_scenarios

from support import wav_bytes

VALID = {
    "id": "a", "fixture": "booking", "modality": "chat", "turn_timeout_ms": 3000,
    "turns": [{"type": "text", "text": "hello"}],
    "expect": {"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"},
               "address": "10 Oak Street", "no_write_without_confirmation": True},
}
AUDIO = {
    "id": "b", "fixture": "address", "modality": "audio", "turn_timeout_ms": 3000,
    "turns": [{"type": "audio", "path": "audio/in.wav"}, {"type": "interrupt"}],
    "expect": {"max_first_audio_playback_ms": 1000, "max_interruption_stop_ms": 400},
}


class ScenarioLoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "audio").mkdir()
        (self.root / "audio" / "in.wav").write_bytes(wav_bytes())

    def load(self, *scenarios, raw=None, name="s.json"):
        path = self.root / name
        path.write_text(raw if raw is not None else json.dumps({"schema_version": 1, "scenarios": list(scenarios)}),
                        encoding="utf-8")
        return load_scenarios([(name, path)], self.root)

    def problems(self, *scenarios, **kwargs):
        with self.assertRaises(ScenarioValidationError) as caught:
            self.load(*scenarios, **kwargs)
        return "\n".join(caught.exception.problems)

    def changed(self, base=VALID, **changes):
        item = copy.deepcopy(base)
        for key, value in changes.items():
            if value is None:
                item.pop(key, None)
            else:
                item[key] = value
        return item

    def test_valid_chat_and_audio_scenarios_load(self):
        loaded = self.load(VALID, AUDIO)
        self.assertEqual([s.id for s in loaded], ["a", "b"])
        self.assertEqual(loaded[0].source, "s.json")
        self.assertEqual(loaded[0].definition, VALID)

    def test_duplicate_ids_rejected_across_files(self):
        self.assertIn("duplicate id 'a'", self.problems(VALID, VALID))
        first, second = self.root / "one.json", self.root / "two.json"
        for path in (first, second):
            path.write_text(json.dumps({"schema_version": 1, "scenarios": [VALID]}), encoding="utf-8")
        with self.assertRaises(ScenarioValidationError) as caught:
            load_scenarios([("one.json", first), ("two.json", second)], self.root)
        self.assertIn("duplicate id", str(caught.exception))

    def test_bad_modality_turn_type_and_deadline(self):
        self.assertIn("modality: must be chat or audio", self.problems(self.changed(modality="video")))
        self.assertIn("type: must be one of", self.problems(self.changed(turns=[{"type": "shout", "text": "x"}])))
        for bad in (0, -5, 1.5, "3000", True, None):
            with self.subTest(deadline=bad):
                self.assertIn("turn_timeout_ms", self.problems(self.changed(turn_timeout_ms=bad)))

    def test_unsupported_expect_type_is_a_validation_error(self):
        text = self.problems(self.changed(expect={"sentiment": "happy"}))
        self.assertIn("expect.sentiment: unsupported expectation type", text)

    def test_bad_expect_values(self):
        cases = [({"booking": {"count": -1}}, "count"), ({"booking": {}}, "count: is required"),
                 ({"booking": {"count": 1, "colour": "red"}}, "unsupported booking field"),
                 ({"booking": {"count": True}}, "count"), ({"address": ""}, "address"),
                 ({"no_write_without_confirmation": "yes"}, "true or false"),
                 ({"max_first_audio_playback_ms": 0}, "positive number"), ({"booking": []}, "must be an object")]
        for expect, fragment in cases:
            with self.subTest(expect=expect):
                self.assertIn(fragment, self.problems(self.changed(expect=expect)))

    def test_missing_audio_file_and_unsafe_paths(self):
        def audio(path):
            return self.changed(AUDIO, turns=[{"type": "audio", "path": path}])
        self.assertIn("audio file does not exist", self.problems(audio("audio/missing.wav")))
        self.assertIn("relative path", self.problems(audio("/etc/in.wav")))
        self.assertIn("relative path", self.problems(audio("C:/in.wav")))
        self.assertIn("forward slashes", self.problems(audio("audio\\in.wav")))
        self.assertIn("inside the starter directory", self.problems(audio("../outside.wav")))

    def test_audio_file_must_be_a_readable_wav(self):
        (self.root / "audio" / "broken.wav").write_bytes(b"RIFF not really a wav")
        text = self.problems(self.changed(AUDIO, turns=[{"type": "audio", "path": "audio/broken.wav"}], expect={}))
        self.assertIn("not a readable PCM WAV", text)

    def test_audio_limits_need_something_to_measure(self):
        self.assertIn("audio limits need an audio scenario",
                      self.problems(self.changed(expect={"max_first_audio_playback_ms": 1000})))
        no_interrupt = self.changed(AUDIO, turns=[{"type": "audio", "path": "audio/in.wav"}])
        self.assertIn("needs at least one interrupt turn", self.problems(no_interrupt))

    def test_turn_shape_and_modality_rules(self):
        self.assertIn("text: must be a nonempty string", self.problems(self.changed(turns=[{"type": "text", "text": " "}])))
        self.assertIn("unexpected field", self.problems(self.changed(turns=[{"type": "text", "text": "x", "path": "y"}])))
        self.assertIn("chat scenario cannot contain a audio turn",
                      self.problems(self.changed(turns=[{"type": "audio", "path": "audio/in.wav"}])))
        self.assertIn("interrupt needs a preceding turn",
                      self.problems(self.changed(AUDIO, turns=[{"type": "interrupt"}, {"type": "audio", "path": "audio/in.wav"}])))
        self.assertIn("turns: must be a nonempty list", self.problems(self.changed(turns=[])))

    def test_missing_and_unknown_fields_and_wrong_types(self):
        self.assertIn("expect: is required", self.problems(self.changed(expect=None)))
        self.assertIn("unknown scenario field", self.problems(self.changed(expected_verdict="PASS")))
        self.assertIn("id: must be a nonempty string", self.problems(self.changed(id=7)))
        self.assertIn("must be an object", self.problems("not a scenario"))

    def test_broken_files_report_instead_of_crashing(self):
        self.assertIn("not valid JSON", self.problems(raw="{nope"))
        self.assertIn("top level must be an object", self.problems(raw="[]"))
        self.assertIn("schema_version must be 1", self.problems(raw='{"schema_version": 2, "scenarios": []}'))
        with self.assertRaises(ScenarioValidationError) as caught:
            load_scenarios([("gone.json", self.root / "gone.json")], self.root)
        self.assertIn("cannot read file", str(caught.exception))

    def test_all_problems_are_reported_together(self):
        with self.assertRaises(ScenarioValidationError) as caught:
            self.load(self.changed(modality="x", turn_timeout_ms=0, expect={"nope": 1}))
        self.assertEqual(len(caught.exception.problems), 3)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def load(self, data):
        self.path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return load_config(self.path)

    def test_defaults_and_overrides(self):
        cfg = self.load({"concurrency": 3})
        self.assertEqual((cfg.concurrency, cfg.harness_timeout_ms, cfg.repeats), (3, 5000, 1))
        self.assertEqual(load_config(self.path, {"repeats": 2, "concurrency": None}).repeats, 2)

    def test_invalid_config_is_rejected_clearly(self):
        for data, fragment in (({"concurrency": 0}, "concurrency"), ({"repeats": "2"}, "repeats"),
                               ({"starter_dir": "C:/abs"}, "relative path"), ({"runs_dir": "/abs"}, "relative path"),
                               ({"scenario_files": ["a\\b.json"]}, "forward slashes"), ({"variants": []}, "variants"),
                               ({"colour": 1}, "unknown keys"), ("{", "not valid JSON"), ("[]", "JSON object")):
            with self.subTest(data=data):
                with self.assertRaises(ConfigError) as caught:
                    self.load(data)
                self.assertIn(fragment, str(caught.exception))

    def test_public_config_has_no_root(self):
        public = RunConfig(root=Path(self.tmp.name)).validate().public()
        self.assertNotIn(self.tmp.name, json.dumps(public))


if __name__ == "__main__":
    unittest.main()
