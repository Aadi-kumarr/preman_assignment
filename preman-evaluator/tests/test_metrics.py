"""Audio metric calculation from saved events: pairing by IDs, rejection, unavailability."""
import unittest

from preman_eval.metrics import FIRST_PLAYBACK, INTERRUPTION_STOP, compute_audio_metrics

from support import audio_evidence, audio_turn, ev, interrupt_step, playback, stop_events


def first(evidence):
    return compute_audio_metrics(evidence)[FIRST_PLAYBACK]


def stops(evidence):
    return compute_audio_metrics(evidence)[INTERRUPTION_STOP]


class FirstPlaybackTests(unittest.TestCase):
    def test_latency_is_played_minus_utterance_end_for_every_audio_turn(self):
        metrics = first(audio_evidence([audio_turn(1, playback(1)), audio_turn(2, playback(2, latency=700))]))
        self.assertEqual([(m["turn_index"], m["status"], m["value_ms"]) for m in metrics], [(1, "ok", 640), (2, "ok", 700)])
        self.assertEqual(metrics[1]["from"], {"kind": "user_utterance_end", "event_id": "user_utterance_end-2", "at_ms": 2000})
        self.assertEqual(metrics[1]["to"]["at_ms"], 2700)

    def test_metric_is_labelled_with_the_events_clock(self):
        metric = first(audio_evidence([audio_turn(1, playback(1))]))[0]
        self.assertEqual((metric["label"], metric["clock_domain"], metric["timing_source"]),
                         ("simulated", "fixture_clock", "simulated"))
        self.assertEqual(metric["scope"], {"session_id": "s1", "turn_id": "turn-1", "response_id": "response-1"})

    def test_events_are_paired_by_ids_not_by_position(self):
        # Everything arrives in one shuffled list on turn 1's response and in the trace.
        shuffled = [playback(2)[1], playback(1)[1], playback(2)[0], playback(1, latency=600)[0]]
        shuffled[1] = ev("first_audio_played", 600, 1)
        evidence = audio_evidence([audio_turn(1, shuffled[:2]), audio_turn(2, shuffled[2:])], trace=shuffled)
        self.assertEqual([m["value_ms"] for m in first(evidence)], [600, 640])

    def test_a_later_timestamped_event_listed_first_does_not_confuse_pairing(self):
        events = [ev("tool_commit", 1250, 1), ev("first_audio_played", 640, 1), ev("user_utterance_end", 0, 1)]
        self.assertEqual(first(audio_evidence([audio_turn(1, events)]))[0]["value_ms"], 640)

    def test_same_event_in_response_and_trace_counts_once(self):
        metric = first(audio_evidence([audio_turn(1, playback(1))], trace=playback(1)))[0]
        self.assertEqual((metric["status"], metric["duplicate_events_deduped"]), ("ok", 0))

    def test_missing_event_is_unavailable_never_zero(self):
        for missing in ("user_utterance_end", "first_audio_played"):
            with self.subTest(missing=missing):
                events = [e for e in playback(1) if e["kind"] != missing]
                metric = first(audio_evidence([audio_turn(1, events)]))[0]
                self.assertEqual((metric["status"], metric["value_ms"]), ("unavailable", None))
                self.assertIn("no %s event" % missing, metric["problems"][0])

    def test_no_events_at_all_is_unavailable(self):
        metric = first(audio_evidence([audio_turn(1, [])]))[0]
        self.assertEqual((metric["status"], metric["value_ms"], len(metric["problems"])), ("unavailable", None, 2))

    def test_unanswered_audio_turn_is_unavailable(self):
        turn = audio_turn(1, [], outcome="timeout", body=None)
        metric = first(audio_evidence([turn], trace=[]))[0]
        self.assertEqual(metric["status"], "unavailable")
        self.assertIn("no response (timeout)", metric["problems"][0])

    def test_end_before_start_is_rejected(self):
        events = [ev("user_utterance_end", 900, 1), ev("first_audio_played", 640, 1)]
        metric = first(audio_evidence([audio_turn(1, events)]))[0]
        self.assertEqual((metric["status"], metric["value_ms"]), ("incompatible", None))
        self.assertIn("impossible timestamps", metric["problems"][0])

    def test_mismatched_ids_are_rejected(self):
        cases = {
            "response_id": [ev("user_utterance_end", 0, 1), ev("first_audio_played", 640, 1, response="response-9")],
            "turn_id": [ev("user_utterance_end", 0, 1), dict(ev("first_audio_played", 640, 1), turn_id="turn-9")],
            "session_id": [ev("user_utterance_end", 0, 1), ev("first_audio_played", 640, 1, session="other")],
            "missing response_id": [ev("user_utterance_end", 0, 1), ev("first_audio_played", 640, 1, response=None)],
        }
        for name, events in cases.items():
            with self.subTest(mismatch=name):
                metric = first(audio_evidence([audio_turn(1, events)]))[0]
                self.assertEqual((metric["status"], metric["value_ms"]), ("incompatible", None))
                self.assertIn("mismatched IDs", metric["problems"][0])

    def test_events_from_another_turn_in_this_response_are_rejected(self):
        metric = first(audio_evidence([audio_turn(1, playback(2))]))[0]
        self.assertEqual(metric["status"], "incompatible")

    def test_turn_response_for_another_session_is_rejected(self):
        turn = audio_turn(1, playback(1))
        turn["body"]["session_id"] = "someone-else"
        metric = first(audio_evidence([turn]))[0]
        self.assertEqual((metric["status"], metric["value_ms"]), ("incompatible", None))

    def test_different_clocks_are_rejected(self):
        events = [ev("user_utterance_end", 0, 1), ev("first_audio_played", 640, 1, clock_domain="wall_clock")]
        metric = first(audio_evidence([audio_turn(1, events)]))[0]
        self.assertEqual(metric["status"], "incompatible")
        self.assertIn("clock_domain differs", metric["problems"][0])

    def test_unusable_timestamps_are_rejected(self):
        for bad in (None, "640", True, float("nan")):
            with self.subTest(at_ms=bad):
                events = [ev("user_utterance_end", 0, 1), ev("first_audio_played", bad, 1)]
                metric = first(audio_evidence([audio_turn(1, events)]))[0]
                self.assertEqual((metric["status"], metric["value_ms"]), ("incompatible", None))

    def test_conflicting_copies_of_one_event_are_rejected(self):
        trace = [ev("user_utterance_end", 0, 1), ev("first_audio_played", 999, 1)]  # same event_id, different time
        metric = first(audio_evidence([audio_turn(1, playback(1))], trace=trace))[0]
        self.assertEqual(metric["status"], "incompatible")
        self.assertIn("conflicting contents", metric["problems"][0])

    def test_chat_evidence_has_no_audio_metrics(self):
        from support import make_evidence
        self.assertEqual(compute_audio_metrics(make_evidence()), {FIRST_PLAYBACK: [], INTERRUPTION_STOP: []})


