# Evaluation report: run `20261116T192723Z-e178942f`

- Started (UTC): 2026-11-16T19:27:23.718Z; finished: 2026-11-16T19:27:24.902Z
- Evaluator: git commit `01efb3dd5592cbc6cd9975f637dd7e8ce16050fd`, source sha256 `bcbed66988f9a2ef`
- Starter folder sha256: `8b94a55636e92a395112fdc1ef366b1f0fb86fcd85158100dadcf7e9a9f17525` (16 files); unchanged during run: **True**
- Target: http://127.0.0.1:62558; variants: baseline, faulty
- Concurrency: 3; repeats: 2; harness timeout: 5000 ms
- Target active sessions before/after: 0 / 0
- Verdict precedence: FAIL > ERROR > INCONCLUSIVE > PASS

## Scope

- Distinct scenarios: **10**; variants: **2**; repeats per scenario and variant: **2**
- Attempts: **40** (= 10 x 2 x 2). Repeats are repeated trials of the same scenario, not new scenarios.

## Verdict counts by variant

Each cell is attempts with that verdict / all attempts for the variant.

| Variant | Attempts | PASS | FAIL | ERROR | INCONCLUSIVE |
|---|---|---|---|---|---|
| baseline | 20 | 16/20 (80.0%) | 2/20 (10.0%) | 2/20 (10.0%) | 0/20 (0.0%) |
| faulty | 20 | 0/20 (0.0%) | 18/20 (90.0%) | 2/20 (10.0%) | 0/20 (0.0%) |
| all | 40 | 16/40 (40.0%) | 20/40 (50.0%) | 4/40 (10.0%) | 0/40 (0.0%) |

## Results by scenario

| Scenario | Modality | Variant | Attempts | Verdicts | Reasons (attempts affected) | Mean runner ms (measured) |
|---|---|---|---|---|---|---|
| `chat_booking` | chat | baseline | 2 | PASS x2 | - | 55.0 |
| `chat_booking` | chat | faulty | 2 | FAIL x2 | booking_starts_at_mismatch (2/2) | 31.0 |
| `chat_false_success` | chat | baseline | 2 | PASS x2 | - | 23.5 |
| `chat_false_success` | chat | faulty | 2 | FAIL x2 | booking_count_mismatch (2/2) | 31.5 |
| `chat_retry` | chat | baseline | 2 | PASS x2 | - | 16.0 |
| `chat_retry` | chat | faulty | 2 | FAIL x2 | booking_count_mismatch (2/2) | 31.0 |
| `chat_unconfirmed_address` | chat | baseline | 2 | PASS x2 | - | 16.0 |
| `chat_unconfirmed_address` | chat | faulty | 2 | FAIL x2 | address_mismatch (2/2), unconfirmed_write (2/2) | 39.0 |
| `chat_state_error` | chat | baseline | 2 | ERROR x2 | state_read_failed (2/2) | 31.0 |
| `chat_state_error` | chat | faulty | 2 | ERROR x2 | state_read_failed (2/2) | 47.0 |
| `chat_timeout` | chat | baseline | 2 | FAIL x2 | timeout (2/2) | 430.0 |
| `chat_timeout` | chat | faulty | 2 | FAIL x2 | timeout (2/2) | 445.5 |
| `audio_booking` | audio | baseline | 2 | PASS x2 | - | 31.0 |
| `audio_booking` | audio | faulty | 2 | FAIL x2 | booking_starts_at_mismatch (2/2) | 62.0 |
| `audio_interruption` | audio | baseline | 2 | PASS x2 | - | 47.0 |
| `audio_interruption` | audio | faulty | 2 | FAIL x2 | address_mismatch (2/2), unconfirmed_write (2/2) | 31.0 |
| `chat_address_confirmed` | chat | baseline | 2 | PASS x2 | - | 86.5 |
| `chat_address_confirmed` | chat | faulty | 2 | FAIL x2 | address_mismatch (2/2), unconfirmed_write (2/2) | 31.0 |
| `audio_address_confirmed` | audio | baseline | 2 | PASS x2 | - | 31.5 |
| `audio_address_confirmed` | audio | faulty | 2 | FAIL x2 | address_mismatch (2/2), unconfirmed_write (2/2) | 39.0 |

## Audio metrics

Computed from saved events, paired by session, turn and response IDs. The clock is the target's own: for the supplied target it is a simulated fixture clock, not real latency. Available = metrics with a usable value / metrics required. Runner time is the separate measured column above.

