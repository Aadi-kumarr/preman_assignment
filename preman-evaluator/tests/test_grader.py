"""Grader unit tests: verdicts come from evidence, with FAIL > ERROR > INCONCLUSIVE > PASS."""
import copy
import unittest

from preman_eval.grader import grade_attempt, worst

from support import BOOK, CONFIRM, POLICY, SLOT, STATE_503, booking, commit, make_evidence, scenario_def

BOOKING_EXPECT = {"booking": {"count": 1, "customer_id": "C1", "starts_at": SLOT}}
ADDRESS_TEXT = "Change it to 14 Pine Street. Ask me before saving."


def grade(expect, evidence, **scenario):
    return grade_attempt(scenario_def(expect, **scenario), evidence, POLICY, "attempts/x/evidence.json")


def codes(result):
    return [reason["code"] for reason in result["reasons"]]


class BookingTests(unittest.TestCase):
    def test_correct_booking_passes(self):
        result = grade(BOOKING_EXPECT, make_evidence(bookings=[booking()]))
        self.assertEqual((result["verdict"], result["reasons"]), ("PASS", []))

    def test_false_success_claim_fails_on_state_not_on_the_reply(self):
        evidence = make_evidence(bookings=[], turn_overrides={2: {"body": {
            "turn_id": "turn-2", "generated_text": "Your appointment is booked for 10:00 UTC on December 1, 2026."}}})
        result = grade(BOOKING_EXPECT, evidence)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(codes(result), ["booking_count_mismatch"])
        self.assertIn("evidence.json#/state/body/bookings", result["reasons"][0]["evidence"][0])

    def test_wrong_time_and_wrong_customer_fail(self):
        result = grade(BOOKING_EXPECT, make_evidence(bookings=[booking(starts_at="2026-12-01T11:00:00Z")]))
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["booking_starts_at_mismatch"]))
        result = grade(BOOKING_EXPECT, make_evidence(bookings=[booking(customer_id="C2")]))
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["booking_customer_mismatch"]))

    def test_equivalent_timestamp_spelling_is_accepted(self):
        result = grade(BOOKING_EXPECT, make_evidence(bookings=[booking(starts_at="2026-12-01T10:00:00+00:00")]))
        self.assertEqual(result["verdict"], "PASS")

    def test_valid_retry_is_one_booking_but_duplicate_write_fails(self):
        retry_events = [{"kind": "tool_result", "booking_id": "B1", "call_id": "call-1"},
                        {"kind": "tool_result", "booking_id": "B1", "call_id": "call-retry"}]
        result = grade(BOOKING_EXPECT, make_evidence(bookings=[booking()], events=retry_events))
        self.assertEqual(result["verdict"], "PASS")
        observed = next(c for c in result["checks"] if c["check"] == "booking")["observed"]
        self.assertEqual(observed["trace_tool_results"], {"events": 2, "distinct_booking_ids": 1, "authoritative": False})

        duplicate_events = [{"kind": "tool_result", "booking_id": "B1"}, {"kind": "tool_result", "booking_id": "B2"}]
        result = grade(BOOKING_EXPECT, make_evidence(bookings=[booking(1), booking(2)], events=duplicate_events))
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["booking_count_mismatch"]))

    def test_different_booking_id_and_tool_call_order_with_same_final_state_passes(self):
        # Another valid tool path: an availability lookup first, the result reported before the
        # commit, a differently named write tool, and a booking ID in a different format.
        other_id = {"id": "appt-9f2c", "customer_id": "C1", "starts_at": SLOT}
        events = [{"kind": "tool_result", "booking_id": None, "call_id": "lookup-1", "tool": "check_availability"},
                  {"kind": "tool_result", "booking_id": "appt-9f2c", "call_id": "create-1"},
                  dict(commit("create_booking", 2, **other_id), event_id="event-0042")]
        evidence = make_evidence(bookings=[other_id], events=events,
                                 audit_log=[dict(commit("create_booking", 2, **other_id), event_id="event-0042")])
        result = grade(dict(BOOKING_EXPECT, no_write_without_confirmation=True), evidence)
        self.assertEqual((result["verdict"], result["reasons"]), ("PASS", []))
        self.assertEqual(next(c for c in result["checks"] if c["check"] == "booking")["observed"]["bookings"], [other_id])

    def test_count_zero_expectation(self):
        self.assertEqual(grade({"booking": {"count": 0}}, make_evidence(texts=[BOOK]))["verdict"], "PASS")
        self.assertEqual(grade({"booking": {"count": 0}}, make_evidence(bookings=[booking()]))["verdict"], "FAIL")

    def test_no_expectation_means_no_invented_check(self):
        result = grade({}, make_evidence(bookings=[booking(), booking(2)], address="anything"))
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual([c["check"] for c in result["checks"]], ["turn_deadline"])