class InterruptionTests(unittest.TestCase):
    def conversation(self, interrupt_events, **kwargs):
        return audio_evidence([audio_turn(1, playback(1)), interrupt_step(2, interrupt_events), audio_turn(3, playback(2), number=2)], **kwargs)

    def test_latency_is_playback_stopped_minus_user_speech_start(self):
        metric = stops(self.conversation(stop_events(1)))[0]
        self.assertEqual((metric["status"], metric["value_ms"], metric["turn_index"], metric["interrupts_turn_index"]),
                         ("ok", 320, 2, 1))
        self.assertEqual((metric["from"]["at_ms"], metric["to"]["at_ms"], metric["label"]), (900, 1220, "simulated"))
        self.assertEqual(metric["scope"]["response_id"], "response-1")

    def test_interrupt_does_not_disturb_first_playback_of_neighbouring_turns(self):
        self.assertEqual([m["value_ms"] for m in first(self.conversation(stop_events(1)))], [640, 640])

    def test_repeated_interrupts_with_identical_events_are_deduplicated(self):
        evidence = audio_evidence([audio_turn(1, playback(1)), interrupt_step(2, stop_events(1, serial=1)),
                                   interrupt_step(3, stop_events(1, serial=2))])
        metrics = stops(evidence)
        self.assertEqual([(m["status"], m["value_ms"]) for m in metrics], [("ok", 320), ("ok", 320)])
        self.assertEqual(metrics[0]["duplicate_events_deduped"], 2)  # one extra start and one extra stop

    def test_conflicting_duplicate_interrupt_events_are_rejected(self):
        evidence = audio_evidence([audio_turn(1, playback(1)), interrupt_step(2, stop_events(1, serial=1)),
                                   interrupt_step(3, stop_events(1, latency=500, serial=2))])
        metrics = stops(evidence)
        self.assertEqual([(m["status"], m["value_ms"]) for m in metrics], [("incompatible", None)] * 2)
        self.assertIn("conflicting duplicate playback_stopped events", " ".join(metrics[0]["problems"]))

    def test_missing_stop_event_is_unavailable(self):
        metric = stops(self.conversation(stop_events(1)[:1]))[0]
        self.assertEqual((metric["status"], metric["value_ms"]), ("unavailable", None))

    def test_stop_before_start_is_rejected(self):
        metric = stops(self.conversation(stop_events(1, latency=-50)))[0]
        self.assertEqual((metric["status"], metric["value_ms"]), ("incompatible", None))

    def test_interrupt_events_for_another_response_are_rejected(self):
        metric = stops(self.conversation(stop_events(7)))[0]
        self.assertEqual(metric["status"], "incompatible")
        self.assertIn("mismatched IDs", metric["problems"][0])

    def test_failed_interrupt_request_is_unavailable(self):
        failed = interrupt_step(2, [], outcome="http_error", status=400, body={"error": {"code": "INVALID_INTERRUPT"}})
        metric = stops(audio_evidence([audio_turn(1, playback(1)), failed]))[0]
        self.assertEqual(metric["status"], "unavailable")
        self.assertIn("no response (http_error)", metric["problems"][0])

    def test_interrupt_with_no_answered_turn_before_it_is_unavailable(self):
        unanswered = audio_turn(1, [], outcome="timeout", body=None)
        metric = stops(audio_evidence([unanswered, interrupt_step(2, stop_events(1))], trace=[]))[0]
        self.assertEqual(metric["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