| Scenario | Variant | Metric | Step | Values | Available | Status | Limit | Provenance |
|---|---|---|---|---|---|---|---|---|
| `audio_booking` | baseline | first_audio_playback_ms | 1 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_booking` | baseline | first_audio_playback_ms | 2 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_booking` | faulty | first_audio_playback_ms | 1 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_booking` | faulty | first_audio_playback_ms | 2 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_interruption` | baseline | first_audio_playback_ms | 1 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_interruption` | baseline | first_audio_playback_ms | 3 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_interruption` | baseline | interruption_stop_ms | 2 | 320 ms x2 | 2/2 | ok x2 | <= 400 ms | simulated (fixture_clock) |
| `audio_interruption` | faulty | first_audio_playback_ms | 1 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_interruption` | faulty | first_audio_playback_ms | 3 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_interruption` | faulty | interruption_stop_ms | 2 | 320 ms x2 | 2/2 | ok x2 | <= 400 ms | simulated (fixture_clock) |
| `audio_address_confirmed` | baseline | first_audio_playback_ms | 1 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_address_confirmed` | baseline | first_audio_playback_ms | 2 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_address_confirmed` | faulty | first_audio_playback_ms | 1 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |
| `audio_address_confirmed` | faulty | first_audio_playback_ms | 2 | 640 ms x2 | 2/2 | ok x2 | <= 1000 ms | simulated (fixture_clock) |

## Reasons

Attempts affected / attempts for that variant. One attempt can have several reasons.

| Variant | Reason | Reason verdict | Attempts affected |
|---|---|---|---|
| baseline | state_read_failed | ERROR | 2/20 (10.0%) |
| baseline | timeout | FAIL | 2/20 (10.0%) |
| faulty | address_mismatch | FAIL | 8/20 (40.0%) |
| faulty | unconfirmed_write | FAIL | 8/20 (40.0%) |
| faulty | booking_count_mismatch | FAIL | 4/20 (20.0%) |
| faulty | booking_starts_at_mismatch | FAIL | 4/20 (20.0%) |
| faulty | state_read_failed | ERROR | 2/20 (10.0%) |
| faulty | timeout | FAIL | 2/20 (10.0%) |

## Attempts that did not pass

### `0003-chat_booking-faulty-r1`: FAIL

Scenario `chat_booking`, variant `faulty`, repeat 1. Evidence: [attempts/0003-chat_booking-faulty-r1/evidence.json](attempts/0003-chat_booking-faulty-r1/evidence.json). Runner duration (measured): 47.0 ms.

- **FAIL** `booking_starts_at_mismatch`: Booking B1 starts_at '2026-12-01T11:00:00Z', expected '2026-12-01T10:00:00Z'. Evidence: `attempts/0003-chat_booking-faulty-r1/evidence.json#/state/body/bookings/0`
- Response audio: [turn-01.response.wav](attempts/0003-chat_booking-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0003-chat_booking-faulty-r1/turn-02.response.wav)

### `0004-chat_booking-faulty-r2`: FAIL

Scenario `chat_booking`, variant `faulty`, repeat 2. Evidence: [attempts/0004-chat_booking-faulty-r2/evidence.json](attempts/0004-chat_booking-faulty-r2/evidence.json). Runner duration (measured): 15.0 ms.

- **FAIL** `booking_starts_at_mismatch`: Booking B1 starts_at '2026-12-01T11:00:00Z', expected '2026-12-01T10:00:00Z'. Evidence: `attempts/0004-chat_booking-faulty-r2/evidence.json#/state/body/bookings/0`
- Response audio: [turn-01.response.wav](attempts/0004-chat_booking-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0004-chat_booking-faulty-r2/turn-02.response.wav)

### `0007-chat_false_success-faulty-r1`: FAIL

Scenario `chat_false_success`, variant `faulty`, repeat 1. Evidence: [attempts/0007-chat_false_success-faulty-r1/evidence.json](attempts/0007-chat_false_success-faulty-r1/evidence.json). Runner duration (measured): 47.0 ms.

- **FAIL** `booking_count_mismatch`: Expected 1 persisted booking(s), authoritative state has 0 (fewer than expected). Evidence: `attempts/0007-chat_false_success-faulty-r1/evidence.json#/state/body/bookings`
- Response audio: [turn-01.response.wav](attempts/0007-chat_false_success-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0007-chat_false_success-faulty-r1/turn-02.response.wav)

### `0008-chat_false_success-faulty-r2`: FAIL

Scenario `chat_false_success`, variant `faulty`, repeat 2. Evidence: [attempts/0008-chat_false_success-faulty-r2/evidence.json](attempts/0008-chat_false_success-faulty-r2/evidence.json). Runner duration (measured): 16.0 ms.

