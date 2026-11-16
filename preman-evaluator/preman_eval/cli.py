"""Command line: validate, run, compare, replay (offline regrade), report, observe."""
import argparse
import contextlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .compare import build_comparison, compare_runs, render_comparison, render_run_equivalence
from .config import ConfigError, load_config
from .hashing import sha256_tree
from .replay import ReplayError, replay_run
from .report import build_observed_table, build_report, load_run
from .runner import RunError, run_suite, split_runnable, write_json
from .scenarios import ScenarioValidationError, load_scenarios
from .target_process import TargetStartError, launched_target

VERDICTS = ("PASS", "FAIL", "ERROR", "INCONCLUSIVE")


def _show(path):
    """A path for display: relative to the working directory, POSIX separators."""
    try:
        return Path(os.path.relpath(path)).as_posix()
    except ValueError:
        return Path(path).name


def _load(args):
    overrides = {"base_url": getattr(args, "base_url", None), "concurrency": getattr(args, "concurrency", None),
                 "repeats": getattr(args, "repeats", None),
                 "variants": args.variants.split(",") if getattr(args, "variants", None) else None}
    cfg = load_config(args.config, overrides)
    files = [(str(label), cfg.resolve(label)) for label in dict.fromkeys(cfg.scenario_files)]
    return cfg, load_scenarios(files, cfg.resolve(cfg.starter_dir))


def _print_counts(manifest, results):
    base = manifest.get("original_manifest", manifest)
    tally = Counter((a["variant"], a["verdict"]) for a in results["attempts"])
    for variant in base["target"]["variants"]:
        total = sum(n for (v, _), n in tally.items() if v == variant)
        print("%-10s %s" % (variant, "  ".join("%s %d/%d" % (verdict, tally[(variant, verdict)], total) for verdict in VERDICTS)))


def cmd_validate(args):
    cfg, scenarios = _load(args)
    for scenario in scenarios:
        print("ok  %-28s %-5s %d step(s)  expect: %s  [%s]" % (
            scenario.id, scenario.modality, len(scenario.turns), ", ".join(scenario.expect) or "-", scenario.source))
    print("%d scenario(s) valid." % len(scenarios))
    return 0


def cmd_run(args):
    cfg, scenarios = _load(args)
    if args.scenario:
        unknown = sorted(set(args.scenario) - {s.id for s in scenarios})
        if unknown:
            raise ConfigError("Unknown scenario id(s): %s" % ", ".join(unknown))
        scenarios = [s for s in scenarios if s.id in args.scenario]
    runnable, skipped = split_runnable(scenarios)
    if not runnable:
        raise ConfigError("No runnable scenarios selected.")
    with contextlib.ExitStack() as stack:
        if args.launch_target:
            cfg.base_url = stack.enter_context(launched_target(cfg.resolve(cfg.starter_dir)))
        run_dir = run_suite(cfg, runnable, skipped)
    manifest, results = load_run(run_dir)
    counts = manifest["counts"]
    print("%d attempts = %d scenarios x %d variants x %d repeats, concurrency %d" % (
        counts["attempts"], counts["distinct_scenarios"], counts["variants"], counts["repeats"], manifest["concurrency"]))
    _print_counts(manifest, results)
    for item in skipped:
        print("not run: %s (%s)" % (item["scenario_id"], item["reason"]))
    print("Run saved to %s" % _show(run_dir))
    print("Report: %s" % _show(run_dir / "report.md"))
    if manifest["artifacts"].get("comparison_report"):
        print("Comparison: %s" % _show(run_dir / "comparison.md"))
    if not manifest["starter"]["unchanged_during_run"]:
        print("error: the starter folder changed during the run (see manifest starter hashes)", file=sys.stderr)
        return 1
    return 0


def cmd_report(args):
    manifest, results = load_run(args.run)
    out = Path(args.out) if args.out else Path(args.run) / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(manifest, results), encoding="utf-8")
    print("Report written to %s" % _show(out))
    return 0


def cmd_compare(args):
    manifest, results = load_run(args.run)
    variants = manifest.get("original_manifest", manifest)["target"]["variants"]
    baseline = args.baseline or variants[0]
    candidate = args.candidate or next((v for v in variants if v != baseline), None)
    present = {a["variant"] for a in results["attempts"]}
    if candidate is None or baseline not in present or candidate not in present:
        raise ConfigError("This run does not contain both variants to compare (has: %s)." % ", ".join(sorted(present)))
    comparison = build_comparison(results, baseline, candidate)
    out = Path(args.out) if args.out else Path(args.run) / "comparison.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_comparison(comparison), encoding="utf-8")
    write_json(out.with_suffix(".json"), comparison)
    for name, ratio in comparison["category_counts"].items():
        print("%-24s %d/%d scenarios" % (name, ratio["count"], ratio["of"]))
    print("Policy failures: %d attempt(s)" % len(comparison["policy_failures"]))
    print("Comparison written to %s (and %s)" % (_show(out), _show(out.with_suffix(".json"))))
    return 0


