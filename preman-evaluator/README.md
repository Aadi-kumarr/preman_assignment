# PreMan agent evaluator

Runs scripted chat and recorded-audio conversations against the supplied target
agent, checks what the agent actually did using authoritative state and the
audit log, grades each attempt PASS, FAIL, ERROR, or INCONCLUSIVE, computes
audio timing metrics, compares a baseline variant with a candidate, and
regrades any saved run offline.

Python 3.10 or later, standard library only (nothing to install or pin). The
starter kit is expected in a sibling folder, `../preman-agent-evaluation`, and
is never modified.

## Architecture

| Component | File | Job |
|---|---|---|
| Scenario loader | `preman_eval/scenarios.py` | Loads and validates scenario files. Scenarios are data; nothing in the code knows a case name. |
| Target client | `preman_eval/client.py` | `urllib` client for the documented endpoints. Handles non-JSON error bodies. |
| Adapters | `preman_eval/adapters.py` | Turn one scenario step into one target request and return an evidence record. `ChatAdapter` sends text; `AudioAdapter` sends WAV bytes and interrupts. |
| Runner | `preman_eval/runner.py` | One session per scenario, variant and repeat. Bounded concurrency. Saves evidence, then deletes the session in a `finally` block. Writes the manifest. |
| Metrics | `preman_eval/metrics.py` | Audio metrics from saved events. Pure functions. |
| Grader | `preman_eval/grader.py` | Checks and verdict precedence. Pure functions over saved evidence. |
| Comparison | `preman_eval/compare.py` | Baseline versus candidate, and run-to-run equivalence. |
| Replay | `preman_eval/replay.py` | Offline regrade from saved evidence. Has no HTTP client. |
| Report | `preman_eval/report.py` | Markdown report and observed-behaviour tables. |
| Support | `config.py`, `hashing.py`, `target_process.py`, `cli.py` | Config, content hashes, optional target launcher, command line. |

Data flow:

```text
scenario files -> loader -> runner -> adapter -> target (HTTP)
                              |
                              v
             attempts/<id>/evidence.json + response WAVs      (saved once, never rewritten)
                              |
                              v
          metrics -> grader -> results.json -> report.md, comparison.md
                              ^
                              |
        replay reads the same evidence again, with the same or changed expectations
```

The adapter boundary is the only place that knows how a target is spoken to.
The runner owns sessions, ordering, state reads and cleanup. The grader,
metrics, comparison and replay only ever see saved evidence, which is why
replay needs no target.

### Connecting a real customer agent

Implement one class in `preman_eval/adapters.py`:

```python
class TurnAdapter:
    modality = "chat" or "audio"
    def send_turn(self, client, session_id, turn, index, deadline_ms, attempt_dir, harness_timeout_ms=5000):
        ...  # send one step, return an evidence record
```

`turn` is the scenario step (`{"type": "text", "text": ...}`,
`{"type": "audio", "path": ...}` or `{"type": "interrupt"}`). The returned
record must contain:

- `index`, `type`, `request` (what was sent, without inline audio);
- `outcome`: `ok`, `http_error`, `timeout` or `transport_error`;
- `elapsed_ms` (measured), `deadline_ms`, `deadline_exceeded`;
- `body`: the agent's reply, including `turn_id`, `response_id` and `events`;
- `audio_artifact`: pointer to the saved response audio (file, SHA-256, playable, duration).

What a real agent, or a shim in front of it, must provide:

| Need | Supplied target | Real agent equivalent |
|---|---|---|
| Isolated session | `POST /sessions`, `DELETE /sessions/{id}` | A fresh sandbox account, tenant or call per attempt, and a way to tear it down. |
| Send a turn | `POST /sessions/{id}/turn` | Chat API call, or streaming audio frames over WebSocket, WebRTC or telephony. |
| Interrupt | `POST /sessions/{id}/interrupt` | Start sending user audio while the agent is still speaking. |
| Authoritative state | `GET /sessions/{id}/state` | Read the booking and address system of record directly, not the agent's reply. |
| Audit log | `audit_log` in state | Tool-call or write log with a confirmed flag and the turn that caused each write. |
| Trace | `GET /sessions/{id}/trace` | Provider and client telemetry. |

