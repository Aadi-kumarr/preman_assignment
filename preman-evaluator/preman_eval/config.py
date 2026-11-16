"""Run configuration. Paths are relative and POSIX-style so configs are portable."""
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

DEFAULT_CONFIRMATION_PHRASES = ("yes", "confirm", "yes confirm", "yes, confirm")


class ConfigError(Exception):
    pass


def _is_pos_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def check_relative_path(value, where):
    """Return a problem string if ``value`` is not a portable relative path."""
    if not isinstance(value, str) or not value.strip():
        return "%s: must be a nonempty string path" % where
    if "\\" in value:
        return "%s: use forward slashes, not backslashes (%r)" % (where, value)
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive:
        return "%s: must be a relative path, not absolute (%r)" % (where, value)
    return None


@dataclass
class RunConfig:
    root: Path  # directory that relative paths are resolved against; never written to outputs
    base_url: str = "http://127.0.0.1:8765"
    starter_dir: str = "../preman-agent-evaluation"
    scenario_files: list = field(default_factory=lambda: [
        "../preman-agent-evaluation/scenarios.json", "scenarios_added.json"])
    variants: list = field(default_factory=lambda: ["baseline", "faulty"])
    repeats: int = 1
    concurrency: int = 1
    harness_timeout_ms: int = 5000
    runs_dir: object = "runs"
    confirmation_phrases: list = field(default_factory=lambda: list(DEFAULT_CONFIRMATION_PHRASES))
    audio_manifest: str = "fixtures/audio_manifest.json"  # relative to starter_dir
    expected_starter_sha256: object = None  # when set, a run refuses to start if the starter differs

    def resolve(self, relative):
        return Path(self.root) / relative

    def validate(self):
        problems = []
        if not isinstance(self.base_url, str) or not self.base_url.startswith(("http://", "https://")):
            problems.append("base_url: must be an http(s) URL")
        if not isinstance(self.variants, list) or not self.variants or not all(
                isinstance(v, str) and v.strip() for v in self.variants):
            problems.append("variants: must be a nonempty list of strings")
        elif len(set(self.variants)) != len(self.variants):
            problems.append("variants: must not contain duplicates")
        for name in ("repeats", "concurrency", "harness_timeout_ms"):
            if not _is_pos_int(getattr(self, name)):
                problems.append("%s: must be a positive integer" % name)
        if not isinstance(self.scenario_files, list) or not self.scenario_files:
            problems.append("scenario_files: must be a nonempty list of paths")
        if not isinstance(self.confirmation_phrases, list) or not self.confirmation_phrases or not all(
                isinstance(p, str) and p.strip() for p in self.confirmation_phrases):
            problems.append("confirmation_phrases: must be a nonempty list of strings")
        if problems:
            raise ConfigError("Invalid run configuration:\n  - " + "\n  - ".join(problems))
        return self

    def public(self):
        """The configuration as recorded in a manifest (no machine-specific paths)."""
        return {
            "base_url": self.base_url,
            "starter_dir": str(self.starter_dir),
            "scenario_files": [str(p) for p in self.scenario_files],
            "variants": list(self.variants),
            "repeats": self.repeats,
            "concurrency": self.concurrency,
            "harness_timeout_ms": self.harness_timeout_ms,
            "confirmation_phrases": list(self.confirmation_phrases),
            "audio_manifest": str(self.audio_manifest),
            "expected_starter_sha256": self.expected_starter_sha256,
        }


CONFIG_KEYS = {"base_url", "starter_dir", "scenario_files", "variants", "repeats", "concurrency",
               "harness_timeout_ms", "runs_dir", "confirmation_phrases", "audio_manifest",
               "expected_starter_sha256"}


def load_config(path, overrides=None):
    """Load a JSON config file; relative paths resolve against the file's folder."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError("Cannot read config file %s: %s" % (path.name, exc.strerror or exc)) from exc
    except ValueError as exc:
        raise ConfigError("Config file %s is not valid JSON: %s" % (path.name, exc)) from exc
    if not isinstance(data, dict):
        raise ConfigError("Config file %s must contain a JSON object" % path.name)
    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        raise ConfigError("Config file %s has unknown keys: %s" % (path.name, ", ".join(unknown)))
    data.update({k: v for k, v in (overrides or {}).items() if v is not None})
    problems = []
    for key in ("starter_dir", "runs_dir", "audio_manifest"):
        if key in data:
            problems.append(check_relative_path(data[key], key))
    if isinstance(data.get("scenario_files"), list):
        for index, item in enumerate(data["scenario_files"]):
            problems.append(check_relative_path(item, "scenario_files[%d]" % index))
    problems = [p for p in problems if p]
    if problems:
        raise ConfigError("Invalid run configuration:\n  - " + "\n  - ".join(problems))
    return RunConfig(root=path.resolve().parent, **data).validate()
