# Local target service protocol

This service is the system your evaluator tests. It does not implement your
scenario runner, grader, comparison logic, result storage, or report. It uses
only the Python standard library and requires Python 3.10 or later.

## Run

From this starter directory:

```sh
python3 target_server.py
python3 -m unittest discover -s tests -v
```

The default address is `http://127.0.0.1:8765`. Flags are `--host`, `--port`,
`--fixtures-dir`, and `--slow-ms`. The slow fixture defaults to a real 2,000 ms
delay per turn. Keep that default when running the supplied scenarios, whose
timeout case uses a 400 ms client deadline. Tests use temporary generated audio
and an ephemeral port; they do not require the service to be running separately.

All request and response bodies are JSON. Errors have this form:

```json
{"error":{"code":"STATE_UNAVAILABLE","message":"..."}}
```

## Endpoints

- `GET /health` returns HTTP 200 with `status: "ok"` and `active_sessions`, the
  current number of sessions retained by this service. Compare the count before
  and after an isolated evaluation run to verify session cleanup.
- `POST /sessions` accepts `{"run_id":"r1","variant":"baseline","fixture":"booking"}`.
  It returns HTTP 201 with `session_id`, `run_id`, `variant`, and `fixture`.
  Variant is `baseline` or `faulty`. Fixtures are `booking`, `false_success`,
  `retry`, `address`, `state_unavailable`, and `slow`.
- `POST /sessions/{session_id}/turn` accepts either `{"text":"Yes, confirm"}`
  or `{"audio_base64":"<actual WAV bytes encoded as base64>","audio_format":"wav"}`.
  Do not send both modalities. A path or transcript is not an audio payload.
- `POST /sessions/{session_id}/interrupt` accepts `{"action":"interrupt"}`
  after a turn. It returns simulated interruption events for the last response.
- `GET /sessions/{session_id}/state` returns authoritative `bookings`, `address`,
  and `audit_log`, plus `session_id`, `run_id`, and `authoritative: true`.
- `GET /sessions/{session_id}/trace` returns `events` sorted by fixture time,
  plus `session_id`, `run_id`, `clock_domain`, and `timing_source`.
- `DELETE /sessions/{session_id}` removes the session and its stored artifacts.
  It returns `{"deleted":true,"session_id":"..."}`. Subsequent requests return
  HTTP 404. A delayed slow request cannot mutate or recreate a deleted session.

Repeated `run_id` values are allowed; each created session remains isolated.
State begins with `bookings: []` and `address: "10 Oak Street"`. Read it before
turns when useful. A booking is `{id, customer_id, starts_at}`. Audit entries
are committed tool effects, including `action`, `confirmed`, affected fields,
and event identifiers. Booking retries can produce multiple tool-result events
without creating multiple persisted bookings.

The `state_unavailable` fixture returns HTTP 503 on every authoritative-state
read, for either variant. Its booking behavior is correct and identical in both
variants; the unavailable state read is its only injected fault. Its other
endpoints still work. A client timeout
alone does not cancel a server request: collect appropriate evidence and clean
up sessions. DELETE can cancel a slow request that is still waiting; it cannot
reverse a write that already completed.

## Turn results and events

A turn response contains:

```text
session_id, run_id, turn_id, response_id, input_mode,
generated_text, audio_base64, audio_format, audio_fixture,
audio_semantics, clock_domain, timing_source, events
```

The response WAV is returned for chat and audio calls, but audio timing events
are emitted only for audio input. Persist the response bytes for audio runs.

Every event has `event_id`, `kind`, `at_ms`, `session_id`, `turn_id`,
`clock_domain: "fixture_clock"`, and `timing_source: "simulated"`.
Once a response is assigned, every event also has `response_id`, including input,
audio timing, and interruption events. A turn assigns its response ID before
recording input, so its input and output events can be correlated directly.
Events carry additional fields appropriate to their kind:

- `input_received`: `mode`, the scripted input `text`, and for audio,
  `audio_sha256` and `audio_byte_count`.
- `user_utterance_end`, `model_request`, `first_model_token`, `tts_request`,
  `first_audio_bytes`, and `first_audio_played`: timing boundaries. The playback
  event also identifies its audio bytes by SHA256.
- `stt_final` and `generated_text`: scripted text. Response events identify
  `response_id` where applicable.
- `tool_commit`: a persisted effect recorded in the audit log.
- `tool_result`: `booking_id`, `call_id`, and `idempotency_key`.
- `user_speech_start`, `cancellation_requested`, and `playback_stopped`:
  interruption boundaries returned by `/interrupt` and retained in the trace.

Each turn starts at a fixture-clock offset 2,000 ms after the preceding turn.
Match events by session and turn before subtracting times. For the supplied
audio fixtures, user utterance end to first audio playback is 640 ms, and
interruption onset to playback stop is 320 ms. Retain the provenance with these
values rather than labeling them real network or browser measurements.

## Simulation boundaries

Input audio is decoded from base64, validated as a nonempty PCM WAV of at most
60 seconds, and matched by SHA256 against `fixtures/audio_manifest.json`.
Unknown but valid audio returns HTTP 400 `UNKNOWN_AUDIO_FIXTURE`. This is an
explicit fixture lookup, not speech recognition. The manifest describes the
supported input recordings; the target does not read `scenarios.json` or its
expected outcomes.

Output audio consists of the supplied prerecorded WAVs, not live synthesized
speech. Generated text and the audible recording may differ. In particular,
the faulty address response generates a longer sentence but returns
`agent_wait.wav`, which says only "I will save". Treat generated text, audio
bytes, fixture timing, and committed tool state as separate evidence.

The HTTP API is buffered request/response. `/interrupt` returns a deterministic
telemetry fixture, not a real duplex audio cancellation. It does not roll back
an address write. All stage timestamps are simulated, even though audio bytes
are real and HTTP durations can be measured locally with a monotonic clock.
Do not use the simulated trace to claim measured STT, TTS, transport, jitter,
or end-user streaming performance. Explain how your evaluator would connect
to and instrument a genuine streaming audio target.
