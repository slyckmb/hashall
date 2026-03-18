"""Bootstrap package for source-layout execution via `python -m hashall`."""

from __future__ import annotations

from pathlib import Path


SRC_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "hashall"
__path__ = [str(SRC_PACKAGE)]
__file__ = str(SRC_PACKAGE / "__init__.py")

exec((SRC_PACKAGE / "__init__.py").read_text(encoding="utf-8"), globals())