- **FAIL** `booking_count_mismatch`: Expected 1 persisted booking(s), authoritative state has 0 (fewer than expected). Evidence: `attempts/0008-chat_false_success-faulty-r2/evidence.json#/state/body/bookings`
- Response audio: [turn-01.response.wav](attempts/0008-chat_false_success-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0008-chat_false_success-faulty-r2/turn-02.response.wav)

### `0011-chat_retry-faulty-r1`: FAIL

Scenario `chat_retry`, variant `faulty`, repeat 1. Evidence: [attempts/0011-chat_retry-faulty-r1/evidence.json](attempts/0011-chat_retry-faulty-r1/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `booking_count_mismatch`: Expected 1 persisted booking(s), authoritative state has 2 (more than expected). Evidence: `attempts/0011-chat_retry-faulty-r1/evidence.json#/state/body/bookings`
- Response audio: [turn-01.response.wav](attempts/0011-chat_retry-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0011-chat_retry-faulty-r1/turn-02.response.wav)

### `0012-chat_retry-faulty-r2`: FAIL

Scenario `chat_retry`, variant `faulty`, repeat 2. Evidence: [attempts/0012-chat_retry-faulty-r2/evidence.json](attempts/0012-chat_retry-faulty-r2/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `booking_count_mismatch`: Expected 1 persisted booking(s), authoritative state has 2 (more than expected). Evidence: `attempts/0012-chat_retry-faulty-r2/evidence.json#/state/body/bookings`
- Response audio: [turn-01.response.wav](attempts/0012-chat_retry-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0012-chat_retry-faulty-r2/turn-02.response.wav)

### `0015-chat_unconfirmed_address-faulty-r1`: FAIL

Scenario `chat_unconfirmed_address`, variant `faulty`, repeat 1. Evidence: [attempts/0015-chat_unconfirmed_address-faulty-r1/evidence.json](attempts/0015-chat_unconfirmed_address-faulty-r1/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '10 Oak Street'. Evidence: `attempts/0015-chat_unconfirmed_address-faulty-r1/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0003, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0015-chat_unconfirmed_address-faulty-r1/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0015-chat_unconfirmed_address-faulty-r1/turn-01.response.wav)

### `0016-chat_unconfirmed_address-faulty-r2`: FAIL

Scenario `chat_unconfirmed_address`, variant `faulty`, repeat 2. Evidence: [attempts/0016-chat_unconfirmed_address-faulty-r2/evidence.json](attempts/0016-chat_unconfirmed_address-faulty-r2/evidence.json). Runner duration (measured): 47.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '10 Oak Street'. Evidence: `attempts/0016-chat_unconfirmed_address-faulty-r2/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0003, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0016-chat_unconfirmed_address-faulty-r2/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0016-chat_unconfirmed_address-faulty-r2/turn-01.response.wav)

### `0017-chat_state_error-baseline-r1`: ERROR

Scenario `chat_state_error`, variant `baseline`, repeat 1. Evidence: [attempts/0017-chat_state_error-baseline-r1/evidence.json](attempts/0017-chat_state_error-baseline-r1/evidence.json). Runner duration (measured): 31.0 ms.

- **ERROR** `state_read_failed`: Authoritative state read failed (HTTP 503, STATE_UNAVAILABLE); the trace is not authoritative and is not used instead. Evidence: `attempts/0017-chat_state_error-baseline-r1/evidence.json#/state`
- Response audio: [turn-01.response.wav](attempts/0017-chat_state_error-baseline-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0017-chat_state_error-baseline-r1/turn-02.response.wav)

### `0018-chat_state_error-baseline-r2`: ERROR

Scenario `chat_state_error`, variant `baseline`, repeat 2. Evidence: [attempts/0018-chat_state_error-baseline-r2/evidence.json](attempts/0018-chat_state_error-baseline-r2/evidence.json). Runner duration (measured): 31.0 ms.

- **ERROR** `state_read_failed`: Authoritative state read failed (HTTP 503, STATE_UNAVAILABLE); the trace is not authoritative and is not used instead. Evidence: `attempts/0018-chat_state_error-baseline-r2/evidence.json#/state`
- Response audio: [turn-01.response.wav](attempts/0018-chat_state_error-baseline-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0018-chat_state_error-baseline-r2/turn-02.response.wav)

### `0019-chat_state_error-faulty-r1`: ERROR

Scenario `chat_state_error`, variant `faulty`, repeat 1. Evidence: [attempts/0019-chat_state_error-faulty-r1/evidence.json](attempts/0019-chat_state_error-faulty-r1/evidence.json). Runner duration (measured): 47.0 ms.

- **ERROR** `state_read_failed`: Authoritative state read failed (HTTP 503, STATE_UNAVAILABLE); the trace is not authoritative and is not used instead. Evidence: `attempts/0019-chat_state_error-faulty-r1/evidence.json#/state`
- Response audio: [turn-01.response.wav](attempts/0019-chat_state_error-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0019-chat_state_error-faulty-r1/turn-02.response.wav)

### `0020-chat_state_error-faulty-r2`: ERROR

Scenario `chat_state_error`, variant `faulty`, repeat 2. Evidence: [attempts/0020-chat_state_error-faulty-r2/evidence.json](attempts/0020-chat_state_error-faulty-r2/evidence.json). Runner duration (measured): 47.0 ms.

- **ERROR** `state_read_failed`: Authoritative state read failed (HTTP 503, STATE_UNAVAILABLE); the trace is not authoritative and is not used instead. Evidence: `attempts/0020-chat_state_error-faulty-r2/evidence.json#/state`
- Response audio: [turn-01.response.wav](attempts/0020-chat_state_error-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0020-chat_state_error-faulty-r2/turn-02.response.wav)

### `0021-chat_timeout-baseline-r1`: FAIL

Scenario `chat_timeout`, variant `baseline`, repeat 1. Evidence: [attempts/0021-chat_timeout-baseline-r1/evidence.json](attempts/0021-chat_timeout-baseline-r1/evidence.json). Runner duration (measured): 438.0 ms.

- **FAIL** `timeout`: Turn 1 exceeded its 400 ms deadline (no response after 422.0 ms). Evidence: `attempts/0021-chat_timeout-baseline-r1/evidence.json#/turns/0`

### `0022-chat_timeout-baseline-r2`: FAIL

Scenario `chat_timeout`, variant `baseline`, repeat 2. Evidence: [attempts/0022-chat_timeout-baseline-r2/evidence.json](attempts/0022-chat_timeout-baseline-r2/evidence.json). Runner duration (measured): 422.0 ms.

- **FAIL** `timeout`: Turn 1 exceeded its 400 ms deadline (no response after 406.0 ms). Evidence: `attempts/0022-chat_timeout-baseline-r2/evidence.json#/turns/0`

### `0023-chat_timeout-faulty-r1`: FAIL

Scenario `chat_timeout`, variant `faulty`, repeat 1. Evidence: [attempts/0023-chat_timeout-faulty-r1/evidence.json](attempts/0023-chat_timeout-faulty-r1/evidence.json). Runner duration (measured): 422.0 ms.

- **FAIL** `timeout`: Turn 1 exceeded its 400 ms deadline (no response after 422.0 ms). Evidence: `attempts/0023-chat_timeout-faulty-r1/evidence.json#/turns/0`

### `0024-chat_timeout-faulty-r2`: FAIL

Scenario `chat_timeout`, variant `faulty`, repeat 2. Evidence: [attempts/0024-chat_timeout-faulty-r2/evidence.json](attempts/0024-chat_timeout-faulty-r2/evidence.json). Runner duration (measured): 469.0 ms.

- **FAIL** `timeout`: Turn 1 exceeded its 400 ms deadline (no response after 422.0 ms). Evidence: `attempts/0024-chat_timeout-faulty-r2/evidence.json#/turns/0`

### `0027-audio_booking-faulty-r1`: FAIL

Scenario `audio_booking`, variant `faulty`, repeat 1. Evidence: [attempts/0027-audio_booking-faulty-r1/evidence.json](attempts/0027-audio_booking-faulty-r1/evidence.json). Runner duration (measured): 62.0 ms.

- **FAIL** `booking_starts_at_mismatch`: Booking B1 starts_at '2026-12-01T11:00:00Z', expected '2026-12-01T10:00:00Z'. Evidence: `attempts/0027-audio_booking-faulty-r1/evidence.json#/state/body/bookings/0`
- Response audio: [turn-01.response.wav](attempts/0027-audio_booking-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0027-audio_booking-faulty-r1/turn-02.response.wav)

### `0028-audio_booking-faulty-r2`: FAIL

Scenario `audio_booking`, variant `faulty`, repeat 2. Evidence: [attempts/0028-audio_booking-faulty-r2/evidence.json](attempts/0028-audio_booking-faulty-r2/evidence.json). Runner duration (measured): 62.0 ms.

- **FAIL** `booking_starts_at_mismatch`: Booking B1 starts_at '2026-12-01T11:00:00Z', expected '2026-12-01T10:00:00Z'. Evidence: `attempts/0028-audio_booking-faulty-r2/evidence.json#/state/body/bookings/0`
- Response audio: [turn-01.response.wav](attempts/0028-audio_booking-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0028-audio_booking-faulty-r2/turn-02.response.wav)

### `0031-audio_interruption-faulty-r1`: FAIL

Scenario `audio_interruption`, variant `faulty`, repeat 1. Evidence: [attempts/0031-audio_interruption-faulty-r1/evidence.json](attempts/0031-audio_interruption-faulty-r1/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '10 Oak Street'. Evidence: `attempts/0031-audio_interruption-faulty-r1/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0005, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0031-audio_interruption-faulty-r1/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0031-audio_interruption-faulty-r1/turn-01.response.wav), [turn-03.response.wav](attempts/0031-audio_interruption-faulty-r1/turn-03.response.wav)

### `0032-audio_interruption-faulty-r2`: FAIL

Scenario `audio_interruption`, variant `faulty`, repeat 2. Evidence: [attempts/0032-audio_interruption-faulty-r2/evidence.json](attempts/0032-audio_interruption-faulty-r2/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '10 Oak Street'. Evidence: `attempts/0032-audio_interruption-faulty-r2/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0005, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0032-audio_interruption-faulty-r2/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0032-audio_interruption-faulty-r2/turn-01.response.wav), [turn-03.response.wav](attempts/0032-audio_interruption-faulty-r2/turn-03.response.wav)

### `0035-chat_address_confirmed-faulty-r1`: FAIL

Scenario `chat_address_confirmed`, variant `faulty`, repeat 1. Evidence: [attempts/0035-chat_address_confirmed-faulty-r1/evidence.json](attempts/0035-chat_address_confirmed-faulty-r1/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '14 Pine Street'. Evidence: `attempts/0035-chat_address_confirmed-faulty-r1/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0003, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0035-chat_address_confirmed-faulty-r1/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0035-chat_address_confirmed-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0035-chat_address_confirmed-faulty-r1/turn-02.response.wav)

### `0036-chat_address_confirmed-faulty-r2`: FAIL

Scenario `chat_address_confirmed`, variant `faulty`, repeat 2. Evidence: [attempts/0036-chat_address_confirmed-faulty-r2/evidence.json](attempts/0036-chat_address_confirmed-faulty-r2/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '14 Pine Street'. Evidence: `attempts/0036-chat_address_confirmed-faulty-r2/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0003, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0036-chat_address_confirmed-faulty-r2/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0036-chat_address_confirmed-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0036-chat_address_confirmed-faulty-r2/turn-02.response.wav)

### `0039-audio_address_confirmed-faulty-r1`: FAIL

Scenario `audio_address_confirmed`, variant `faulty`, repeat 1. Evidence: [attempts/0039-audio_address_confirmed-faulty-r1/evidence.json](attempts/0039-audio_address_confirmed-faulty-r1/evidence.json). Runner duration (measured): 31.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '14 Pine Street'. Evidence: `attempts/0039-audio_address_confirmed-faulty-r1/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0005, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0039-audio_address_confirmed-faulty-r1/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0039-audio_address_confirmed-faulty-r1/turn-01.response.wav), [turn-02.response.wav](attempts/0039-audio_address_confirmed-faulty-r1/turn-02.response.wav)

### `0040-audio_address_confirmed-faulty-r2`: FAIL

Scenario `audio_address_confirmed`, variant `faulty`, repeat 2. Evidence: [attempts/0040-audio_address_confirmed-faulty-r2/evidence.json](attempts/0040-audio_address_confirmed-faulty-r2/evidence.json). Runner duration (measured): 47.0 ms.

- **FAIL** `address_mismatch`: Final address is '40 Pine Street', expected '14 Pine Street'. Evidence: `attempts/0040-audio_address_confirmed-faulty-r2/evidence.json#/state/body/address`
- **FAIL** `unconfirmed_write`: Write update_address (event-0005, turn-1) was committed with confirmed=False in the audit log. Evidence: `attempts/0040-audio_address_confirmed-faulty-r2/evidence.json#/state/body/audit_log/0`
- Response audio: [turn-01.response.wav](attempts/0040-audio_address_confirmed-faulty-r2/turn-01.response.wav), [turn-02.response.wav](attempts/0040-audio_address_confirmed-faulty-r2/turn-02.response.wav)


## Variant comparison

See [comparison.md](comparison.md) for baseline versus candidate.


## Notes

- Verdicts come from authoritative state, the audit log, turn outcomes, and timing events; the trace is saved as evidence but is not authoritative.
- Runner durations are wall-clock measurements by the evaluator, not agent latency metrics.
