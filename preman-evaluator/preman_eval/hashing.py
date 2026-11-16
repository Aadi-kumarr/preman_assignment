"""Content hashes used for reproducibility: files, folder trees, evaluator source."""
import hashlib
import subprocess
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
EVALUATOR_ROOT = PACKAGE_DIR.parent


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root, suffix=None):
    """Hash every file under ``root`` (optionally only those with ``suffix``).

    The digest covers each file's POSIX-style relative path and its content
    hash, in sorted path order, so it is identical on every platform and
    changes if any file is added, removed, renamed, or edited.
    Returns ``(hex_digest, file_count)``.
    """
    root = Path(root)
    entries = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if suffix is not None and (path.suffix != suffix or "__pycache__" in path.parts):
            continue
        entries.append((path.relative_to(root).as_posix(), path))
    digest = hashlib.sha256()
    for rel, path in sorted(entries):
        digest.update(rel.encode("utf-8") + b"\0" + sha256_file(path).encode("ascii") + b"\n")
    return digest.hexdigest(), len(entries)


def _git(*args):
    try:
        done = subprocess.run(["git", *args], cwd=EVALUATOR_ROOT, capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def evaluator_identity():
    """Git commit of the evaluator, or "uncommitted" plus a source hash."""
    source_hash, source_files = sha256_tree(PACKAGE_DIR, suffix=".py")
    head = _git("rev-parse", "HEAD")
    # Only source changes make the commit unrepresentative; saved runs do not.
    status = _git("status", "--porcelain", "--", "preman_eval", "tests", "scenarios_added.json", "eval_config.json")
    dirty = None if status is None else bool(status)
    committed = head is not None and dirty is False
    return {
        "git_commit": head if committed else "uncommitted",
        "git_head": head,
        "git_dirty": dirty,
        "source_sha256": source_hash,
        "source_files_hashed": source_files,
        "source_hash_scope": "preman_eval/**/*.py",
    }
