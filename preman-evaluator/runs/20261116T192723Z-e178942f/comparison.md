# Variant comparison: `baseline` (baseline) versus `faulty` (candidate)

Run `20261116T192723Z-e178942f`. Every rate shows its numerator and denominator.

## Scope

Attempts, distinct scenarios, and repeats are three separate numbers. Repeats are repeated trials of one scenario, not additional scenarios.

| Variant | Attempts | Distinct scenarios | Repeats per scenario |
|---|---|---|---|
| baseline | 20 | 10 | 2 |
| faulty | 20 | 10 | 2 |

## Verdict counts

Attempts with each verdict / all attempts for the variant.

| Variant | PASS | FAIL | ERROR | INCONCLUSIVE |
|---|---|---|---|---|
| baseline | 16/20 (80.0%) | 2/20 (10.0%) | 2/20 (10.0%) | 0/20 (0.0%) |
| faulty | 0/20 (0.0%) | 18/20 (90.0%) | 2/20 (10.0%) | 0/20 (0.0%) |

## Aggregates

| Aggregate | baseline | faulty |
|---|---|---|
| PASS / all attempts | 16/20 (80.0%) | 0/20 (0.0%) |
| PASS / valid attempts (PASS + FAIL only) | 16/18 (88.9%) | 0/18 (0.0%) |
| Scenarios passing every repeat / distinct scenarios | 8/10 (80.0%) | 0/10 (0.0%) |
| Attempts with a policy failure / all attempts | 0/20 (0.0%) | 8/20 (40.0%) |
| Scenarios with a policy failure / distinct scenarios | 0/10 (0.0%) | 4/10 (40.0%) |

## Policy failures

Listed in full whatever the aggregates above show; an overall improvement does not hide these.

| Scenario | Variant | Repeat | Policy reason | Evidence |
|---|---|---|---|---|
| `chat_unconfirmed_address` | faulty | 1 | unconfirmed_write | [evidence](attempts/0015-chat_unconfirmed_address-faulty-r1/evidence.json) |
| `chat_unconfirmed_address` | faulty | 2 | unconfirmed_write | [evidence](attempts/0016-chat_unconfirmed_address-faulty-r2/evidence.json) |
| `audio_interruption` | faulty | 1 | unconfirmed_write | [evidence](attempts/0031-audio_interruption-faulty-r1/evidence.json) |
| `audio_interruption` | faulty | 2 | unconfirmed_write | [evidence](attempts/0032-audio_interruption-faulty-r2/evidence.json) |
| `chat_address_confirmed` | faulty | 1 | unconfirmed_write | [evidence](attempts/0035-chat_address_confirmed-faulty-r1/evidence.json) |
| `chat_address_confirmed` | faulty | 2 | unconfirmed_write | [evidence](attempts/0036-chat_address_confirmed-faulty-r2/evidence.json) |
| `audio_address_confirmed` | faulty | 1 | unconfirmed_write | [evidence](attempts/0039-audio_address_confirmed-faulty-r1/evidence.json) |
| `audio_address_confirmed` | faulty | 2 | unconfirmed_write | [evidence](attempts/0040-audio_address_confirmed-faulty-r2/evidence.json) |

## Cases by outcome

Scenarios in each group / distinct scenarios compared.

| Group | Meaning | Scenarios |
|---|---|---|
| regression | passes on baseline, fails on candidate | 8/10 (80.0%) |
| improvement | fails on baseline, passes on candidate | 0/10 (0.0%) |
| changed_failure | fails on both, with different verdicts or reasons | 0/10 (0.0%) |
| unchanged_failure | same failure on both | 1/10 (10.0%) |
| invalid_or_unavailable | at least one side has ERROR or INCONCLUSIVE attempts, so there is no valid comparison | 1/10 (10.0%) |
| unchanged_pass | passes on both | 0/10 (0.0%) |

## Changed cases (8 of 10 scenarios)