class AddressTests(unittest.TestCase):
    def test_address_match_and_mismatch(self):
        self.assertEqual(grade({"address": "10 Oak Street"}, make_evidence(texts=[ADDRESS_TEXT]))["verdict"], "PASS")
        result = grade({"address": "10 Oak Street"}, make_evidence(texts=[ADDRESS_TEXT], address="40 Pine Street"))
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["address_mismatch"]))


class ConfirmationRuleTests(unittest.TestCase):
    EXPECT = {"no_write_without_confirmation": True}

    def test_no_writes_passes(self):
        self.assertEqual(grade(self.EXPECT, make_evidence(texts=[ADDRESS_TEXT]))["verdict"], "PASS")

    def test_write_with_confirmed_false_fails(self):
        evidence = make_evidence(texts=[ADDRESS_TEXT], address="40 Pine Street",
                                 audit_log=[commit("update_address", 1, confirmed=False, address="40 Pine Street")])
        result = grade(self.EXPECT, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["unconfirmed_write"]))
        self.assertIn("/state/body/audit_log/0", result["reasons"][0]["evidence"][0])

    def test_confirmed_write_after_user_confirmation_passes(self):
        evidence = make_evidence(texts=[ADDRESS_TEXT, CONFIRM], address="14 Pine Street",
                                 audit_log=[commit("update_address", 2, address="14 Pine Street")])
        self.assertEqual(grade(self.EXPECT, evidence)["verdict"], "PASS")

    def test_audit_flag_alone_is_not_enough(self):
        # The audit log claims confirmed=true, but the user never confirmed.
        evidence = make_evidence(texts=[ADDRESS_TEXT], audit_log=[commit("update_address", 1)])
        result = grade(self.EXPECT, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["write_without_user_confirmation"]))

    def test_confirmation_after_the_write_does_not_count(self):
        evidence = make_evidence(texts=[ADDRESS_TEXT, CONFIRM], audit_log=[commit("update_address", 1)])
        self.assertEqual(codes(grade(self.EXPECT, evidence)), ["write_without_user_confirmation"])

    def test_rule_covers_booking_writes_too(self):
        good = make_evidence(bookings=[booking()], audit_log=[commit("book_appointment", 2, **booking())])
        self.assertEqual(grade(self.EXPECT, good)["verdict"], "PASS")
        bad = make_evidence(texts=[BOOK], bookings=[booking()],
                            audit_log=[commit("book_appointment", 1, confirmed=False, **booking())])
        self.assertEqual(codes(grade(self.EXPECT, bad)), ["unconfirmed_write"])

    def test_missing_confirmed_field_is_a_violation(self):
        entry = commit("update_address", 2)
        del entry["confirmed"]
        self.assertEqual(codes(grade(self.EXPECT, make_evidence(audit_log=[entry]))), ["unconfirmed_write"])

    def test_write_that_cannot_be_tied_to_a_turn_is_inconclusive(self):
        result = grade(self.EXPECT, make_evidence(audit_log=[commit("update_address", 9)]))
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["write_turn_uncorrelated"]))

    def test_confirmation_phrases_come_from_policy(self):
        evidence = make_evidence(texts=[ADDRESS_TEXT, "Go ahead"], audit_log=[commit("update_address", 2)])
        scenario = scenario_def(self.EXPECT, turns=[ADDRESS_TEXT, "Go ahead"])
        self.assertEqual(grade_attempt(scenario, evidence, POLICY)["verdict"], "FAIL")
        self.assertEqual(grade_attempt(scenario, evidence, {"confirmation_phrases": ["go ahead"]})["verdict"], "PASS")

    def test_false_expectation_is_not_applied(self):
        evidence = make_evidence(audit_log=[commit("update_address", 1, confirmed=False)])
        self.assertEqual(grade({"no_write_without_confirmation": False}, evidence)["verdict"], "PASS")


