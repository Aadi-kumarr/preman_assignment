"""Suite runner: isolated sessions, ordered turns, evidence capture, guaranteed cleanup."""
import json
import re
import secrets
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .adapters import SUPPORTED_MODALITIES, build_adapters, load_utterances
from .client import TargetClient, exchange
from .compare import build_comparison, render_comparison
from .grader import PRECEDENCE, build_attempt_result
from .hashing import evaluator_identity, sha256_file, sha256_tree
from .report import build_report

EVIDENCE_SCHEMA = 1


class RunError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")[:60] or "scenario"


def run_attempt(client, adapter, scenario, variant, repeat, attempt_id, attempt_dir, run_id, harness_timeout_ms):
    """Run one scenario x variant x repeat in its own session and save its evidence.

    Order: create session, turns in order, state, trace, then DELETE in a
    ``finally`` block. All evidence is fetched before the session is deleted.
    Never raises: unexpected faults are recorded under ``harness_errors``.
    """
    started = time.monotonic()
    evidence = {
        "evidence_schema": EVIDENCE_SCHEMA, "attempt_id": attempt_id, "run_id": run_id,
        "scenario_id": scenario.id, "variant": variant, "repeat": repeat,
        "started_at_utc": utc_now(),
        "timing_note": "elapsed_ms values are measured by the runner with a monotonic clock; "
                       "at_ms values inside target events are the target's simulated fixture clock.",
        "session": {"outcome": "not_attempted"},
        "turns": [{"index": i, "type": t.get("type"), "outcome": "not_sent"} for i, t in enumerate(scenario.turns, 1)],
        "state": {"outcome": "not_attempted"}, "trace": {"outcome": "not_attempted"},
        "cleanup": {"outcome": "not_attempted"}, "harness_errors": [],
    }
    try:
        attempt_dir.mkdir(parents=True)
        request = {"run_id": run_id, "variant": variant, "fixture": scenario.fixture}
        session = exchange(lambda: client.create_session(timeout_ms=harness_timeout_ms, **request), 201)
        session["request"] = request
        session_id = (session.get("body") or {}).get("session_id") if session["outcome"] == "ok" else None
        if session["outcome"] == "ok" and not isinstance(session_id, str):
            session["outcome"] = "http_error"
        evidence["session"] = session
        if isinstance(session_id, str):
            try:
                try:
                    for index, turn in enumerate(scenario.turns, 1):
                        record = adapter.send_turn(client, session_id, turn, index, scenario.turn_timeout_ms,
                                                  attempt_dir, harness_timeout_ms)
                        evidence["turns"][index - 1] = record
                        if record["outcome"] != "ok":
                            break  # later turns would not be the scripted conversation; they stay "not_sent"
                except Exception as exc:  # evaluator fault inside the conversation
                    evidence["harness_errors"].append("%s: %s" % (type(exc).__name__, exc))
                # Evidence is collected whatever happened to the turns, and always before DELETE.
                evidence["state"] = exchange(lambda: client.get_state(session_id, harness_timeout_ms), 200)
                evidence["trace"] = exchange(lambda: client.get_trace(session_id, harness_timeout_ms), 200)
            finally:
                evidence["cleanup"] = exchange(lambda: client.delete_session(session_id, harness_timeout_ms), 200)
    except Exception as exc:
        evidence["harness_errors"].append("%s: %s" % (type(exc).__name__, exc))
    evidence["runner_duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    try:
        write_json(attempt_dir / "evidence.json", evidence)
    except Exception as exc:
        evidence["harness_errors"].append("could not save evidence: %s: %s" % (type(exc).__name__, exc))
    return evidence


def split_runnable(scenarios):
    """Separate scenarios that have an adapter from those that cannot be run yet."""
    runnable = [s for s in scenarios if s.modality in SUPPORTED_MODALITIES]
    skipped = [{"scenario_id": s.id, "source": s.source, "modality": s.modality,
                "reason": "no adapter for modality %r in this build" % s.modality}
               for s in scenarios if s.modality not in SUPPORTED_MODALITIES]
    return runnable, skipped


def _starter_hash(cfg):
    digest, count = sha256_tree(cfg.resolve(cfg.starter_dir))
    return {"sha256": digest, "files": count}


def _health(client, timeout_ms):
    record = exchange(lambda: client.health(timeout_ms), 200)
    return {"outcome": record["outcome"], "status": record.get("status"),
            "active_sessions": (record.get("body") or {}).get("active_sessions") if record["outcome"] == "ok" else None,
            "error": record.get("error")}


def run_suite(cfg, scenarios, skipped=(), client=None, adapters=None):
    """Run every scenario x variant x repeat; write evidence, results, manifest, report.

    Returns the new run directory. A previous run is never overwritten.
    """
    client = client or TargetClient(cfg.base_url)
    starter_dir = cfg.resolve(cfg.starter_dir)
    if adapters is None:
        adapters = build_adapters(starter_dir, load_utterances(starter_dir, cfg.audio_manifest))
    pick = adapters.get
    health_before = _health(client, cfg.harness_timeout_ms)
    if health_before["outcome"] != "ok":
        raise RunError("Target is not reachable at %s (%s). Start it with: python3 target_server.py --port 8765"
                       % (cfg.base_url, health_before.get("error") or "HTTP %s" % health_before.get("status")))

    starter_before = _starter_hash(cfg)
    expected = cfg.expected_starter_sha256
    if expected and starter_before["sha256"] != expected:
        raise RunError("Starter folder hash is %s but the configured expected_starter_sha256 is %s. "
                       "The starter has changed; refusing to run." % (starter_before["sha256"], expected))
    started_at = utc_now()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    run_dir = cfg.resolve(cfg.runs_dir) / run_id
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir()  # fails rather than overwrite an existing run

    scenario_files = []
    (run_dir / "scenarios").mkdir()
    for index, label in enumerate(dict.fromkeys(str(p) for p in cfg.scenario_files)):
        source = cfg.resolve(label)
        copy = "scenarios/%02d-%s" % (index, source.name)
        shutil.copyfile(source, run_dir / copy)
        scenario_files.append({"path": label, "sha256": sha256_file(source), "copy": copy})

    plan = []
    for scenario in scenarios:
        for variant in cfg.variants:
            for repeat in range(1, cfg.repeats + 1):
                attempt_id = "%04d-%s-%s-r%d" % (len(plan) + 1, _slug(scenario.id), _slug(variant), repeat)
                plan.append((scenario, variant, repeat, attempt_id))

    manifest = {
        "manifest_schema": 1, "run_id": run_id, "status": "running",
        "started_at_utc": started_at, "finished_at_utc": None,
        "evaluator": dict(evaluator_identity(), version=__version__,
                          python="%d.%d.%d" % sys.version_info[:3]),
        "starter": {"path": str(cfg.starter_dir), "sha256": starter_before["sha256"], "files": starter_before["files"],
                    "hash_method": "sha256 over every file's POSIX relative path and content sha256, in sorted path order",
                    "sha256_after_run": None, "unchanged_during_run": None,
                    "expected_sha256": expected, "matches_expected": (starter_before["sha256"] == expected) if expected else None},
        "scenario_files": scenario_files,
        "target": {"base_url": cfg.base_url, "variants": list(cfg.variants),
                   "health_before": health_before, "health_after": None},
        "config": cfg.public(), "concurrency": cfg.concurrency, "repeats": cfg.repeats,
        "harness_timeout_ms": cfg.harness_timeout_ms,
        "policy": {"confirmation_phrases": list(cfg.confirmation_phrases)},
        "counts": {"distinct_scenarios": len(scenarios), "variants": len(cfg.variants),
                   "repeats": cfg.repeats, "attempts": len(plan)},
        "skipped_scenarios": list(skipped),
        "artifacts": {"results": "results.json", "report": "report.md", "scenario_copies": "scenarios/",
                      "comparison": None, "comparison_report": None},
        "attempts": [{"attempt_id": a, "scenario_id": s.id, "variant": v, "repeat": r,
                      "evidence": "attempts/%s/evidence.json" % a, "artifacts": []} for s, v, r, a in plan],
    }
    write_json(run_dir / "manifest.json", manifest)

    def work(item):
        scenario, variant, repeat, attempt_id = item
        attempt_dir = run_dir / "attempts" / attempt_id
        try:
            adapter = pick(scenario.modality)
            if adapter is None:
                raise RunError("no adapter for modality %r" % scenario.modality)
            return run_attempt(client, adapter, scenario, variant, repeat, attempt_id, attempt_dir,
                               run_id, cfg.harness_timeout_ms)
        except Exception as exc:  # one broken attempt must never stop the others
            return {"attempt_id": attempt_id, "scenario_id": scenario.id, "variant": variant, "repeat": repeat,
                    "harness_errors": ["%s: %s" % (type(exc).__name__, exc)]}

    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
        evidences = list(pool.map(work, plan))
    wall_ms = round((time.monotonic() - wall_start) * 1000, 1)

    policy = manifest["policy"]
    attempts = []
    for (scenario, variant, repeat, attempt_id), evidence, entry in zip(plan, evidences, manifest["attempts"]):
        entry["artifacts"] = ["attempts/%s/%s" % (attempt_id, t["audio_artifact"]["path"])
                              for t in evidence.get("turns", []) if t.get("audio_artifact")]
        attempts.append(build_attempt_result(entry, scenario.definition, scenario.source, evidence, policy,
                                             entry["evidence"], entry["artifacts"]))

    starter_after = _starter_hash(cfg)
    manifest["starter"]["sha256_after_run"] = starter_after["sha256"]
    manifest["starter"]["unchanged_during_run"] = starter_after == starter_before
    manifest["target"]["health_after"] = _health(client, cfg.harness_timeout_ms)
    manifest["finished_at_utc"] = utc_now()
    manifest["suite_wall_clock_ms"] = wall_ms
    manifest["status"] = "completed"
    results = {"results_schema": 1, "run_id": run_id, "verdict_precedence": list(PRECEDENCE), "attempts": attempts}
    write_json(run_dir / "results.json", results)
    if len(cfg.variants) >= 2:  # the first configured variant is the baseline
        comparison = build_comparison(results, cfg.variants[0], cfg.variants[1])
        write_json(run_dir / "comparison.json", comparison)
        (run_dir / "comparison.md").write_text(render_comparison(comparison), encoding="utf-8")
        manifest["artifacts"].update(comparison="comparison.json", comparison_report="comparison.md")
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "report.md").write_text(build_report(manifest, results), encoding="utf-8")
    return run_dir
