"""Scenario loading and validation. Scenarios are data; nothing here knows case names."""
import json
import wave
from dataclasses import dataclass
from pathlib import Path

from .config import check_relative_path

SCHEMA_VERSION = 1
MODALITIES = ("chat", "audio")
# Fields allowed on each turn type.
TURN_FIELDS = {"text": {"type", "text"}, "audio": {"type", "path"}, "interrupt": {"type"}}
# Turn types each modality may contain (evaluator decision, see README).
MODALITY_TURNS = {"chat": {"text"}, "audio": {"audio", "interrupt"}}
SCENARIO_FIELDS = {"id", "fixture", "modality", "turns", "expect", "turn_timeout_ms"}
BOOKING_FIELDS = {"count", "customer_id", "starts_at"}


class ScenarioValidationError(Exception):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("Scenario validation failed (%d problem%s):\n  - %s" % (
            len(self.problems), "" if len(self.problems) == 1 else "s", "\n  - ".join(self.problems)))


@dataclass(frozen=True)
class Scenario:
    id: str
    fixture: str
    modality: str
    turn_timeout_ms: int
    turns: tuple
    expect: dict
    source: str       # label of the file it came from (relative, as configured)
    definition: dict  # the untouched definition, kept with every graded result


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _expect_booking(value, where, problems):
    if not isinstance(value, dict):
        return problems.append("%s: must be an object" % where)
    for key in sorted(set(value) - BOOKING_FIELDS):
        problems.append("%s.%s: unsupported booking field" % (where, key))
    if "count" not in value:
        problems.append("%s.count: is required" % where)
    elif not _is_int(value["count"]) or value["count"] < 0:
        problems.append("%s.count: must be a non-negative integer" % where)
    for key in ("customer_id", "starts_at"):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            problems.append("%s.%s: must be a nonempty string" % (where, key))


def _expect_address(value, where, problems):
    if not isinstance(value, str) or not value.strip():
        problems.append("%s: must be a nonempty string" % where)


def _expect_bool(value, where, problems):
    if not isinstance(value, bool):
        problems.append("%s: must be true or false" % where)


def _expect_limit_ms(value, where, problems):
    if not _is_number(value) or value <= 0:
        problems.append("%s: must be a positive number of milliseconds" % where)


# Every supported expectation type and its validator. Anything else is an error.
EXPECT_VALIDATORS = {
    "booking": _expect_booking,
    "address": _expect_address,
    "no_write_without_confirmation": _expect_bool,
    "max_first_audio_playback_ms": _expect_limit_ms,
    "max_interruption_stop_ms": _expect_limit_ms,
}
AUDIO_LIMITS = ("max_first_audio_playback_ms", "max_interruption_stop_ms")
# Changing any of these changes the conversation, so it needs a new target run (not a replay).
CONVERSATION_FIELDS = ("fixture", "modality", "turns", "turn_timeout_ms")


def _validate_turn(turn, where, modality, audio_root, problems):
    if not isinstance(turn, dict):
        return problems.append("%s: must be an object" % where)
    kind = turn.get("type")
    if not isinstance(kind, str) or kind not in TURN_FIELDS:
        return problems.append("%s.type: must be one of %s (got %r)" % (where, ", ".join(sorted(TURN_FIELDS)), kind))
    for key in sorted(set(turn) - TURN_FIELDS[kind]):
        problems.append("%s.%s: unexpected field for a %s turn" % (where, key, kind))
    if modality in MODALITY_TURNS and kind not in MODALITY_TURNS[modality]:
        problems.append("%s.type: a %s scenario cannot contain a %s turn" % (where, modality, kind))
    if kind == "text" and (not isinstance(turn.get("text"), str) or not turn["text"].strip()):
        problems.append("%s.text: must be a nonempty string" % where)
    if kind == "audio":
        path = turn.get("path")
        problem = check_relative_path(path, where + ".path")
        if problem:
            return problems.append(problem)
        resolved = (audio_root / path).resolve()
        if not resolved.is_relative_to(audio_root.resolve()):
            problems.append("%s.path: must stay inside the starter directory (%r)" % (where, path))
        elif not resolved.is_file():
            problems.append("%s.path: audio file does not exist (%r)" % (where, path))
        else:
            try:
                with wave.open(str(resolved), "rb") as audio:
                    if audio.getnframes() <= 0:
                        raise wave.Error("no audio frames")
            except (wave.Error, EOFError, OSError) as exc:
                problems.append("%s.path: not a readable PCM WAV file (%r: %s)" % (where, path, exc))


