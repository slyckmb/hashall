"""
Logging infrastructure for rehome: tee console output to a timestamped log file
and build a structured JSON record of each run.
"""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import datetime
from pathlib import Path


class _TeeStdout:
    """Wraps sys.stdout to mirror all writes to a log file."""

    def __init__(self, fh, orig):
        self._fh = fh
        self._orig = orig

    def write(self, s: str) -> int:
        n = self._orig.write(s)
        self._fh.write(s)
        return n

    def flush(self) -> None:
        self._orig.flush()
        self._fh.flush()

    def __getattr__(self, name: str):
        return getattr(self._orig, name)


class RunLogger:
    """
    Tee console output to a log file and accumulate a structured step record.

    Usage::

        with RunLogger(path, verbose=verbose, debug=debug) as logger:
            with logger.patch_stdout():
                # all print() calls are mirrored to the log file
                ...
            logger.dump_json(json_path)

    Flags:
        verbose  -- subprocess stdout/stderr shown on console and written to log
        debug    -- implies verbose; also shows config resolution details
    """

    def __init__(self, log_path: Path, verbose: bool = False, debug: bool = False):
        self.log_path = log_path
        self.verbose = verbose or debug
        self.debug = debug
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = log_path.open("w", buffering=1, encoding="utf-8")
        self._steps: list[dict] = []
        self._started_at = datetime.now().isoformat()

    # ── stdout tee ────────────────────────────────────────────────────────────

    @contextlib.contextmanager
    def patch_stdout(self):
        """Replace sys.stdout with a tee writer for the duration of the block."""
        orig = sys.stdout
        sys.stdout = _TeeStdout(self._fh, orig)
        try:
            yield
        finally:
            sys.stdout = orig

    def write_raw(self, text: str) -> None:
        """Write directly to log file (for content not going through sys.stdout, e.g. stderr)."""
        self._fh.write(text)
        self._fh.flush()

    # ── structured step recording ─────────────────────────────────────────────

    def record_step(
        self,
        label: str,
        cmd: list[str],
        ok: bool,
        elapsed: float,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self._steps.append({
            "label": label,
            "cmd": cmd,
            "ok": ok,
            "elapsed_s": round(elapsed, 2),
            "stdout": stdout,
            "stderr": stderr,
        })

    # ── JSON output ───────────────────────────────────────────────────────────

    def dump_json(self, path: Path, extra: "dict | None" = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "started_at": self._started_at,
            "log_path": str(self.log_path),
            "steps": self._steps,
            **(extra or {}),
        }
        path.write_text(json.dumps(data, indent=2))

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "RunLogger":
        return self

    def __exit__(self, *_) -> None:
        self.close()
