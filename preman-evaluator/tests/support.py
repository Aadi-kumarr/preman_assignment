"""Shared test helpers: a scriptable local HTTP fake, evidence builders, starter lookup."""
import base64
import io
import json
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EVALUATOR_ROOT = Path(__file__).resolve().parents[1]
STARTER_RELATIVE = os.environ.get("PREMAN_STARTER_DIR", "../preman-agent-evaluation")
STARTER_DIR = EVALUATOR_ROOT / STARTER_RELATIVE
STARTER_AVAILABLE = (STARTER_DIR / "target_server.py").is_file()

BOOK = "Book appointment for C1 at 2026-12-01T10:00:00Z"
CONFIRM = "Yes, confirm"
SLOT = "2026-12-01T10:00:00Z"
POLICY = {"confirmation_phrases": ["yes", "confirm", "yes confirm", "yes, confirm"]}


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * 160)
    return buffer.getvalue()


class FakeTarget:
    """A local HTTP server whose behaviour each test scripts.

    ``routes`` maps ``(METHOD, name)`` to ``(status, body)`` or a callable
    ``(fake, body_json) -> (status, body)``; names are health, sessions, turn,
    state, trace, session (DELETE). A dict body is sent as JSON, a str as HTML.
    """

    def __init__(self, routes=None):
        self.routes = {
            ("GET", "health"): lambda fake, body: (200, {"status": "ok", "active_sessions": len(fake.sessions)}),
            ("POST", "sessions"): self._create,
            ("POST", "turn"): self._turn,
            ("GET", "state"): (200, {"authoritative": True, "bookings": [], "address": "10 Oak Street", "audit_log": []}),
            ("GET", "trace"): (200, {"events": []}),
            ("POST", "interrupt"): self._interrupt,
            ("DELETE", "session"): self._delete,
        }
        self.routes.update(routes or {})
        self.calls, self.sessions, self.turns = [], set(), {}
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_any(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                parts = self.path.strip("/").split("/")
                name = parts[0] if len(parts) == 1 else (parts[2] if len(parts) == 3 else "session")
                with fake.lock:
                    fake.calls.append((self.command, name, parts[1] if len(parts) > 1 else None, body))
                    fake.current_session = parts[1] if len(parts) > 1 else None
                route = fake.routes.get((self.command, name), (404, {"error": {"code": "NOT_FOUND", "message": "x"}}))
                status, payload = route(fake, body) if callable(route) else route
                data = json.dumps(payload).encode() if isinstance(payload, (dict, list)) else str(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json" if isinstance(payload, (dict, list)) else "text/html")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client gave up (timeout tests)

            do_GET = do_POST = do_DELETE = do_PUT = handle_any

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = "http://127.0.0.1:%d" % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def _create(fake, body):
        with fake.lock:
            session_id = "s%d" % (len([c for c in fake.calls if c[:2] == ("POST", "sessions")]))
            fake.sessions.add(session_id)
        return 201, {"session_id": session_id, "run_id": body["run_id"], "variant": body["variant"], "fixture": body["fixture"]}

    @staticmethod
    def _turn(fake, body):
        session = fake.current_session
        with fake.lock:
            number = fake.turns[session] = fake.turns.get(session, 0) + 1
        events = []
        if "audio_base64" in body:  # audio input gets timing events, like the real target
            base = (number - 1) * 2000
            events = [ev("user_utterance_end", base, number, session=session),
                      ev("first_audio_played", base + 640, number, session=session)]
        return 200, {"session_id": session, "turn_id": "turn-%d" % number, "response_id": "response-%d" % number,
                     "generated_text": "ok", "audio_base64": base64.b64encode(wav_bytes()).decode(),
                     "audio_format": "wav", "events": events}

    @staticmethod
    def _interrupt(fake, body):
        session = fake.current_session
        number = fake.turns.get(session, 0)
        base = (number - 1) * 2000
        with fake.lock:
            fake.interrupts = getattr(fake, "interrupts", 0) + 1
            serial = fake.interrupts
        return 200, {"session_id": session, "events": [
            ev("user_speech_start", base + 900, number, session=session, event_id="i%d-start" % serial),
            ev("playback_stopped", base + 1220, number, session=session, event_id="i%d-stop" % serial)]}

    @staticmethod
    def _delete(fake, body):
        with fake.lock:
            fake.sessions.discard(fake.current_session)
        return 200, {"deleted": True}

    def count(self, method, name):
        return sum(1 for call in self.calls if call[:2] == (method, name))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def scenario_def(expect, turns=(BOOK, CONFIRM), timeout_ms=3000, scenario_id="case", fixture="any"):
    return {"id": scenario_id, "fixture": fixture, "modality": "chat", "turn_timeout_ms": timeout_ms,
            "turns": [{"type": "text", "text": text} for text in turns], "expect": expect}


def booking(number=1, starts_at=SLOT, customer_id="C1"):
    return {"id": "B%d" % number, "customer_id": customer_id, "starts_at": starts_at}


def commit(action, turn, confirmed=True, event=1, **fields):
    return dict({"event_id": "event-%04d" % event, "kind": "tool_commit", "turn_id": "turn-%d" % turn,
                 "action": action, "confirmed": confirmed}, **fields)


def make_evidence(texts=(BOOK, CONFIRM), bookings=(), address="10 Oak Street", audit_log=(), events=(),
                  state=None, turn_overrides=None, **top):
    """Evidence in the shape the runner saves, for grading without any HTTP."""
    turns = []
    for index, text in enumerate(texts, 1):
        turn = {"index": index, "type": "text", "request": {"text": text}, "deadline_ms": 3000, "outcome": "ok",
                "status": 200, "elapsed_ms": 5.0, "deadline_exceeded": False,
                "body": {"turn_id": "turn-%d" % index, "generated_text": "ok", "events": []}}
        turn.update((turn_overrides or {}).get(index, {}))
        turns.append(turn)
    evidence = {
        "session": {"outcome": "ok", "status": 201, "body": {"session_id": "s1"}},
        "turns": turns,
        "state": state if state is not None else {"outcome": "ok", "status": 200, "body": {
            "authoritative": True, "bookings": list(bookings), "address": address, "audit_log": list(audit_log)}},
        "trace": {"outcome": "ok", "status": 200, "body": {"events": list(events)}},
        "cleanup": {"outcome": "ok", "status": 200, "body": {"deleted": True}},
        "harness_errors": [],
    }
    evidence.update(top)
    return evidence


def ev(kind, at_ms, turn=1, session="s1", event_id=None, response="same", **extra):
    """One timing event in the target's shape."""
    event = {"event_id": event_id or "%s-%d" % (kind, turn), "kind": kind, "at_ms": at_ms, "session_id": session,
             "turn_id": "turn-%d" % turn, "response_id": "response-%d" % turn if response == "same" else response,
             "clock_domain": "fixture_clock", "timing_source": "simulated"}
    event.update(extra)
    return event


def playback(turn=1, latency=640):
    base = (turn - 1) * 2000
    return [ev("user_utterance_end", base, turn), ev("first_audio_played", base + latency, turn)]


def stop_events(turn=1, latency=320, serial=1):
    base = (turn - 1) * 2000 + 900
    return [ev("user_speech_start", base, turn, event_id="i%d-start" % serial),
            ev("playback_stopped", base + latency, turn, event_id="i%d-stop" % serial)]


def audio_turn(index, events, number=None, utterance=None, **overrides):
    """An answered audio turn as the runner saves it. ``number`` is the target's turn number."""
    number = number or index
    turn = {"index": index, "type": "audio", "deadline_ms": 3000, "outcome": "ok", "status": 200, "elapsed_ms": 5.0,
            "deadline_exceeded": False,
            "request": {"audio_format": "wav", "sent_as": "audio_base64", "audio_path": "in.wav", "utterance_text": utterance},
            "body": {"session_id": "s1", "turn_id": "turn-%d" % number, "response_id": "response-%d" % number, "events": events},
            "audio_artifact": {"path": "turn-%02d.response.wav" % index, "sha256": "0" * 64, "bytes": 364,
                               "playable": True, "duration_ms": 10.0}}
    turn.update(overrides)
    return turn


def interrupt_step(index, events, **overrides):
    step = {"index": index, "type": "interrupt", "request": {"action": "interrupt"}, "timeout_ms": 5000,
            "outcome": "ok", "status": 200, "elapsed_ms": 2.0, "body": {"session_id": "s1", "events": events}}
    step.update(overrides)
    return step


def audio_evidence(turns, trace=None, **state):
    """Evidence for an audio conversation. The trace repeats every event unless given."""
    evidence = make_evidence(texts=(), **state)
    evidence["turns"] = turns
    if trace is None:
        trace = [e for t in turns for e in ((t.get("body") or {}).get("events") or [])]
    evidence["trace"] = {"outcome": "ok", "status": 200, "body": {"events": trace}}
    return evidence


STATE_503 = {"outcome": "http_error", "status": 503,
             "body": {"error": {"code": "STATE_UNAVAILABLE", "message": "unavailable"}}}
