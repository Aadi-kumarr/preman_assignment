"""Offline regrading of a saved run. Reads files only; never contacts the target.

Replay recalculates every check from the evidence a run saved, optionally with
changed expectations or thresholds. Conversation inputs cannot be changed here:
that needs a new target run. Output goes to its own directory and points back at
the original run, whose files are left untouched.
"""
import copy
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from .compare import build_comparison, render_comparison
from .grader import PRECEDENCE, build_attempt_result
from .hashing import evaluator_identity, sha256_file
from .report import build_report
from .scenarios import CONVERSATION_FIELDS, validate_expect


class ReplayError(Exception):
    pass


def _read_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReplayError("Cannot read %s (%s): %s" % (what, Path(path).name, exc.strerror or exc)) from exc
    except ValueError as exc:
        raise ReplayError("%s (%s) is not valid JSON: %s" % (what, Path(path).name, exc)) from exc


def _relative(path, start):
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError as exc:  # different drives on Windows
        raise ReplayError("The replay directory must be on the same drive as the original run.") from exc


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_definitions(run_dir, manifest):
    """Scenario definitions exactly as the run used them (from its saved copies)."""
    definitions = {}
    for entry in manifest.get("scenario_files", []):
        data = _read_json(run_dir / entry["copy"], "saved scenario file")
        for item in data.get("scenarios", []):
            definitions[item["id"]] = (item, entry["path"])
    return definitions


def _apply_scenario_files(definitions, files, notes):
    for path in files:
        data = _read_json(path, "scenario file")
        items = data.get("scenarios") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ReplayError("%s: scenarios must be a list" % Path(path).name)
        for item in items:
            scenario_id = item.get("id") if isinstance(item, dict) else None
            if scenario_id not in definitions:
                notes.append("%s: scenario %r was not part of the original run and is ignored" % (Path(path).name, scenario_id))
                continue
            original = definitions[scenario_id][0]
            changed = [f for f in CONVERSATION_FIELDS if item.get(f) != original.get(f)]
            if changed:
                raise ReplayError("Scenario %r changes %s. Changing conversation inputs requires a new target run; "
                                  "replay can only change expectations." % (scenario_id, ", ".join(changed)))
            definitions[scenario_id] = (dict(original, expect=copy.deepcopy(item.get("expect"))), definitions[scenario_id][1])


def _apply_sets(definitions, sets):
    """Apply ``<scenario_id>.<expect path>=<json>``; ``*`` targets every scenario that has the field."""
    for spec in sets:
        target, _, raw = spec.partition("=")
        if not _:
            raise ReplayError("--set needs <scenario_id>.<expectation>=<value>, got %r" % spec)
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw  # a bare word is taken as a string
        if target.startswith("*."):
            ids, path = list(definitions), target[2:]
        else:
            ids = [i for i in definitions if target.startswith(i + ".")]
            if not ids:
                raise ReplayError("--set %r does not name a scenario from the original run" % spec)
            ids = [max(ids, key=len)]
            path = target[len(ids[0]) + 1:]
        keys = path.split(".")
        applied = False
        for scenario_id in ids:
            definition, source = definitions[scenario_id]
            if target.startswith("*.") and keys[0] not in (definition.get("expect") or {}):
                continue  # never invent a check a scenario did not have
            definition = copy.deepcopy(definition)
            node = definition.setdefault("expect", {})
            for key in keys[:-1]:
                node = node.setdefault(key, {})
                if not isinstance(node, dict):
                    raise ReplayError("--set %r: %r is not an object" % (spec, key))
            node[keys[-1]] = value
            definitions[scenario_id] = (definition, source)
            applied = True
        if not applied:
            raise ReplayError("--set %r matched no scenario" % spec)


def _outcome(attempt):
    """The parts of a graded attempt that must be reproduced."""
    return {"verdict": attempt["verdict"],
            "reasons": sorted([r["code"], r["verdict"]] for r in attempt["reasons"]),
            "checks": sorted([c["check"], str(c["verdict"])] for c in attempt["checks"])}


