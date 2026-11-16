"""Contract tests for the provided target only; candidates implement evaluator tests."""
import base64
import hashlib
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from target_server import make_server, RESPONSE_FILES, SLOT, WRONG_SLOT

BOOK = "Book appointment for C1 at 2026-12-01T10:00:00Z"
ADDRESS = "Change it to 14 Pine Street. Ask me before saving."


def wav_bytes(value):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(int(value).to_bytes(2, "little", signed=True) * 160)
    return buf.getvalue()


class TargetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        fixtures = Path(cls.tmp.name)
        (fixtures / "audio").mkdir()
        inputs = {"booking_request": BOOK, "confirm": "Yes, confirm", "address_request": ADDRESS,
                  "correction": "No, fourteen. Don't save yet."}
        files = []
        cls.audio = {}
        for index, (name, text) in enumerate(inputs.items(), 1):
            data = cls.audio[name] = wav_bytes(index)
            (fixtures / "audio" / (name + ".wav")).write_bytes(data)
            files.append({"path": "audio/" + name + ".wav", "text": text})
        for index, name in enumerate(RESPONSE_FILES, 100):
            (fixtures / "audio" / (name + ".wav")).write_bytes(wav_bytes(index))
        (fixtures / "audio_manifest.json").write_text(json.dumps({"files": files}))
        cls.server = make_server(port=0, fixtures_dir=fixtures, slow_ms=250)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, timeout=2):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    def create(self, fixture="booking", variant="baseline"):
        status, body = self.request("POST", "/sessions", {"run_id": self.id(), "variant": variant, "fixture": fixture})
        self.assertEqual(status, 201)
        session = body["session_id"]
        self.addCleanup(self.request, "DELETE", "/sessions/" + session)
        return session

    def turn(self, session, text):
        status, body = self.request("POST", "/sessions/" + session + "/turn", {"text": text})
        self.assertEqual(status, 200)
        return body

    def state(self, session):
        status, body = self.request("GET", "/sessions/" + session + "/state")
        self.assertEqual(status, 200)
        return body

    def test_health_and_isolated_sessions(self):
        health = self.request("GET", "/health")[1]
        self.assertEqual(health["status"], "ok")
        before = health["active_sessions"]
        first, second = self.create(), self.create()
        self.assertEqual(self.request("GET", "/health")[1]["active_sessions"], before + 2)
        self.turn(first, BOOK)
        self.assertEqual(self.state(first)["bookings"], [])
        self.turn(first, "Yes, confirm")
        self.assertEqual(self.state(first)["bookings"][0]["starts_at"], SLOT)
        self.assertEqual(self.state(second)["bookings"], [])
        self.assertEqual(self.state(second)["address"], "10 Oak Street")
        self.assertEqual(self.request("DELETE", "/sessions/" + first)[0], 200)
        self.assertEqual(self.request("GET", "/health")[1]["active_sessions"], before + 1)
        self.assertEqual(self.request("DELETE", "/sessions/" + second)[0], 200)
        self.assertEqual(self.request("GET", "/health")[1]["active_sessions"], before)

    def test_faulty_wrong_time_and_false_success(self):
        for fixture in ("booking", "false_success"):
            with self.subTest(fixture=fixture):
                session = self.create(fixture, "faulty")
                self.turn(session, BOOK)
                response = self.turn(session, "Yes, confirm")
                self.assertIn("10:00", response["generated_text"])
                bookings = self.state(session)["bookings"]
                self.assertEqual(len(bookings), 0 if fixture == "false_success" else 1)
                if bookings:
                    self.assertEqual(bookings[0]["starts_at"], WRONG_SLOT)

    def test_retry_result_is_not_duplicate_state(self):
        for variant, expected_count in (("baseline", 1), ("faulty", 2)):
            with self.subTest(variant=variant):
                session = self.create("retry", variant)
                self.turn(session, BOOK)
                result = self.turn(session, "Yes, confirm")
                calls = [e for e in result["events"] if e["kind"] == "tool_result"]
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(self.state(session)["bookings"]), expected_count)
                self.assertEqual(len({e["booking_id"] for e in calls}), expected_count)

    def test_address_requires_confirmation_and_audits_bad_write(self):
        good, bad = self.create("address"), self.create("address", "faulty")
        self.turn(good, ADDRESS)
        self.turn(bad, ADDRESS)
        self.assertEqual(self.state(good)["address"], "10 Oak Street")
        self.assertEqual(self.state(bad)["address"], "40 Pine Street")
        self.assertFalse(self.state(bad)["audit_log"][0]["confirmed"])
        self.turn(good, "Yes, confirm")
        self.assertEqual(self.state(good)["address"], "14 Pine Street")
        self.assertTrue(self.state(good)["audit_log"][0]["confirmed"])

    def test_audio_uses_actual_wav_and_retains_byte_evidence(self):
        session = self.create()
        for name in ("booking_request", "confirm"):
            data = self.audio[name]
            status, result = self.request("POST", "/sessions/" + session + "/turn", {
                "audio_base64": base64.b64encode(data).decode(), "audio_format": "wav"})
            self.assertEqual(status, 200)
            evidence = next(e for e in result["events"] if e["kind"] == "input_received")
            self.assertEqual(evidence["audio_byte_count"], len(data))
            self.assertEqual(evidence["audio_sha256"], hashlib.sha256(data).hexdigest())
            self.assertTrue(all(e["response_id"] == result["response_id"] for e in result["events"]))
            with wave.open(io.BytesIO(base64.b64decode(result["audio_base64"])), "rb") as response:
                self.assertGreater(response.getnframes(), 0)
            played = next(e for e in result["events"] if e["kind"] == "first_audio_played")
            end = next(e for e in result["events"] if e["kind"] == "user_utterance_end")
            self.assertEqual(played["at_ms"] - end["at_ms"], 640)
        self.assertEqual(self.state(session)["bookings"][0]["starts_at"], SLOT)

    def test_interruption_keeps_state_and_simulated_provenance(self):
        for variant, address in (("baseline", "10 Oak Street"), ("faulty", "40 Pine Street")):
            session = self.create("address", variant)
            self.turn(session, ADDRESS)
            status, result = self.request("POST", "/sessions/" + session + "/interrupt", {"action": "interrupt"})
            self.assertEqual(status, 200)
            self.assertEqual(result["events"][-1]["at_ms"] - result["events"][0]["at_ms"], 320)
            self.assertTrue(all(e["response_id"] == "response-1" for e in result["events"]))
            self.turn(session, "No, fourteen. Don't save yet.")
            self.assertEqual(self.state(session)["address"], address)
            status, trace = self.request("GET", "/sessions/" + session + "/trace")
            self.assertEqual(status, 200)
            times = [event["at_ms"] for event in trace["events"]]
            self.assertEqual(times, sorted(times))
            self.assertTrue(all(e["timing_source"] == "simulated" for e in trace["events"]))

    def test_state_unavailable_is_explicit_503_for_both_variants(self):
        for variant in ("baseline", "faulty"):
            session = self.create("state_unavailable", variant)
            status, result = self.request("GET", "/sessions/" + session + "/state")
            self.assertEqual(status, 503)
            self.assertEqual(result["error"]["code"], "STATE_UNAVAILABLE")
            self.turn(session, BOOK)
            self.turn(session, "Yes, confirm")
            status, trace = self.request("GET", "/sessions/" + session + "/trace")
            self.assertEqual(status, 200)
            commits = [e for e in trace["events"] if e["kind"] == "tool_commit"]
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0]["starts_at"], SLOT)

    def test_timeout_and_deletion_prevent_delayed_mutation(self):
        session_id = self.create("slow")
        session = self.server.target.session(session_id)
        self.turn(session_id, BOOK)
        original_events = list(session.events)
        with self.assertRaises((TimeoutError, socket.timeout)):
            self.request("POST", "/sessions/" + session_id + "/turn", {"text": "Yes, confirm"}, timeout=.03)
        self.assertEqual(self.request("DELETE", "/sessions/" + session_id)[0], 200)
        time.sleep(.30)
        self.assertEqual(self.request("GET", "/sessions/" + session_id + "/state")[0], 404)
        self.assertEqual(session.events, original_events)
        self.assertEqual(session.bookings, [])

    def test_invalid_inputs_return_errors_without_mutation(self):
        session = self.create()
        bad_inputs = [
            {}, {"text": ""}, {"text": 123}, {"text": BOOK, "audio_base64": "a"},
            {"audio_base64": "%%", "audio_format": "wav"},
            {"audio_base64": base64.b64encode(b"not wave").decode(), "audio_format": "wav"},
            {"audio_base64": base64.b64encode(wav_bytes(777)).decode(), "audio_format": "wav"},
        ]
        for body in bad_inputs:
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/sessions/" + session + "/turn", body)[0], 400)
        self.assertEqual(self.state(session)["bookings"], [])
        self.assertEqual(self.request("POST", "/sessions/" + session + "/interrupt", {"action": "interrupt"})[0], 400)
        self.assertEqual(self.request("POST", "/sessions", {"variant": [], "fixture": "booking", "run_id": "x"})[0], 400)
        self.assertEqual(self.request("POST", "/sessions", {"variant": "baseline", "fixture": [], "run_id": "x"})[0], 400)


if __name__ == "__main__":
    unittest.main()