class ErrorAndPrecedenceTests(unittest.TestCase):
    def test_precedence_order(self):
        self.assertEqual(worst(["PASS", "INCONCLUSIVE", "ERROR", "FAIL"]), "FAIL")
        self.assertEqual(worst(["PASS", "INCONCLUSIVE", "ERROR"]), "ERROR")
        self.assertEqual(worst(["PASS", "INCONCLUSIVE"]), "INCONCLUSIVE")
        self.assertEqual(worst([]), "PASS")

    def test_state_read_failure_is_error_even_if_trace_shows_the_commit(self):
        trace = [dict(commit("book_appointment", 2, **booking()), kind="tool_commit")]
        result = grade(BOOKING_EXPECT, make_evidence(state=copy.deepcopy(STATE_503), events=trace))
        self.assertEqual((result["verdict"], codes(result)), ("ERROR", ["state_read_failed"]))
        self.assertIn("STATE_UNAVAILABLE", result["reasons"][0]["message"])

    def test_state_failure_reported_once_for_several_checks(self):
        expect = {"address": "10 Oak Street", "no_write_without_confirmation": True}
        result = grade(expect, make_evidence(state=copy.deepcopy(STATE_503)))
        self.assertEqual(codes(result), ["state_read_failed"])
        self.assertEqual([c["verdict"] for c in result["checks"]], ["PASS", "ERROR", "ERROR"])

    def test_timeout_is_fail_even_when_the_state_check_passes(self):
        evidence = make_evidence(texts=[BOOK], turn_overrides={1: {
            "outcome": "timeout", "elapsed_ms": 410.0, "deadline_ms": 400, "deadline_exceeded": True, "body": None}})
        result = grade({"booking": {"count": 0}}, evidence)
        self.assertEqual((result["verdict"], codes(result)), ("FAIL", ["timeout"]))
        self.assertEqual(next(c for c in result["checks"] if c["check"] == "booking")["verdict"], "PASS")

    def test_timeout_fail_stands_and_state_error_is_kept(self):
        evidence = make_evidence(texts=[BOOK], state=copy.deepcopy(STATE_503),
                                 turn_overrides={1: {"outcome": "timeout", "elapsed_ms": 410.0, "deadline_exceeded": True}})
        result = grade(BOOKING_EXPECT, evidence)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(codes(result), ["timeout", "state_read_failed"])

    def test_late_response_is_a_timeout(self):
        evidence = make_evidence(bookings=[booking()], turn_overrides={2: {"elapsed_ms": 3500.0, "deadline_exceeded": True}})
        self.assertEqual(codes(grade(BOOKING_EXPECT, evidence)), ["timeout"])

    def test_policy_failure_stands_with_harness_error(self):
        evidence = make_evidence(texts=[ADDRESS_TEXT], audit_log=[commit("update_address", 1, confirmed=False)],
                                 cleanup={"outcome": "transport_error", "error": "boom"})
        result = grade({"no_write_without_confirmation": True}, evidence)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(codes(result), ["unconfirmed_write", "session_cleanup_failed"])

    def test_state_mismatch_stays_fail_when_a_turn_errored(self):
        evidence = make_evidence(bookings=[], turn_overrides={
            1: {"outcome": "http_error", "status": 501, "body": None, "body_text": "<html>"},
            2: {"outcome": "not_sent"}})
        result = grade(BOOKING_EXPECT, evidence)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(codes(result), ["booking_count_mismatch", "turn_failed"])
        self.assertEqual([r["verdict"] for r in result["reasons"]], ["FAIL", "ERROR"])
        self.assertNotIn("downgraded_from", result["reasons"][0])

    def test_state_mismatch_stays_fail_when_a_turn_timed_out(self):
        evidence = make_evidence(bookings=[], address="40 Pine Street", turn_overrides={
            1: {"outcome": "timeout", "elapsed_ms": 3001.0, "deadline_exceeded": True, "body": None},
            2: {"outcome": "not_sent"}})
        result = grade(dict(BOOKING_EXPECT, address="10 Oak Street"), evidence)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(codes(result), ["timeout", "booking_count_mismatch", "address_mismatch"])
        self.assertTrue(all(r["verdict"] == "FAIL" for r in result["reasons"]))

    def test_reasons_carry_a_category(self):
        evidence = make_evidence(texts=[ADDRESS_TEXT], address="40 Pine Street", state=None,
                                 audit_log=[commit("update_address", 1, confirmed=False)])
        result = grade({"address": "10 Oak Street", "no_write_without_confirmation": True}, evidence)
        self.assertEqual({r["code"]: r["category"] for r in result["reasons"]},
                         {"address_mismatch": "business_state", "unconfirmed_write": "policy"})

    def test_session_create_failure_is_error_with_missing_state_inconclusive(self):
        evidence = make_evidence(session={"outcome": "http_error", "status": 400, "body": {"error": {"code": "INVALID_SESSION"}}},
                                 state={"outcome": "not_attempted"}, trace={"outcome": "not_attempted"},
                                 cleanup={"outcome": "not_attempted"}, turn_overrides={1: {"outcome": "not_sent"}, 2: {"outcome": "not_sent"}})
        result = grade(BOOKING_EXPECT, evidence)
        self.assertEqual(result["verdict"], "ERROR")
        self.assertEqual(codes(result), ["session_create_failed", "state_evidence_missing"])

    def test_harness_exception_and_trace_failure_are_errors(self):
        evidence = make_evidence(bookings=[booking()], harness_errors=["RuntimeError: boom"],
                                 trace={"outcome": "timeout", "error": "no response"})
        result = grade(BOOKING_EXPECT, evidence)
        self.assertEqual(result["verdict"], "ERROR")
        self.assertEqual(sorted(codes(result)), ["harness_exception", "trace_read_failed"])

    def test_audio_limit_with_nothing_to_measure_is_inconclusive_not_a_silent_pass(self):
        result = grade({"max_first_audio_playback_ms": 1000}, make_evidence())
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["first_audio_playback_unavailable"]))

    def test_unreadable_evidence_is_explicitly_inconclusive(self):
        result = grade(BOOKING_EXPECT, {"evidence_missing": True, "evidence_error": "FileNotFoundError"})
        self.assertEqual((result["verdict"], codes(result)), ("INCONCLUSIVE", ["evidence_missing"]))

    def test_verdict_ignores_names_and_variant_labels(self):
        evidence = make_evidence(bookings=[booking(starts_at="2026-12-01T11:00:00Z")], variant="baseline",
                                 scenario_id="looks_fine", run_id="r")
        renamed = dict(evidence, variant="faulty", scenario_id="chat_booking", run_id="other")
        first = grade(BOOKING_EXPECT, evidence, scenario_id="looks_fine", fixture="x")
        second = grade(BOOKING_EXPECT, renamed, scenario_id="chat_booking", fixture="booking")
        self.assertEqual(first, second)
        self.assertEqual(first["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