def cmd_compare_runs(args):
    manifest_a, results_a = load_run(args.a)
    manifest_b, results_b = load_run(args.b)
    result = compare_runs(results_a, results_b)
    text = render_run_equivalence(result, manifest_a.get("original_manifest", manifest_a),
                                  manifest_b.get("original_manifest", manifest_b), results_a, results_b)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print("Equivalence written to %s" % _show(args.out))
    print("Equivalent: %s (%d differing attempts)" % ("yes" if result["equivalent"] else "NO", len(result["differences"])))
    return 0 if result["equivalent"] else 1


def cmd_replay(args):
    replay_dir = replay_run(args.run, args.replays_dir, args.scenarios or (), args.set or ())
    manifest, results = load_run(replay_dir)
    reproduction = manifest["reproduction"]
    _print_counts(manifest, results)
    print("Expectations: %s" % ("unchanged" if manifest["expectations"]["unchanged"]
                                else "changed for %d scenario(s)" % len(manifest["expectations"]["changed"])))
    print("Identical to original outcomes: %s (%d attempts compared, %d differ)" % (
        "yes" if reproduction["identical_to_original"] else "no", reproduction["attempts_compared"], len(reproduction["differences"])))
    for d in reproduction["differences"]:
        print("  %s: %s -> %s (%s)" % (d["attempt_id"], d["original_verdict"], d["replay_verdict"], ", ".join(d["replay_reasons"]) or "-"))
    print("Target contacted: no")
    print("Replay saved to %s" % _show(replay_dir))
    return 0


def cmd_observe(args):
    text = build_observed_table(args.run, sources=args.source or None, modality=args.modality)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print("Observed behaviour written to %s" % _show(args.out))
    else:
        sys.stdout.write(text)
    return 0


def cmd_starter_hash(args):
    cfg = load_config(args.config)
    digest, count = sha256_tree(cfg.resolve(cfg.starter_dir))
    print("%s  %s (%d files)" % (digest, cfg.starter_dir, count))
    if cfg.expected_starter_sha256:
        same = digest == cfg.expected_starter_sha256
        print("expected_starter_sha256 in config: %s" % ("MATCH" if same else "MISMATCH (%s)" % cfg.expected_starter_sha256))
        return 0 if same else 1
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m preman_eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        command = sub.add_parser(name, help=help_text)
        command.set_defaults(func=func)
        return command

    add("validate", cmd_validate, "validate the scenario files").add_argument("--config", default="eval_config.json")
    command = add("run", cmd_run, "run the suite against the target")
    command.add_argument("--config", default="eval_config.json")
    command.add_argument("--base-url", help="override the target URL")
    command.add_argument("--concurrency", type=int)
    command.add_argument("--repeats", type=int)
    command.add_argument("--variants", help="comma-separated, baseline first, e.g. baseline,faulty")
    command.add_argument("--scenario", action="append", help="run only this scenario id (repeatable)")
    command.add_argument("--launch-target", action="store_true",
                         help="start the supplied target on a free port for this run")
    command = add("compare", cmd_compare, "baseline versus candidate comparison for a saved run or replay")
    command.add_argument("--run", required=True, help="run or replay directory")
    command.add_argument("--baseline")
    command.add_argument("--candidate")
    command.add_argument("--out", help="output .md file (default: comparison.md in the run directory)")
    command = add("compare-runs", cmd_compare_runs, "check two saved runs give equivalent outcomes")
    command.add_argument("--a", required=True)
    command.add_argument("--b", required=True)
    command.add_argument("--out")
    command = add("replay", cmd_replay, "regrade a saved run offline (no target requests)")
    command.add_argument("--run", required=True, help="original run directory")
    command.add_argument("--scenarios", action="append", help="scenario file with changed expectations (repeatable)")
    command.add_argument("--set", action="append", metavar="ID.EXPECTATION=VALUE",
                         help="change one expectation, e.g. audio_booking.max_first_audio_playback_ms=500; "
                              "use *.NAME=VALUE for every scenario that already has NAME")
    command.add_argument("--replays-dir", help="where to save (default: replays/ beside the runs folder)")
    command = add("report", cmd_report, "rebuild report.md from a saved run's or replay's results")
    command.add_argument("--run", required=True, help="run or replay directory")
    command.add_argument("--out", help="output file (default: report.md in that directory)")
    command = add("observe", cmd_observe, "table of observed behaviour from saved evidence")
    command.add_argument("--run", required=True)
    command.add_argument("--out")
    command.add_argument("--source", action="append", help="only scenarios from this scenario file (as configured)")
    command.add_argument("--modality", choices=("chat", "audio"))
    add("starter-hash", cmd_starter_hash, "print the SHA-256 of the starter folder").add_argument("--config", default="eval_config.json")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, ScenarioValidationError, RunError, TargetStartError, ReplayError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print("error: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