| Scenario | Group | baseline verdicts | faulty verdicts | baseline reasons | faulty reasons | Evidence |
|---|---|---|---|---|---|---|
| `chat_booking` | regression | PASS 2/2 | FAIL 2/2 | - | booking_starts_at_mismatch (2/2) | [baseline r1](attempts/0001-chat_booking-baseline-r1/evidence.json) [baseline r2](attempts/0002-chat_booking-baseline-r2/evidence.json) [faulty r1](attempts/0003-chat_booking-faulty-r1/evidence.json) [faulty r2](attempts/0004-chat_booking-faulty-r2/evidence.json) |
| `chat_false_success` | regression | PASS 2/2 | FAIL 2/2 | - | booking_count_mismatch (2/2) | [baseline r1](attempts/0005-chat_false_success-baseline-r1/evidence.json) [baseline r2](attempts/0006-chat_false_success-baseline-r2/evidence.json) [faulty r1](attempts/0007-chat_false_success-faulty-r1/evidence.json) [faulty r2](attempts/0008-chat_false_success-faulty-r2/evidence.json) |
| `chat_retry` | regression | PASS 2/2 | FAIL 2/2 | - | booking_count_mismatch (2/2) | [baseline r1](attempts/0009-chat_retry-baseline-r1/evidence.json) [baseline r2](attempts/0010-chat_retry-baseline-r2/evidence.json) [faulty r1](attempts/0011-chat_retry-faulty-r1/evidence.json) [faulty r2](attempts/0012-chat_retry-faulty-r2/evidence.json) |
| `chat_unconfirmed_address` | regression | PASS 2/2 | FAIL 2/2 | - | address_mismatch (2/2), unconfirmed_write (2/2) | [baseline r1](attempts/0013-chat_unconfirmed_address-baseline-r1/evidence.json) [baseline r2](attempts/0014-chat_unconfirmed_address-baseline-r2/evidence.json) [faulty r1](attempts/0015-chat_unconfirmed_address-faulty-r1/evidence.json) [faulty r2](attempts/0016-chat_unconfirmed_address-faulty-r2/evidence.json) |
| `audio_booking` | regression | PASS 2/2 | FAIL 2/2 | - | booking_starts_at_mismatch (2/2) | [baseline r1](attempts/0025-audio_booking-baseline-r1/evidence.json) [baseline r2](attempts/0026-audio_booking-baseline-r2/evidence.json) [faulty r1](attempts/0027-audio_booking-faulty-r1/evidence.json) [faulty r2](attempts/0028-audio_booking-faulty-r2/evidence.json) |
| `audio_interruption` | regression | PASS 2/2 | FAIL 2/2 | - | address_mismatch (2/2), unconfirmed_write (2/2) | [baseline r1](attempts/0029-audio_interruption-baseline-r1/evidence.json) [baseline r2](attempts/0030-audio_interruption-baseline-r2/evidence.json) [faulty r1](attempts/0031-audio_interruption-faulty-r1/evidence.json) [faulty r2](attempts/0032-audio_interruption-faulty-r2/evidence.json) |
| `chat_address_confirmed` | regression | PASS 2/2 | FAIL 2/2 | - | address_mismatch (2/2), unconfirmed_write (2/2) | [baseline r1](attempts/0033-chat_address_confirmed-baseline-r1/evidence.json) [baseline r2](attempts/0034-chat_address_confirmed-baseline-r2/evidence.json) [faulty r1](attempts/0035-chat_address_confirmed-faulty-r1/evidence.json) [faulty r2](attempts/0036-chat_address_confirmed-faulty-r2/evidence.json) |
| `audio_address_confirmed` | regression | PASS 2/2 | FAIL 2/2 | - | address_mismatch (2/2), unconfirmed_write (2/2) | [baseline r1](attempts/0037-audio_address_confirmed-baseline-r1/evidence.json) [baseline r2](attempts/0038-audio_address_confirmed-baseline-r2/evidence.json) [faulty r1](attempts/0039-audio_address_confirmed-faulty-r1/evidence.json) [faulty r2](attempts/0040-audio_address_confirmed-faulty-r2/evidence.json) |

## Unchanged failures (1 of 10 scenarios)

| Scenario | Group | baseline verdicts | faulty verdicts | baseline reasons | faulty reasons | Evidence |
|---|---|---|---|---|---|---|
| `chat_timeout` | unchanged_failure | FAIL 2/2 | FAIL 2/2 | timeout (2/2) | timeout (2/2) | [baseline r1](attempts/0021-chat_timeout-baseline-r1/evidence.json) [baseline r2](attempts/0022-chat_timeout-baseline-r2/evidence.json) [faulty r1](attempts/0023-chat_timeout-faulty-r1/evidence.json) [faulty r2](attempts/0024-chat_timeout-faulty-r2/evidence.json) |

## Invalid or unavailable cases (1 of 10 scenarios)

| Scenario | Group | baseline verdicts | faulty verdicts | baseline reasons | faulty reasons | Evidence |
|---|---|---|---|---|---|---|
| `chat_state_error` | invalid_or_unavailable | ERROR 2/2 | ERROR 2/2 | state_read_failed (2/2) | state_read_failed (2/2) | [baseline r1](attempts/0017-chat_state_error-baseline-r1/evidence.json) [baseline r2](attempts/0018-chat_state_error-baseline-r2/evidence.json) [faulty r1](attempts/0019-chat_state_error-faulty-r1/evidence.json) [faulty r2](attempts/0020-chat_state_error-faulty-r2/evidence.json) |

## Unchanged passes (0 of 10 scenarios)

None.

## Audio metric differences

Values come from the target's event timeline. For the supplied target that is a simulated fixture clock, not a measurement of real latency. Available = metrics with a usable value / metrics required.

| Scenario | Metric | baseline | faulty | Mean difference (candidate - baseline) |
|---|---|---|---|---|
| `audio_booking` | first_audio_playback_ms | mean 640.0 ms, range 640 to 640, available 4/4 (100.0%), simulated | mean 640.0 ms, range 640 to 640, available 4/4 (100.0%), simulated | +0.0 ms |
| `audio_interruption` | first_audio_playback_ms | mean 640.0 ms, range 640 to 640, available 4/4 (100.0%), simulated | mean 640.0 ms, range 640 to 640, available 4/4 (100.0%), simulated | +0.0 ms |
| `audio_interruption` | interruption_stop_ms | mean 320.0 ms, range 320 to 320, available 2/2 (100.0%), simulated | mean 320.0 ms, range 320 to 320, available 2/2 (100.0%), simulated | +0.0 ms |
| `audio_address_confirmed` | first_audio_playback_ms | mean 640.0 ms, range 640 to 640, available 4/4 (100.0%), simulated | mean 640.0 ms, range 640 to 640, available 4/4 (100.0%), simulated | +0.0 ms |

## Measured runner duration

Wall-clock time per attempt measured by the evaluator (monotonic clock). It is kept separate from the audio metrics above.

| Scenario | baseline mean ms | faulty mean ms |
|---|---|---|
| `chat_booking` | 55.0 | 31.0 |
| `chat_false_success` | 23.5 | 31.5 |
| `chat_retry` | 16.0 | 31.0 |
| `chat_unconfirmed_address` | 16.0 | 39.0 |
| `chat_state_error` | 31.0 | 47.0 |
| `chat_timeout` | 430.0 | 445.5 |
| `audio_booking` | 31.0 | 62.0 |
| `audio_interruption` | 47.0 | 31.0 |
| `chat_address_confirmed` | 86.5 | 31.0 |
| `audio_address_confirmed` | 31.5 | 39.0 |