def replay_run(run_dir, replays_dir=None, scenario_files=(), sets=()):
    """Regrade ``run_dir`` offline and return the new replay directory."""
    started = time.monotonic()
    run_dir = Path(run_dir)
    manifest = _read_json(run_dir / "manifest.json", "run manifest")
    if manifest.get("kind") == "replay":
        raise ReplayError("%s is itself a replay; replay the original run instead." % run_dir.name)
    original = _read_json(run_dir / "results.json", "run results")
    definitions = _load_definitions(run_dir, manifest)
    used_originally = copy.deepcopy(definitions)
    notes = []
    _apply_scenario_files(definitions, scenario_files, notes)
    _apply_sets(definitions, sets)
    problems, changed = [], []
    for scenario_id, (definition, _) in definitions.items():
        before = used_originally[scenario_id][0].get("expect")
        if definition.get("expect") != before:
            validate_expect(definition.get("expect"), scenario_id, problems, definition.get("modality"),
                            [t.get("type") for t in definition.get("turns", [])])
            changed.append({"scenario_id": scenario_id, "original_expect": before, "replay_expect": definition.get("expect")})
    if problems:
        raise ReplayError("Changed expectations are not valid:\n  - " + "\n  - ".join(problems))

    replay_id = "replay-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    replays_dir = Path(replays_dir) if replays_dir else run_dir.parent.parent / "replays"
    replay_dir = replays_dir / replay_id
    replays_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir()  # never overwrite an earlier replay
    back = _relative(run_dir, replay_dir)

    policy = manifest.get("policy") or {}
    attempts, differences, artifact_problems = [], [], []
    for old in original["attempts"]:
        evidence_path = run_dir / old["evidence"]
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            evidence = {"evidence_missing": True, "evidence_error": type(exc).__name__}
        for artifact in old.get("artifacts", []):
            recorded = next((t["audio_artifact"]["sha256"] for t in evidence.get("turns", [])
                             if t.get("audio_artifact") and artifact.endswith("/" + t["audio_artifact"]["path"])), None)
            file = run_dir / artifact
            if not file.is_file():
                artifact_problems.append({"attempt_id": old["attempt_id"], "artifact": artifact, "problem": "missing"})
            elif recorded and sha256_file(file) != recorded:
                artifact_problems.append({"attempt_id": old["attempt_id"], "artifact": artifact, "problem": "sha256 differs from evidence"})
        definition, source = definitions.get(old["scenario_id"], ({"expect": old.get("expect"), "modality": old.get("modality"),
                                                                    "turn_timeout_ms": old.get("turn_timeout_ms")}, old.get("source")))
        new = build_attempt_result(old, definition, source, evidence, policy, "%s/%s" % (back, old["evidence"]),
                                   ["%s/%s" % (back, a) for a in old.get("artifacts", [])])
        new["original_verdict"] = old["verdict"]
        attempts.append(new)
        if _outcome(new) != _outcome(old):
            before, after = _outcome(old), _outcome(new)
            differences.append({"attempt_id": old["attempt_id"], "scenario_id": old["scenario_id"], "variant": old["variant"],
                                "repeat": old["repeat"], "original_verdict": old["verdict"], "replay_verdict": new["verdict"],
                                "original_reasons": [c for c, _ in before["reasons"]], "replay_reasons": [c for c, _ in after["reasons"]],
                                "changed_checks": sorted({c[0] for c in before["checks"] + after["checks"]
                                                          if c not in before["checks"] or c not in after["checks"]})})

    results = {"results_schema": 1, "run_id": replay_id, "kind": "replay", "original_run_id": manifest["run_id"],
               "verdict_precedence": list(PRECEDENCE), "attempts": attempts}
    replay_manifest = {
        "manifest_schema": 1, "kind": "replay", "replay_id": replay_id, "run_id": replay_id,
        "original_run_id": manifest["run_id"], "original_run_path": back,
        "started_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "evaluator": evaluator_identity(),
        "target_contacted": False,
        "target_note": "Replay reads saved files only. It has no HTTP client and sends no requests.",
        "expectations": {
            "unchanged": not changed,
            "override_files": [{"file": Path(p).name, "sha256": sha256_file(p)} for p in scenario_files],
            "set_overrides": list(sets), "changed": changed, "notes": notes},
        "reproduction": {
            "identical_to_original": not differences,
            "meaning": "verdict, reason codes and every check outcome per attempt, compared with the original results.json",
            "attempts_compared": len(attempts), "differences": differences},
        "artifact_problems": artifact_problems,
        "original_manifest": manifest,
        "artifacts": {"results": "results.json", "report": "report.md", "comparison": None, "comparison_report": None},
    }
    variants = (manifest.get("target") or {}).get("variants") or []
    if len(variants) >= 2:
        comparison = build_comparison(results, variants[0], variants[1])
        _write_json(replay_dir / "comparison.json", comparison)
        (replay_dir / "comparison.md").write_text(render_comparison(comparison), encoding="utf-8")
        replay_manifest["artifacts"].update(comparison="comparison.json", comparison_report="comparison.md")
    _write_json(replay_dir / "results.json", results)
    replay_manifest["replay_duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    replay_manifest["timing_note"] = ("replay_duration_ms is how long this offline regrade took. Agent and runner timings "
                                      "in the results are the original run's and were not re-measured.")
    _write_json(replay_dir / "manifest.json", replay_manifest)
    (replay_dir / "report.md").write_text(build_report(replay_manifest, results), encoding="utf-8")
    return replay_dir
