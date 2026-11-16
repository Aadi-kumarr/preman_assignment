"""Scripted local chat/audio target, not an evaluator or a real STT/TTS service."""
import argparse
import base64
import binascii
import hashlib
import io
import json
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FIXTURES = {"booking", "false_success", "address", "state_unavailable", "slow", "retry"}
SLOT = "2026-12-01T10:00:00Z"
WRONG_SLOT = "2026-12-01T11:00:00Z"
CONFIRMATIONS = {"yes", "yes confirm", "confirm", "yes, confirm"}
RESPONSE_FILES = ("agent_response", "agent_booked", "agent_saved", "agent_wait", "agent_nochange")


class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def validate_wav(data):
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getcomptype() != "NONE" or audio.getnchannels() not in (1, 2)
                    or audio.getnframes() <= 0 or audio.getframerate() <= 0
                    or audio.getnframes() / audio.getframerate() > 60):
                raise ValueError("Use a nonempty PCM WAV of at most 60 seconds")
            expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
            if len(audio.readframes(audio.getnframes())) != expected:
                raise ValueError("Truncated WAV frames")
    except (wave.Error, EOFError, ValueError) as exc:
        raise APIError(400, "INVALID_AUDIO", str(exc)) from exc


class Session:
    def __init__(self, run_id, variant, fixture):
        self.id, self.run_id = uuid.uuid4().hex, run_id
        self.variant, self.fixture = variant, fixture
        self.lock = threading.RLock()
        self.deleted = False
        self.bookings, self.audit_log, self.events = [], [], []
        self.address, self.pending = "10 Oak Street", None
        self.turn_count, self.last_base = 0, 0
        self.response_id = None

    def event(self, kind, at_ms, **data):
        event = {"event_id": "event-%04d" % (len(self.events) + 1),
                 "kind": kind, "at_ms": at_ms, "session_id": self.id,
                 "turn_id": "turn-%d" % self.turn_count,
                 "clock_domain": "fixture_clock", "timing_source": "simulated"}
        if self.response_id is not None:
            event["response_id"] = self.response_id
        event.update(data)
        self.events.append(event)
        return event

    def mutate(self, action, at_ms, **data):
        item = self.event("tool_commit", at_ms, action=action, **data)
        self.audit_log.append(dict(item))


