#!/usr/bin/env python3
"""
Validate the structure of hashall.json output.
"""

import json
import sys
from pathlib import Path

JSON_FILE = Path("sandbox/test_root/.hashall/hashall.json")

with JSON_FILE.open() as f:
    data = json.load(f)

assert "meta" in data, "Missing top-level 'meta'"
assert "files" in data, "Missing top-level 'files'"
assert isinstance(data["files"], list), "'files' must be a list"
assert len(data["files"]) > 0, "No files found in export"

# Validate schema for each file object
for i, fobj in enumerate(data["files"]):
    assert "rel_path" in fobj, f"Missing 'rel_path' in entry {i}"
    assert "size" in fobj, f"Missing 'size' in entry {i}"
    assert "mtime" in fobj, f"Missing 'mtime' in entry {i}"
    assert "sha1" in fobj, f"Missing 'sha1' in entry {i}"

print("✅ JSON format is valid.")
