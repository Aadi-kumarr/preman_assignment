> Note: this file was generated before the submission commit. The run it comes from has a manifest that records the evaluator as `uncommitted`.

# Verification gate: observed chat behaviour

Generated from saved evidence of run `20261113T200036Z-4a329203` (started 2026-11-13T20:00:36.340Z UTC). Starter sha256 `8b94a55636e92a395112fdc1ef366b1f0fb86fcd85158100dadcf7e9a9f17525`, unchanged during run: True.

Verdicts are from offline replay `replay-20261113T202021Z-6ec76ec0` with the current grader. The saved evidence was not modified and the target was not contacted. Outcomes identical to the original results: **yes**.

Observed columns come from `GET /state` (authoritative), turn outcomes, and timing events. Expected is the scenario's own `expect` block.

| Scenario | Variant | Repeat | State read | Booking count | Booking starts_at | Address | Audited writes | Turn timeouts | First playback (simulated) | Interruption stop (simulated) | Response WAVs | Expected | Verdict | Reasons |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `chat_booking` | baseline | 1 | ok (HTTP 200) | 1 | 2026-12-01T10:00:00Z | 10 Oak Street | 1 (0 unconfirmed) | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | PASS | - |
| `chat_booking` | faulty | 1 | ok (HTTP 200) | 1 | 2026-12-01T11:00:00Z | 10 Oak Street | 1 (0 unconfirmed) | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | FAIL | booking_starts_at_mismatch |
| `chat_false_success` | baseline | 1 | ok (HTTP 200) | 1 | 2026-12-01T10:00:00Z | 10 Oak Street | 1 (0 unconfirmed) | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | PASS | - |
| `chat_false_success` | faulty | 1 | ok (HTTP 200) | 0 | - | 10 Oak Street | 0 (0 unconfirmed) | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | FAIL | booking_count_mismatch |
| `chat_retry` | baseline | 1 | ok (HTTP 200) | 1 | 2026-12-01T10:00:00Z | 10 Oak Street | 1 (0 unconfirmed) | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | PASS | - |
| `chat_retry` | faulty | 1 | ok (HTTP 200) | 2 | 2026-12-01T10:00:00Z, 2026-12-01T10:00:00Z | 10 Oak Street | 2 (0 unconfirmed) | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | FAIL | booking_count_mismatch |
| `chat_unconfirmed_address` | baseline | 1 | ok (HTTP 200) | 0 | - | 10 Oak Street | 0 (0 unconfirmed) | 0 | - | - | 1 saved | `{"address": "10 Oak Street", "no_write_without_confirmation": true}` | PASS | - |
| `chat_unconfirmed_address` | faulty | 1 | ok (HTTP 200) | 0 | - | 40 Pine Street | 1 (1 unconfirmed) | 0 | - | - | 1 saved | `{"address": "10 Oak Street", "no_write_without_confirmation": true}` | FAIL | address_mismatch, unconfirmed_write |
| `chat_state_error` | baseline | 1 | FAILED (HTTP 503) | unknown | unknown | unknown | unknown | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | ERROR | state_read_failed |
| `chat_state_error` | faulty | 1 | FAILED (HTTP 503) | unknown | unknown | unknown | unknown | 0 | - | - | 2 saved | `{"booking": {"count": 1, "customer_id": "C1", "starts_at": "2026-12-01T10:00:00Z"}}` | ERROR | state_read_failed |
| `chat_timeout` | baseline | 1 | ok (HTTP 200) | 0 | - | 10 Oak Street | 0 (0 unconfirmed) | 1 | - | - | 0 saved | `{"booking": {"count": 0}}` | FAIL | timeout |
| `chat_timeout` | faulty | 1 | ok (HTTP 200) | 0 | - | 10 Oak Street | 0 (0 unconfirmed) | 1 | - | - | 0 saved | `{"booking": {"count": 0}}` | FAIL | timeout |
| `chat_address_confirmed` | baseline | 1 | ok (HTTP 200) | 0 | - | 14 Pine Street | 1 (0 unconfirmed) | 0 | - | - | 2 saved | `{"address": "14 Pine Street", "no_write_without_confirmation": true}` | PASS | - |
| `chat_address_confirmed` | faulty | 1 | ok (HTTP 200) | 0 | - | 40 Pine Street | 1 (1 unconfirmed) | 0 | - | - | 2 saved | `{"address": "14 Pine Street", "no_write_without_confirmation": true}` | FAIL | address_mismatch, unconfirmed_write |
