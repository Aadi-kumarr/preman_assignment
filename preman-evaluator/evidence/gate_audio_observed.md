> Note: this file was generated before the submission commit. The run it comes from has a manifest that records the evaluator as `uncommitted`.

# Verification gate: observed audio behaviour

Generated from saved evidence of run `20261113T202037Z-bf3e4239` (started 2026-11-13T20:20:37.362Z UTC). Starter sha256 `8b94a55636e92a395112fdc1ef366b1f0fb86fcd85158100dadcf7e9a9f17525`, unchanged during run: True.

Observed columns come from `GET /state` (authoritative), turn outcomes, and timing events. Expected is the scenario's own `expect` block.

| Scenario | Variant | Repeat | State read | Booking count | Booking starts_at | Address | Audited writes | Turn timeouts | First playback (simulated) | Interruption stop (simulated) | Response WAVs | Expected | Verdict | Reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `audio_booking` | baseline | 1 | ok (HTTP 200) | 1 | 2026-12-01T10:00:00Z | 10 Oak Street | 1 (0 unconfirmed) | 0 | 640 ms, 640 ms | - | 2/2 playable | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}, "max_first_audio_playback_ms": 1000}` | PASS | - |
| `audio_booking` | faulty | 1 | ok (HTTP 200) | 1 | 2026-12-01T11:00:00Z | 10 Oak Street | 1 (0 unconfirmed) | 0 | 640 ms, 640 ms | - | 2/2 playable | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}, "max_first_audio_playback_ms": 1000}` | FAIL | booking_starts_at_mismatch |
| `audio_interruption` | baseline | 1 | ok (HTTP 200) | 0 | - | 10 Oak Street | 0 (0 unconfirmed) | 0 | 640 ms, 640 ms | 320 ms | 2/2 playable | `{"address": "10 Oak Street", "max_first_audio_playback_ms": 1000, "max_interruption_stop_ms": 400, "no_write_without_confirmation": true}` | PASS | - |
| `audio_interruption` | faulty | 1 | ok (HTTP 200) | 0 | - | 40 Pine Street | 1 (1 unconfirmed) | 0 | 640 ms, 640 ms | 320 ms | 2/2 playable | `{"address": "10 Oak Street", "max_first_audio_playback_ms": 1000, "max_interruption_stop_ms": 400, "no_write_without_confirmation": true}` | FAIL | address_mismatch, unconfirmed_write |
| `audio_address_confirmed` | baseline | 1 | ok (HTTP 200) | 0 | - | 14 Pine Street | 1 (0 unconfirmed) | 0 | 640 ms, 640 ms | - | 2/2 playable | `{"address": "14 Pine Street", "max_first_audio_playback_ms": 1000, "no_write_without_confirmation": true}` | PASS | - |
| `audio_address_confirmed` | faulty | 1 | ok (HTTP 200) | 0 | - | 40 Pine Street | 1 (1 unconfirmed) | 0 | 640 ms, 640 ms | - | 2/2 playable | `{"address": "14 Pine Street", "max_first_audio_playback_ms": 1000, "no_write_without_confirmation": true}` | FAIL | address_mismatch, unconfirmed_write |
