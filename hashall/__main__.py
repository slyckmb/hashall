"""Bootstrap module for source-layout execution via `python -m hashall`."""

from __future__ import annotations

import runpy
from pathlib import Path


SRC_MAIN = Path(__file__).resolve().parents[1] / "src" / "hashall" / "__main__.py"
runpy.run_path(str(SRC_MAIN), run_name="__main__")
