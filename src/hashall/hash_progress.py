"""Shared hashing progress reporting for CLI workflows."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional


def _format_bytes(value: float | int) -> str:
    value_f = float(max(0.0, value))
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    idx = 0
    while value_f >= 1024.0 and idx < len(units) - 1:
        value_f /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value_f)} {units[idx]}"
    return f"{value_f:.1f} {units[idx]}"


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    total = int(max(0, seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes:d}m{secs:02d}s"
    return f"{secs:d}s"


def _truncate_path(path: str, limit: int = 56) -> str:
    text = str(path or "")
    if len(text) <= limit:
        return text
    p = Path(text)
    tail = p.name
    if len(tail) <= limit - 3:
        return f"...{tail[-(limit - 3):]}"
    return text[: limit - 3] + "..."


class HashProgressReporter:
    """
    Standardized hash progress renderer.

    Modes:
      - auto: full on TTY, minimal otherwise
      - minimal: start + periodic group counts + done
      - full: byte/rate/eta style progress line with throttling
    """

    def __init__(
        self,
        *,
        label: str,
        mode: str = "auto",
        emit: Optional[Callable[[str], None]] = None,
        render_interval_s: float = 1.0,
        heartbeat_interval_s: float = 5.0,
    ) -> None:
        resolved = (mode or "auto").lower()
        if resolved not in {"auto", "minimal", "full"}:
            resolved = "auto"
        if resolved == "auto":
            resolved = "full" if sys.stdout.isatty() else "minimal"
        self.mode = resolved
        self.label = label
        self._emit = emit or print
        self._render_interval_s = max(0.1, float(render_interval_s))
        self._heartbeat_interval_s = max(0.5, float(heartbeat_interval_s))

        self._lock = threading.Lock()
        self._started = False
        self._start_ts = 0.0
        self._last_render_ts = 0.0
        self._last_progress_ts = 0.0
        self._last_batch_bytes_done = -1
        self._last_group_logged = -1
        self._total_groups = 0
        self._total_bytes = 0

    def start(self, *, total_groups: int, total_bytes: int) -> None:
        with self._lock:
            self._started = True
            self._start_ts = time.monotonic()
            self._last_render_ts = self._start_ts
            self._last_progress_ts = self._start_ts
            self._last_batch_bytes_done = 0
            self._last_group_logged = 0
            self._total_groups = max(0, int(total_groups))
            self._total_bytes = max(0, int(total_bytes))
            if self.mode == "minimal":
                self._emit(
                    "   ⏳ Hashing inode groups: 0/"
                    f"{self._total_groups}"
                    + (f" total={_format_bytes(self._total_bytes)}" if self._total_bytes else "")
                )
            else:
                self._emit(
                    "   ⏳ Hashing started: groups=0/"
                    f"{self._total_groups}"
                    + (f" total={_format_bytes(self._total_bytes)}" if self._total_bytes else "")
                )

    def update(
        self,
        *,
        event: str,
        done_groups: int,
        total_groups: Optional[int] = None,
        path: str = "",
        file_bytes_done: Optional[int] = None,
        file_bytes_total: Optional[int] = None,
        batch_bytes_done: Optional[int] = None,
        batch_bytes_total: Optional[int] = None,
        force: bool = False,
    ) -> None:
        with self._lock:
            if not self._started:
                self.start(
                    total_groups=int(total_groups or 0),
                    total_bytes=int(batch_bytes_total or 0),
                )
            now = time.monotonic()
            groups_done = max(0, int(done_groups))
            groups_total = max(0, int(total_groups or self._total_groups))
            total_bytes_val = max(0, int(batch_bytes_total or self._total_bytes))
            if total_groups is not None:
                self._total_groups = groups_total
            if batch_bytes_total is not None:
                self._total_bytes = total_bytes_val

            bytes_done = max(0, int(batch_bytes_done or 0))
            if bytes_done != self._last_batch_bytes_done:
                self._last_progress_ts = now
                self._last_batch_bytes_done = bytes_done

            if self.mode == "minimal":
                if event == "done":
                    self._emit(
                        "   🔎 Hashing complete: "
                        f"{groups_done}/{groups_total} inode groups"
                        + (f" total={_format_bytes(bytes_done)}" if bytes_done else "")
                    )
                    return
                if event == "progress":
                    if groups_done != self._last_group_logged:
                        self._last_group_logged = groups_done
                        self._emit(f"   ⏳ Hashing inode groups: {groups_done}/{groups_total}")
                return

            should_render = force or event == "done"
            if not should_render and (now - self._last_render_ts) >= self._render_interval_s:
                should_render = True
            if not should_render and (now - self._last_progress_ts) >= self._heartbeat_interval_s:
                should_render = True

            if not should_render:
                return

            elapsed = max(1e-9, now - self._start_ts)
            rate_bps = bytes_done / elapsed if bytes_done > 0 else 0.0
            eta_s = None
            if total_bytes_val > 0 and rate_bps > 0.0:
                eta_s = (total_bytes_val - bytes_done) / rate_bps

            progress_bits = [f"groups={groups_done}/{groups_total}"]
            if file_bytes_total:
                progress_bits.append(
                    "file="
                    f"{_format_bytes(file_bytes_done or 0)}/{_format_bytes(file_bytes_total)}"
                )
            if total_bytes_val:
                progress_bits.append(
                    "total="
                    f"{_format_bytes(bytes_done)}/{_format_bytes(total_bytes_val)}"
                )
            if rate_bps > 0:
                progress_bits.append(f"rate={_format_bytes(rate_bps)}/s")
            progress_bits.append(f"eta={_format_duration(eta_s)}")
            progress_bits.append(f"elapsed={_format_duration(elapsed)}")
            if path:
                progress_bits.append(f"path={_truncate_path(path)}")

            prefix = "   🔎 Hashing complete:" if event == "done" else "   ⏳ Hashing:"
            self._emit(prefix + " " + " ".join(progress_bits))
            self._last_render_ts = now

    def finish(
        self,
        *,
        done_groups: int,
        total_groups: Optional[int] = None,
        batch_bytes_done: Optional[int] = None,
        batch_bytes_total: Optional[int] = None,
    ) -> None:
        self.update(
            event="done",
            done_groups=done_groups,
            total_groups=total_groups,
            batch_bytes_done=batch_bytes_done,
            batch_bytes_total=batch_bytes_total,
            force=True,
        )

    def status_desc(self, *, done_groups: int, total_groups: int, path: str = "") -> str:
        label = _truncate_path(path or self.label, limit=40)
        return f"hashing {done_groups}/{total_groups} inode-groups: {label}"