def validate_expect(expect, where, problems, modality=None, turn_kinds=()):
    """Validate an ``expect`` block; used at load time and for replay overrides."""
    if not isinstance(expect, dict):
        return problems.append("%s.expect: must be an object" % where)
    for key, value in expect.items():
        validator = EXPECT_VALIDATORS.get(key)
        if validator is None:
            problems.append("%s.expect.%s: unsupported expectation type (supported: %s)" % (
                where, key, ", ".join(sorted(EXPECT_VALIDATORS))))
            continue
        validator(value, "%s.expect.%s" % (where, key), problems)
        # An audio limit with nothing to measure could never be shown to hold.
        if key in AUDIO_LIMITS and modality is not None and modality != "audio":
            problems.append("%s.expect.%s: audio limits need an audio scenario" % (where, key))
        if key == "max_interruption_stop_ms" and modality == "audio" and "interrupt" not in turn_kinds:
            problems.append("%s.expect.%s: needs at least one interrupt turn to measure" % (where, key))


def _validate_scenario(item, where, audio_root, problems):
    if not isinstance(item, dict):
        return problems.append("%s: must be an object" % where)
    for key in sorted(set(item) - SCENARIO_FIELDS):
        problems.append("%s.%s: unknown scenario field" % (where, key))
    for key in sorted(SCENARIO_FIELDS - set(item)):
        problems.append("%s.%s: is required" % (where, key))
    for key in ("id", "fixture"):
        if key in item and (not isinstance(item[key], str) or not item[key].strip()):
            problems.append("%s.%s: must be a nonempty string" % (where, key))
    modality = item.get("modality")
    if "modality" in item and (not isinstance(modality, str) or modality not in MODALITIES):
        problems.append("%s.modality: must be chat or audio (got %r)" % (where, modality))
        modality = None
    if "turn_timeout_ms" in item and (not _is_int(item["turn_timeout_ms"]) or item["turn_timeout_ms"] <= 0):
        problems.append("%s.turn_timeout_ms: must be a positive integer (got %r)" % (where, item["turn_timeout_ms"]))
    if "turns" in item:
        turns = item["turns"]
        if not isinstance(turns, list) or not turns:
            problems.append("%s.turns: must be a nonempty list" % where)
        else:
            for index, turn in enumerate(turns):
                _validate_turn(turn, "%s.turns[%d]" % (where, index), modality, audio_root, problems)
            kinds = [t.get("type") for t in turns if isinstance(t, dict)]
            if kinds and kinds[0] == "interrupt":
                problems.append("%s.turns[0]: an interrupt needs a preceding turn" % where)
            if modality == "audio" and "audio" not in kinds:
                problems.append("%s.turns: an audio scenario needs at least one audio turn" % where)
    if "expect" in item:
        turns = item.get("turns") if isinstance(item.get("turns"), list) else []
        validate_expect(item["expect"], where, problems, modality,
                        [t.get("type") for t in turns if isinstance(t, dict)])


def load_scenarios(files, audio_root):
    """Load and validate scenario files.

    ``files`` is a list of ``(label, path)``; ``label`` is the relative name used
    in messages and outputs. Audio paths resolve against ``audio_root`` (the
    starter directory). Raises ScenarioValidationError listing every problem.
    """
    audio_root = Path(audio_root)
    problems, scenarios, seen = [], [], {}
    for label, path in files:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            problems.append("%s: cannot read file (%s)" % (label, exc.strerror or exc))
            continue
        except ValueError as exc:
            problems.append("%s: not valid JSON (%s)" % (label, exc))
            continue
        if not isinstance(data, dict):
            problems.append("%s: top level must be an object" % label)
            continue
        for key in sorted(set(data) - {"schema_version", "scenarios"}):
            problems.append("%s: unknown top-level field %r" % (label, key))
        if data.get("schema_version") != SCHEMA_VERSION or not _is_int(data.get("schema_version")):
            problems.append("%s: schema_version must be %d (got %r)" % (label, SCHEMA_VERSION, data.get("schema_version")))
        items = data.get("scenarios")
        if not isinstance(items, list) or not items:
            problems.append("%s: scenarios must be a nonempty list" % label)
            continue
        for index, item in enumerate(items):
            where = "%s: scenarios[%d]" % (label, index)
            before = len(problems)
            _validate_scenario(item, where, audio_root, problems)
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
                if item["id"] in seen:
                    problems.append("%s.id: duplicate id %r (first defined in %s)" % (where, item["id"], seen[item["id"]]))
                else:
                    seen[item["id"]] = where
            if len(problems) == before:
                scenarios.append(Scenario(
                    id=item["id"], fixture=item["fixture"], modality=item["modality"],
                    turn_timeout_ms=item["turn_timeout_ms"], turns=tuple(item["turns"]),
                    expect=item["expect"], source=label, definition=item))
    if problems:
        raise ScenarioValidationError(problems)
    return scenarios
