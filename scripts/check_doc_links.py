#!/usr/bin/env python3
"""Check local markdown links in README/docs for broken paths."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAT = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def iter_docs(include_archive: bool = False) -> list[Path]:
    files: list[Path] = []
    for p in (ROOT / "docs").rglob("*"):
        if p.is_file() and p.suffix.lower() in {".md", ".txt"}:
            if not include_archive and "archive" in p.relative_to(ROOT / "docs").parts:
                continue
            files.append(p)
    for p in (ROOT / "README.md", ROOT / "TODO.md"):
        if p.exists():
            files.append(p)
    return sorted(files)


def main() -> int:
    include_archive = "--include-archive" in sys.argv[1:]
    missing: list[tuple[Path, str, Path]] = []
    for f in iter_docs(include_archive=include_archive):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in PAT.finditer(text):
            link = m.group(1).strip()
            if not link or link.startswith("#") or "://" in link or link.startswith("mailto:"):
                continue
            link = link.split("#", 1)[0]
            if not link:
                continue
            target = (f.parent / link).resolve() if not link.startswith("/") else Path(link)
            if not target.exists():
                missing.append((f, link, target))

    if missing:
        print(f"BROKEN_LINKS={len(missing)}")
        for f, link, target in missing:
            print(f"{f.relative_to(ROOT)}\t{link}\t{target}")
        return 1

    print("BROKEN_LINKS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
