"""Adapter boundary between the runner and a target's turn interface.

An adapter turns one scenario step into one target request and returns an
evidence record. The runner owns sessions, ordering, state reads, and cleanup,
so connecting a different target (for example a real streaming voice agent)
means writing a new adapter that returns records of the same shape.
"""
import base64
import binascii
import io
import json
import wave
from pathlib import Path

from .client import exchange
from .hashing import sha256_bytes, sha256_file


class TurnAdapter:
    modality = None

    def send_turn(self, client, session_id, turn, index, deadline_ms, attempt_dir, harness_timeout_ms=5000):
        """Send one step; return an evidence record with at least ``outcome``."""
        raise NotImplementedError


def describe_wav(data):
    """Check that bytes are a playable PCM WAV and measure it with the ``wave`` module."""
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if frames <= 0 or rate <= 0:
                raise ValueError("WAV has no audio frames")
            if len(audio.readframes(frames)) != frames * channels * width:
                raise ValueError("WAV frames are truncated")
    except (wave.Error, EOFError, ValueError) as exc:
        return {"playable": False, "error": str(exc) or type(exc).__name__}
    return {"playable": True, "duration_ms": round(frames * 1000 / rate, 1), "sample_rate_hz": rate,
            "channels": channels, "sample_width_bits": width * 8, "frames": frames}


def extract_response_audio(record, index, attempt_dir):
    """Save the returned WAV beside the evidence and replace the base64 in the record.

    The raw response is otherwise kept as received; the JSON holds a pointer
    (file name and SHA-256) instead of the inline base64.
    """
    body = record.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("audio_base64"), str):
        return
    encoded = body["audio_base64"]
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        record["audio_error"] = "response audio is not valid base64: %s" % exc
        body["audio_base64"] = {"extracted_to": None, "base64_chars": len(encoded)}
        return
    name = "turn-%02d.response.%s" % (index, "wav" if body.get("audio_format") == "wav" else "bin")
    (attempt_dir / name).write_bytes(audio)
    artifact = {"path": name, "sha256": sha256_bytes(audio), "bytes": len(audio)}
    artifact.update(describe_wav(audio))
    body["audio_base64"] = {"extracted_to": name, "sha256": artifact["sha256"], "base64_chars": len(encoded)}
    record["audio_artifact"] = artifact


def _finish_turn(record, index, deadline_ms, attempt_dir):
    # A response that arrives after the deadline is still a deadline breach.
    record["deadline_exceeded"] = record["outcome"] == "timeout" or record["elapsed_ms"] > deadline_ms
    extract_response_audio(record, index, attempt_dir)
    return record


class ChatAdapter(TurnAdapter):
    """Sends text turns to ``POST /sessions/{id}/turn``."""
    modality = "chat"

    def send_turn(self, client, session_id, turn, index, deadline_ms, attempt_dir, harness_timeout_ms=5000):
        if turn.get("type") != "text":
            raise ValueError("chat adapter can only send text turns, got %r" % turn.get("type"))
        record = {"index": index, "type": "text", "request": {"text": turn["text"]}, "deadline_ms": deadline_ms}
        record.update(exchange(lambda: client.send_text(session_id, turn["text"], deadline_ms), 200))
        return _finish_turn(record, index, deadline_ms, attempt_dir)


def load_utterances(starter_dir, manifest_path):
    """Map each manifest WAV's SHA-256 to its scripted words.

    This is evaluator-side knowledge of what the user says in a recording (used
    by the confirmation policy). It is never sent to the target.
    """
    try:
        manifest_file = Path(starter_dir) / manifest_path
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        return {sha256_file(manifest_file.parent / item["path"]): item["text"] for item in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


class AudioAdapter(TurnAdapter):
    """Sends WAV bytes as base64 to ``/turn`` and interrupts to ``/interrupt``."""
    modality = "audio"

    def __init__(self, audio_root, utterances=None):
        self.audio_root = Path(audio_root)
        self.utterances = utterances or {}

    def send_turn(self, client, session_id, turn, index, deadline_ms, attempt_dir, harness_timeout_ms=5000):
        kind = turn.get("type")
        if kind == "interrupt":
            # Not an agent turn: it uses the harness timeout, not the turn deadline.
            record = {"index": index, "type": "interrupt", "request": {"action": "interrupt"},
                      "timeout_ms": harness_timeout_ms}
            record.update(exchange(lambda: client.interrupt(session_id, harness_timeout_ms), 200))
            return record
        if kind != "audio":
            raise ValueError("audio adapter can only send audio and interrupt steps, got %r" % kind)
        wav = (self.audio_root / turn["path"]).read_bytes()
        digest = sha256_bytes(wav)
        record = {"index": index, "type": "audio", "deadline_ms": deadline_ms, "request": {
            "audio_format": "wav", "sent_as": "audio_base64", "audio_path": turn["path"],
            "audio_sha256": digest, "audio_bytes": len(wav),
            "utterance_text": self.utterances.get(digest),
            "utterance_source": "audio manifest; evaluator-side only, not sent to the target"}}
        record.update(exchange(lambda: client.send_audio(session_id, wav, deadline_ms), 200))
        return _finish_turn(record, index, deadline_ms, attempt_dir)


def build_adapters(audio_root, utterances=None):
    return {"chat": ChatAdapter(), "audio": AudioAdapter(audio_root, utterances)}


SUPPORTED_MODALITIES = ("chat", "audio")