Audio and interruption telemetry map to the same four event kinds, each tagged
with `session_id`, `turn_id`, `response_id`, `at_ms`, `clock_domain` and
`timing_source`:

| Event | What a real adapter observes |
|---|---|
| `user_utterance_end` | The moment the last frame of user audio was sent. |
| `first_audio_played` | The moment the first agent audio frame was actually played out, not merely received. |
| `user_speech_start` | The moment interrupting user audio began to be sent. |
| `playback_stopped` | The moment agent audio actually stopped playing. |

What would have to change:

- A new adapter and client for the agent's transport. For streaming audio the
  adapter itself must timestamp these moments on one client-side monotonic
  clock and emit them with `timing_source: "measured"`.
- State and trace reads in `runner.py` and `client.py` currently call the
  supplied endpoints; they would move behind the same kind of boundary.
- `eval_config.json`: target address, variants, confirmation phrases, and the
  source of each recording's words (currently the starter's audio manifest).
- Nothing in metrics, grader, comparison, replay or report: they read the
  saved record shape only.

## Status precedence

**FAIL > ERROR > INCONCLUSIVE > PASS.** Each attempt takes the worst verdict
among its reasons. Every reason is kept, so a verified failure stands when a
timeout, harness error or missing evidence is also present, and those appear as
additional reasons.

| Verdict | Driven by | Reason codes |
|---|---|---|
| FAIL | A turn got no response within `turn_timeout_ms`, or the response was late. Later steps are not sent. | `timeout` |
| FAIL | Authoritative `GET /state` differs from `expect`. Stays FAIL even if a turn timed out or errored. | `booking_count_mismatch`, `booking_customer_mismatch`, `booking_starts_at_mismatch`, `address_mismatch` |
| FAIL | Policy: an audited write without `confirmed: true`, or without a user confirmation turn at or before the turn that committed it. | `unconfirmed_write`, `write_without_user_confirmation` |
| FAIL | A measured audio value is over the scenario's limit. | `first_audio_playback_over_limit`, `interruption_stop_over_limit` |
| ERROR | The state read failed. The trace is not authoritative and is not used instead. | `state_read_failed` |
| ERROR | The test run broke, not the agent. | `session_create_failed`, `turn_failed`, `interrupt_failed`, `trace_read_failed`, `session_cleanup_failed`, `harness_exception` |
| INCONCLUSIVE | Required evidence is missing or was rejected. | `first_audio_playback_unavailable`, `first_audio_playback_incompatible`, `interruption_stop_unavailable`, `interruption_stop_incompatible`, `response_audio_missing`, `response_audio_unplayable`, `confirmation_unverifiable`, `write_turn_uncorrelated`, `state_evidence_missing`, `evidence_missing` |
| PASS | No reason of any kind. | none |

The grader reads only the `expect` block, the deadline, and saved evidence. It
never looks at the scenario ID, run ID, variant, or fixture name. Grading reads
final state, so booking IDs and tool-call order are not prescribed: a different
valid tool path that ends in the same state passes. Bookings are counted from
state only; repeated tool results in the trace are reported beside the count
but never counted as bookings. A check is applied only if the scenario's
`expect` names it.

Decisions made while building, and where each applies:

