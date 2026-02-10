"""Progress display utilities for long-running operations."""

import shutil
import sys
import time
import unicodedata

from tqdm import tqdm


def _char_width(ch: str) -> int:
    """Calculate display width of a single character (handles wide chars)."""
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F", "A"):
        return 2
    return 1


def _display_width(text: str) -> int:
    """Calculate total display width of text (sum of char widths)."""
    return sum(_char_width(ch) for ch in text)


def _slice_by_width(text: str, max_width: int, *, from_end: bool = False) -> str:
    """Slice text to fit within max_width display columns."""
    if max_width <= 0:
        return ""
    if not from_end:
        width = 0
        out = []
        for ch in text:
            ch_w = _char_width(ch)
            if width + ch_w > max_width:
                break
            out.append(ch)
            width += ch_w
        return "".join(out)
    width = 0
    out = []
    for ch in reversed(text):
        ch_w = _char_width(ch)
        if width + ch_w > max_width:
            break
        out.append(ch)
        width += ch_w
    return "".join(reversed(out))


def _truncate_middle(text: str, max_width: int) -> str:
    """Truncate text to max_width, showing head...tail if too long."""
    if max_width <= 0 or _display_width(text) <= max_width:
        return text
    if max_width <= 3:
        return _slice_by_width(text, max_width)
    head = max_width // 2 - 1
    tail = max_width - head - 3
    return f"{_slice_by_width(text, head)}...{_slice_by_width(text, tail, from_end=True)}"


def _pad_to_width(text: str, max_width: int) -> str:
    """Pad text with spaces to reach max_width display columns."""
    pad = max_width - _display_width(text)
    if pad > 0:
        return text + (" " * pad)
    return text


class TwoLineProgress:
    """Two-line progress display: status line + tqdm progress bar.

    Example:
        with TwoLineProgress(total=100, prefix="Processing", unit="items") as progress:
            for item in items:
                progress.update(desc=str(item), advance=1)
    """

    def __init__(self, total: int, prefix: str = "Processing", unit: str = "items", enabled: bool = None):
        """Initialize progress display.

        Args:
            total: Total number of items to process
            prefix: Label for progress bar (e.g., "📦 Scanning")
            unit: Unit name (e.g., "files", "torrents")
            enabled: Force enable/disable. If None, auto-detects TTY.
        """
        if enabled is None:
            enabled = sys.stdout.isatty()
        self.enabled = enabled
        self.file = sys.stdout if self.enabled else None
        self.total = total
        self.prefix = prefix
        self.unit = unit
        self.start = time.monotonic()
        self.n = 0
        self.desc = ""
        if self.enabled:
            self.file.write("\r\x1b[2K")
            print("", file=self.file, flush=True)
            print("", file=self.file, flush=True)

    def _width(self) -> int:
        """Get terminal width."""
        try:
            width = shutil.get_terminal_size((120, 20)).columns
        except Exception:
            width = 120
        return max(10, width - 2)

    def _progress_line(self, width: int) -> str:
        """Build tqdm-formatted progress bar line."""
        elapsed = max(time.monotonic() - self.start, 1e-9)
        line = tqdm.format_meter(
            self.n,
            self.total,
            elapsed,
            ncols=width,
            prefix=self.prefix,
            unit=self.unit,
        )
        return _pad_to_width(_truncate_middle(line, width), width)

    def update(self, *, desc: str | None = None, advance: int = 0) -> None:
        """Update progress display.

        Args:
            desc: Current item description (shown on line 1)
            advance: Number of items completed (increment counter)
        """
        if not self.enabled:
            return
        if desc is not None:
            self.desc = desc.replace("\n", " ")
        if advance:
            self.n += advance
        width = self._width()
        status_line = _pad_to_width(_truncate_middle(self.desc, width), width)
        bar_line = self._progress_line(width)
        self.file.write("\x1b[2A\r\x1b[2K" + status_line)
        self.file.write("\x1b[1B\r\x1b[2K" + bar_line)
        self.file.write("\x1b[1B\r")
        self.file.flush()

    def close(self) -> None:
        """Close progress display and clear lines."""
        if not self.enabled:
            return
        self.file.write("\x1b[2A\r\x1b[2K\x1b[1B\r")
        self.file.flush()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
