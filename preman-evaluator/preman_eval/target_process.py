"""Start the supplied target as a child process without writing into its folder."""
import contextlib
import os
import re
import subprocess
import sys
from pathlib import Path


class TargetStartError(Exception):
    pass


@contextlib.contextmanager
def launched_target(starter_dir, port=0, slow_ms=None):
    """Run ``target_server.py`` from ``starter_dir`` and yield its base URL.

    Port 0 asks the OS for a free port. Bytecode writing is disabled so no
    ``__pycache__`` appears in the starter folder.
    """
    starter_dir = Path(starter_dir)
    if not (starter_dir / "target_server.py").is_file():
        raise TargetStartError("target_server.py not found in the starter directory")
    command = [sys.executable, "-B", "target_server.py", "--port", str(port)]
    if slow_ms is not None:
        command += ["--slow-ms", str(slow_ms)]
    process = subprocess.Popen(command, cwd=starter_dir, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    try:
        line = process.stdout.readline()  # the target prints its address once it is listening
        match = re.search(r"http://\S+", line)
        if not match:
            raise TargetStartError("target did not start (is the port already in use?)")
        yield match.group(0)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()