| ID | Decision |
|---|---|
| D1 | The address expected by `audio_address_confirmed` is `14 Pine Street` because the user asks for it and confirms it. A gate run then showed baseline does the same. It was not derived from the target's output. |
| D2 | `audio_address_confirmed` also carries `max_first_audio_playback_ms: 1000`, in addition to the address and confirmation checks. |
| D3 | For the confirmation rule, the words of an audio turn come from the starter's audio manifest, matched by the WAV's SHA-256, not from the target's transcript. They are never sent to the target. An unknown recording gives `confirmation_unverifiable`. |
| D4 | Identical duplicate events, as repeated interrupts on one response produce, are deduplicated. Each interrupt still gets its own metric entry. Duplicates that disagree are rejected. |
| D5 | Rejected metrics (impossible or mismatched timestamps) are INCONCLUSIVE, like missing telemetry, not FAIL. |
| D6 | Missing or unplayable response audio on an audio turn is INCONCLUSIVE. |
| D7 | A failed interrupt request is ERROR (`interrupt_failed`), never a timeout FAIL. Interrupts use `harness_timeout_ms`, not the turn deadline. |
| D8 | Validation rejects an audio limit on a chat scenario, and an interruption limit with no interrupt turn. |
| D9 | Replay refuses a changed `turn_timeout_ms`, `fixture`, `modality` or `turns`. Those change the conversation and need a new target run. |
| D10 | In the comparison, a scenario with any ERROR or INCONCLUSIVE attempt on either side is "invalid or unavailable", not a regression or improvement. |
| D11 | The first configured variant is the baseline. `compare --baseline/--candidate` overrides it. |
| D12 | Replays are saved in `replays/` beside `runs/` and link to the original evidence by relative path instead of copying it. |
| D13 | If a response contains the right event kind only for a different turn or response, the metric is rejected as an ID mismatch. If correctly scoped events exist, unrelated ones are ignored. |

Two further rules: "earlier confirmation" includes the turn that commits the
write, since the user's confirmation is that turn's input; and confirmation
phrases are configured in `eval_config.json`.

## Reproducibility

Setup: Python 3.10 or later. There is nothing to install: `requirements.txt`
records that the evaluator uses the standard library only and has no
third-party dependencies to pin. Put the starter kit beside this folder as
`../preman-agent-evaluation`. Run everything from this folder, and use
`python3` instead of `python` if that is your interpreter's name.

Start the target (separate terminal, from the starter folder):

```sh
cd ../preman-agent-evaluation
PYTHONDONTWRITEBYTECODE=1 python3 target_server.py --port 8765
```

Run, compare, replay, report, test:

```sh
python -m preman_eval validate                               # check both scenario files
python -m preman_eval starter-hash                           # starter SHA-256, checked against eval_config.json
python -m preman_eval run --repeats 2 --concurrency 1        # 10 scenarios x 2 variants x 2 repeats = 40 attempts
python -m preman_eval run --repeats 2 --concurrency 3
python -m preman_eval run --repeats 2 --launch-target        # one command: starts a temporary target itself
python -m preman_eval compare --run runs/<run_id>            # rebuild comparison.md and comparison.json
python -m preman_eval compare-runs --a runs/<id1> --b runs/<id2>   # are two runs equivalent?
python -m preman_eval replay --run runs/<run_id>             # offline regrade, target stopped
python -m preman_eval replay --run runs/<run_id> --set "audio_booking.max_first_audio_playback_ms=500"
python -m preman_eval replay --run runs/<run_id> --set "*.max_first_audio_playback_ms=500"
python -m preman_eval replay --run runs/<run_id> --scenarios edited_scenarios.json
python -m preman_eval report --run runs/<run_id>             # rebuild report.md (run or replay folder)
python -m preman_eval observe --run runs/<run_id> --modality audio
python -B -m unittest discover -s tests                      # evaluator tests; no running target needed
```

