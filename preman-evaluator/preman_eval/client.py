"""Small urllib client for the target's documented HTTP endpoints (README_PROTOCOL.md)."""
import base64
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

MAX_ERROR_TEXT = 4000


class TargetError(Exception):
    """A request produced no HTTP response."""

    def __init__(self, message, elapsed_ms):
        super().__init__(message)
        self.elapsed_ms = elapsed_ms


class TargetTimeout(TargetError):
    pass


class TargetTransportError(TargetError):
    pass


@dataclass
class HttpResult:
    status: int
    json: object      # parsed body, or None when the body is not JSON (e.g. an HTML 501)
    text: object      # raw body text (truncated) when it is not JSON, else None
    elapsed_ms: float  # measured by the runner with a monotonic clock


class TargetClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        # No proxies: the target is a local service.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, body=None, timeout_ms=5000):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"})
        start = time.monotonic()

        def elapsed():
            return round((time.monotonic() - start) * 1000, 1)

        try:
            try:
                response = self._opener.open(request, timeout=timeout_ms / 1000)
            except urllib.error.HTTPError as exc:  # non-2xx still carries a body
                response = exc
            with response:
                status = getattr(response, "status", None) or response.code
                raw = response.read()
        except TimeoutError as exc:  # socket.timeout is TimeoutError on Python 3.10+
            raise TargetTimeout("no response within %d ms" % timeout_ms, elapsed()) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TargetTimeout("no response within %d ms" % timeout_ms, elapsed()) from exc
            raise TargetTransportError("transport error: %s" % exc.reason, elapsed()) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise TargetTransportError("transport error: %s: %s" % (type(exc).__name__, exc), elapsed()) from exc
        took = elapsed()
        try:
            return HttpResult(status, json.loads(raw.decode("utf-8")), None, took)
        except ValueError:
            return HttpResult(status, None, raw.decode("utf-8", "replace")[:MAX_ERROR_TEXT], took)

    @staticmethod
    def _session(session_id, suffix=""):
        return "/sessions/" + urllib.parse.quote(str(session_id), safe="") + suffix

    def health(self, timeout_ms):
        return self.request("GET", "/health", timeout_ms=timeout_ms)

    def create_session(self, run_id, variant, fixture, timeout_ms):
        return self.request("POST", "/sessions", {"run_id": run_id, "variant": variant, "fixture": fixture}, timeout_ms)

    def send_text(self, session_id, text, timeout_ms):
        return self.request("POST", self._session(session_id, "/turn"), {"text": text}, timeout_ms)

    def send_audio(self, session_id, wav_bytes, timeout_ms):
        body = {"audio_base64": base64.b64encode(wav_bytes).decode("ascii"), "audio_format": "wav"}
        return self.request("POST", self._session(session_id, "/turn"), body, timeout_ms)

    def interrupt(self, session_id, timeout_ms):
        return self.request("POST", self._session(session_id, "/interrupt"), {"action": "interrupt"}, timeout_ms)

    def get_state(self, session_id, timeout_ms):
        return self.request("GET", self._session(session_id, "/state"), timeout_ms=timeout_ms)

    def get_trace(self, session_id, timeout_ms):
        return self.request("GET", self._session(session_id, "/trace"), timeout_ms=timeout_ms)

    def delete_session(self, session_id, timeout_ms):
        return self.request("DELETE", self._session(session_id), timeout_ms=timeout_ms)


def exchange(call, expect_status):
    """Run one client call and return a JSON-serialisable evidence record.

    ``outcome`` is ``ok`` (expected status with a JSON object body),
    ``http_error`` (any other response), ``timeout``, or ``transport_error``.
    """
    try:
        result = call()
    except TargetTimeout as exc:
        return {"outcome": "timeout", "elapsed_ms": exc.elapsed_ms, "error": str(exc)}
    except TargetTransportError as exc:
        return {"outcome": "transport_error", "elapsed_ms": exc.elapsed_ms, "error": str(exc)}
    record = {"outcome": "ok" if result.status == expect_status and isinstance(result.json, dict) else "http_error",
              "status": result.status, "elapsed_ms": result.elapsed_ms, "body": result.json}
    if result.json is None:
        record["body_text"] = result.text
    return record