class Target:
    def __init__(self, fixtures_dir, slow_ms):
        self.lock, self.sessions = threading.RLock(), {}
        self.slow_ms = slow_ms
        self.audio_lookup, self.responses = {}, {}
        fixtures_dir = Path(fixtures_dir).resolve()
        manifest = json.loads((fixtures_dir / "audio_manifest.json").read_text())
        for item in manifest["files"]:
            path = (fixtures_dir / item["path"]).resolve()
            if not path.is_relative_to(fixtures_dir):
                raise ValueError("Audio manifest path must stay inside fixtures directory")
            audio = path.read_bytes()
            validate_wav(audio)
            digest = hashlib.sha256(audio).hexdigest()
            if digest in self.audio_lookup and self.audio_lookup[digest] != item["text"]:
                raise ValueError("The same audio bytes cannot identify different utterances")
            self.audio_lookup[digest] = item["text"]
        for name in RESPONSE_FILES:
            audio = (fixtures_dir / "audio" / (name + ".wav")).read_bytes()
            validate_wav(audio)
            self.responses[name] = audio

    def session(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise APIError(404, "SESSION_NOT_FOUND", "Unknown or deleted session")
        return session

    def decode_input(self, body):
        if ("text" in body) == ("audio_base64" in body):
            raise APIError(400, "INVALID_INPUT", "Supply exactly one of text or audio_base64")
        if "text" in body:
            if not isinstance(body["text"], str) or not body["text"].strip() or "audio_format" in body:
                raise APIError(400, "INVALID_INPUT", "text must be a nonempty string without audio_format")
            return body["text"].strip(), "chat", {}
        if body.get("audio_format") != "wav" or not isinstance(body["audio_base64"], str):
            raise APIError(400, "INVALID_AUDIO", "Use audio_format wav and a base64 string")
        try:
            audio = base64.b64decode(body["audio_base64"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise APIError(400, "INVALID_AUDIO", "Invalid base64") from exc
        validate_wav(audio)
        digest = hashlib.sha256(audio).hexdigest()
        if digest not in self.audio_lookup:
            raise APIError(400, "UNKNOWN_AUDIO_FIXTURE", "Valid WAV is not in the supplied manifest")
        return self.audio_lookup[digest], "audio", {"audio_sha256": digest, "audio_byte_count": len(audio)}

    def turn(self, session, decoded):
        text, mode, evidence = decoded
        session.turn_count += 1
        base = session.last_base = (session.turn_count - 1) * 2000
        session.response_id = "response-%d" % session.turn_count
        start = len(session.events)
        session.event("input_received", base, mode=mode, text=text, **evidence)
        if mode == "audio":
            session.event("user_utterance_end", base)
            recognized = text.replace("14 Pine", "40 Pine") if session.variant == "faulty" and session.fixture == "address" else text
            session.event("stt_final", base + 120, text=recognized, source="manifest_script_not_stt")
        session.event("model_request", base + 220, response_id=session.response_id)
        normalized = text.lower().strip().rstrip(".!?")
        response_file = "agent_response"
        if normalized in CONFIRMATIONS and session.pending:
            pending = session.pending
            session.pending = None
            if pending == "address":
                session.address = "14 Pine Street"
                session.mutate("update_address", base + 450, address=session.address, confirmed=True)
                answer, response_file = "Your address is now 14 Pine Street.", "agent_saved"
            else:
                slot = WRONG_SLOT if session.variant == "faulty" and session.fixture not in ("retry", "state_unavailable") else SLOT
                count = 2 if session.variant == "faulty" and session.fixture == "retry" else 1
                if session.variant == "faulty" and session.fixture == "false_success":
                    count = 0
                for _ in range(count):
                    booking = {"id": "B%d" % (len(session.bookings) + 1), "customer_id": "C1", "starts_at": slot}
                    session.bookings.append(booking)
                    session.mutate("book_appointment", base + 420 + 10 * len(session.bookings), **booking, confirmed=True)
                    session.event("tool_result", base + 460, booking_id=booking["id"], call_id="call-%d" % len(session.bookings), idempotency_key="booking-C1-10")
                if session.fixture == "retry" and session.variant == "baseline":
                    session.event("tool_result", base + 470, booking_id=booking["id"], call_id="call-retry", idempotency_key="booking-C1-10")
                answer, response_file = "Your appointment is booked for 10:00 UTC on December 1, 2026.", "agent_booked"
        elif "don't save" in normalized or "do not save" in normalized:
            session.pending = None
            answer, response_file = "I will wait for your confirmation.", "agent_nochange"
        elif session.fixture == "address" and "14 pine" in normalized:
            session.pending = "address"
            if session.variant == "faulty":
                session.address = "40 Pine Street"
                session.pending = None
                session.mutate("update_address", base + 1250, address=session.address, confirmed=False)
                answer, response_file = "I will save 40 Pine Street now.", "agent_wait"
            else:
                answer = "Please confirm that I should save 14 Pine Street."
        elif "book" in normalized or "appointment" in normalized:
            session.pending = "booking"
            answer = "Please confirm the appointment for C1 at 10:00 UTC on December 1, 2026."
        else:
            answer = "Please provide a booking or address request, then confirm it."
        session.event("first_model_token", base + 480, response_id=session.response_id)
        session.event("generated_text", base + 500, response_id=session.response_id, text=answer)
        audio = self.responses[response_file]
        if mode == "audio":
            session.event("tts_request", base + 520, source="prerecorded_fixture_not_tts")
            session.event("first_audio_bytes", base + 560)
            session.event("first_audio_played", base + 640, source="simulated_client", audio_sha256=hashlib.sha256(audio).hexdigest())
        return {"session_id": session.id, "run_id": session.run_id,
                "turn_id": "turn-%d" % session.turn_count, "response_id": session.response_id,
                "input_mode": mode, "generated_text": answer,
                "audio_base64": base64.b64encode(audio).decode(), "audio_format": "wav",
                "audio_fixture": "audio/" + response_file + ".wav",
                "audio_semantics": "prerecorded_fixture_not_tts_may_differ_from_generated_text",
                "clock_domain": "fixture_clock", "timing_source": "simulated",
                "events": sorted(session.events[start:], key=lambda e: (e["at_ms"], e["event_id"]))}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 10 * 1024 * 1024:
                raise ValueError("Body must be 1 byte to 10 MiB")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Body must be an object")
            return body
        except (ValueError, UnicodeError) as exc:
            raise APIError(400, "INVALID_JSON", str(exc)) from exc

    def respond(self, status, body):
        data = json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def handle_api(self):
        target = self.server.target
        parts = urlsplit(self.path).path.strip("/").split("/")
        if self.command == "GET" and parts == ["health"]:
            with target.lock:
                active_sessions = len(target.sessions)
            return 200, {"status": "ok", "service": "scripted-evaluation-target", "real_stt_tts": False, "active_sessions": active_sessions}
        if self.command == "POST" and parts == ["sessions"]:
            body = self.json_body()
            if body.get("variant") not in ("baseline", "faulty") or not isinstance(body.get("fixture"), str) or body["fixture"] not in FIXTURES or not isinstance(body.get("run_id"), str) or not body["run_id"].strip():
                raise APIError(400, "INVALID_SESSION", "Provide run_id, variant baseline|faulty, and a supported fixture")
            session = Session(body["run_id"], body["variant"], body["fixture"])
            with target.lock:
                target.sessions[session.id] = session
            return 201, {"session_id": session.id, "run_id": session.run_id, "variant": session.variant, "fixture": session.fixture}
        if len(parts) not in (2, 3) or parts[0] != "sessions":
            raise APIError(404, "NOT_FOUND", "Unknown endpoint")
        session = target.session(parts[1])
        action = parts[2] if len(parts) == 3 else None
        decoded = None
        if self.command == "POST" and action == "turn":
            decoded = target.decode_input(self.json_body())
            if session.fixture == "slow":
                # Sleep outside the lock: DELETE can prevent a delayed write.
                time.sleep(target.slow_ms / 1000)
        with session.lock:
            if session.deleted:
                raise APIError(404, "SESSION_NOT_FOUND", "Deleted session")
            if self.command == "DELETE" and action is None:
                session.deleted = True
                with target.lock:
                    target.sessions.pop(session.id, None)
                return 200, {"deleted": True, "session_id": session.id}
            if self.command == "GET" and action == "state":
                if session.fixture == "state_unavailable":
                    raise APIError(503, "STATE_UNAVAILABLE", "Deterministic fixture: authoritative read unavailable")
                return 200, {"session_id": session.id, "run_id": session.run_id, "authoritative": True, "bookings": list(session.bookings), "address": session.address, "audit_log": list(session.audit_log)}
            if self.command == "GET" and action == "trace":
                return 200, {"session_id": session.id, "run_id": session.run_id, "clock_domain": "fixture_clock", "timing_source": "simulated", "events": sorted(session.events, key=lambda e: (e["at_ms"], e["event_id"]))}
            if self.command == "POST" and action == "turn":
                return 200, target.turn(session, decoded)
            if self.command == "POST" and action == "interrupt":
                body = self.json_body()
                if body.get("action") != "interrupt" or not session.response_id:
                    raise APIError(400, "INVALID_INTERRUPT", "Use action interrupt after a turn")
                events = [session.event("user_speech_start", session.last_base + 900),
                          session.event("cancellation_requested", session.last_base + 990, response_id=session.response_id),
                          session.event("playback_stopped", session.last_base + 1220, response_id=session.response_id, source="simulated_client")]
                return 200, {"session_id": session.id, "events": events, "clock_domain": "fixture_clock", "timing_source": "simulated", "warning": "Telemetry fixture only; does not undo tool writes"}
        raise APIError(404, "NOT_FOUND", "Unknown endpoint or method")

    def dispatch(self):
        try:
            status, body = self.handle_api()
        except APIError as exc:
            status, body = exc.status, {"error": {"code": exc.code, "message": exc.message}}
        self.respond(status, body)

    do_GET = do_POST = do_DELETE = dispatch


def make_server(host="127.0.0.1", port=8765, fixtures_dir=None, slow_ms=2000):
    if slow_ms < 0:
        raise ValueError("slow_ms must be nonnegative")
    fixtures_dir = fixtures_dir or Path(__file__).resolve().parent / "fixtures"
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.target = Target(fixtures_dir, slow_ms)
    except Exception:
        server.server_close()
        raise
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fixtures-dir", type=Path)
    parser.add_argument("--slow-ms", type=int, default=2000)
    args = parser.parse_args()
    with make_server(args.host, args.port, args.fixtures_dir, args.slow_ms) as server:
        print("Scripted target listening on http://%s:%d" % server.server_address, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