Starter tests, from inside the starter:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests
```

Each run is saved in a new folder `runs/<UTC time>-<random>/` and each replay in
`replays/replay-<UTC time>-<random>/`. Nothing is overwritten.

A run manifest records: run ID; UTC start and finish; evaluator git commit (or
`uncommitted`) and source hash; starter folder SHA-256 before and after the
run; each scenario file's path, SHA-256 and saved copy; target URL, variants and
active-session counts before and after; concurrency; repeats; harness timeout;
confirmation phrases; attempt, scenario and repeat counts; measured suite
wall-clock time; and the relative path of every evidence file and WAV.

A replay manifest records: replay ID; the original run ID and relative path;
the replay's own duration, separate from the original run's timings; changed
expectations (old and new); every attempt whose outcome differs from the
original; missing or altered artifacts; and a copy of the original manifest.

### Submitted runs

The submitted demo runs are the two newest folders in `runs/`, one at
concurrency 1 and one at concurrency 3. Their run IDs and verdict counts are in
`evidence/demo_concurrency_equivalence.md`, and each manifest records the commit
that produced it. Each run is 40 attempts: 10 distinct scenarios, 2 variants,
2 repeats.

| Concurrency | Variant | PASS | FAIL | ERROR | INCONCLUSIVE |
|---|---|---|---|---|---|
| 1 | baseline | 16/20 | 2/20 | 2/20 | 0/20 |
| 1 | faulty | 0/20 | 18/20 | 2/20 | 0/20 |
| 3 | baseline | 16/20 | 2/20 | 2/20 | 0/20 |
| 3 | faulty | 0/20 | 18/20 | 2/20 | 0/20 |

- The two runs agree on all 40 attempts (`evidence/demo_concurrency_equivalence.md`).
- Comparison, baseline versus faulty: 8/10 scenarios regress, 1/10 is an
  unchanged failure (`chat_timeout`), 1/10 is invalid (`chat_state_error`).
  Policy failures: 0/20 baseline attempts, 8/20 faulty attempts, in 4/10 scenarios.
- Audio metrics, both variants: first playback 640 ms on every audio turn,
  interruption stop 320 ms, all on the simulated fixture clock.
- Each run has a replay with unchanged expectations in `replays/` that
  reproduces every outcome with 0 differences. Each replay manifest names its
  original run.
- Threshold walkthrough: one more replay regrades the concurrency 1 run with
  `--set "audio_booking.max_first_audio_playback_ms=500"`. The measured 640 ms
  is then over the limit on both audio turns of `audio_booking`, and the replay
  manifest lists each attempt whose outcome changed.

### Included runs

Every run and replay in this repository was produced at commit `01efb3d`
(`01efb3dd5592cbc6cd9975f637dd7e8ce16050fd`), and each manifest records that
hash.

- `runs/20261116T192718Z-5d07ae8c`: concurrency 1, 40 attempts.
- `runs/20261116T192723Z-e178942f`: concurrency 3, 40 attempts.
- `replays/replay-20261116T192731Z-3389e5db`: the concurrency 1 run regraded
  with unchanged expectations; 0 of 40 attempts differ.
- `replays/replay-20261116T192731Z-4658fdcb`: the concurrency 3 run regraded
  with unchanged expectations; 0 of 40 attempts differ.
- `replays/replay-20261116T192732Z-3ae3c97a`: the concurrency 1 run regraded
  with `--set "audio_booking.max_first_audio_playback_ms=500"`; the 4
  `audio_booking` attempts gain `first_audio_playback_over_limit`.

Runs and replays made earlier, during development, are not included.

### Added scenarios

In `scenarios_added.json`; `scenarios.json` in the starter is untouched.

| Scenario | Conversation | Baseline | Faulty |
|---|---|---|---|
| `chat_address_confirmed` | Ask for the address change, then "Yes, confirm". | Saves `14 Pine Street` in one confirmed write: PASS. | Writes `40 Pine Street` on the first turn without confirmation: FAIL (`address_mismatch`, `unconfirmed_write`). |
| `audio_address_confirmed` | `address_request.wav`, then `confirm.wav`. | Saves `14 Pine Street` in one confirmed write: PASS. | Writes `40 Pine Street` unconfirmed: FAIL (`address_mismatch`, `unconfirmed_write`). |

No supplied scenario confirms an address change, so the "confirmed write is
allowed" side of the policy is otherwise untested. `audio_address_confirmed` is
the only case that takes the audio path into the confirmation rule with a write
present on baseline: the evaluator has to recognise a spoken confirmation before
the audit entry. The supplied `audio_interruption` only ever expects no write.

## Limitations

- **Scripted target only.** The supplied service is a test double. It matches
  input WAVs by SHA-256 and returns prerecorded audio.
- **No real STT or TTS.** Nothing here measures recognition or speech quality.
- **Simulated audio timing.** The metrics come from the target's fixture clock
  (`timing_source: "simulated"`). They exercise the measurement code and say
  nothing about real latency. Measured wall-clock time is reported separately
  as `runner_duration_ms`.
- **Approximate deadlines.** The turn deadline is a socket timeout plus a check
  of total elapsed time. A target that stalls is cut off at the deadline. A
  target that trickles bytes slowly is flagged late (`timeout`, FAIL) but may
  not be cut off at exactly the deadline.
- **Two supplied scenarios never pass, by design.** `chat_timeout` is a timeout
  FAIL on both variants (the slow fixture takes 2,000 ms against a 400 ms
  deadline). `chat_state_error` is ERROR on both variants (the state read
  always returns 503).
- **No live faults for missing telemetry.** The real target always returns
  complete timing events within the limits, with identical values on both
  variants. Missing, rejected and over-limit metrics are covered by unit tests
  and by the changed-threshold replay, not by a live case.
- **Interrupts are scripted.** The interrupt is a request that returns
  telemetry, not a real concurrent barge-in.
- **Timeout evidence is a snapshot.** After a client timeout the state is read
  immediately, while the slow turn may still be pending on the server.

## Time spent

Approximately 8 hours.

## Unfinished work and next engineering step

- There is no single index page listing every run and replay.

Next step: put state and trace reads behind the adapter boundary, so that a
real agent needs only one new class, then build a streaming audio adapter that
timestamps playback on a client-side clock.

## AI tools used and verification

This evaluator was built with help of Claude Code, an AI coding assistant. Claude Code
helped draft parts of the source code, tests, and documentation. I directed the
work, read through the source and tests, ran the test suite and a demo run
myself, and checked the report against the saved evidence.

How the code was checked:

- **Evaluator tests.** 137 `unittest` tests, 0 failures, 0 skips. They cover
  scenario and config validation, the client, runner cleanup and isolation,
  every grading rule and the precedence order, both metric calculations,
  timestamp rejection, missing telemetry, duplicate interrupt events, WAV
  playability, comparison groups and denominators, and replay.
- **Integration tests.** Four of those tests run the real supplied target as a
  child process on an ephemeral port, for chat and audio, on both variants.
  They fail, not skip, if the starter is missing.
- **Verification gates.** Before any expectation was relied on, the supplied
  scenarios were run against both variants and the observed state recorded in
  `evidence/gate_chat_observed.md` and `evidence/gate_audio_observed.md`.
  Those two files were generated during development; the runs they name are
  not included in this repository.
  Baseline matched every expectation where state could be read. No expectation
  was changed to fit the target.
- **Starter hash.** The starter folder's SHA-256
  (`8b94a55636e92a395112fdc1ef366b1f0fb86fcd85158100dadcf7e9a9f17525`, 16
  files) is checked before each run, recorded before and after in every
  manifest, and has not changed. The starter's own 9 tests still pass.
- **Replay makes zero requests.** The replay tests block `socket.socket`,
  `socket.create_connection` and `urllib`, replay with the target stopped, and
  assert the stopped fake target received no further calls. The replay module
  contains no client code.
- **Concurrency.** The concurrency 1 and concurrency 3 demo runs agree on all
  40 attempts.
- **Paths.** Generated manifests, results, reports and replays were scanned for
  absolute filesystem paths; none were found.

Not independently verified:

- The WAV files were checked for format and playability with the `wave` module.
  Nobody listened to them here to confirm what they say.
- The evaluator was run on Windows with Python 3.11 only. It uses `pathlib` and
  relative paths throughout, but was not run on Linux or macOS.
- The grading rules encode the decisions listed above. They were tested for
  self-consistency, not reviewed against an external answer key.
