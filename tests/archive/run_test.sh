#!/usr/bin/env bash
set -e

ROOT="sandbox/test_root"
DB="${DB:-$HOME/.hashall/hashall.sqlite3}"

echo "🧪 Running test scan/export"
rm -rf "$ROOT"
bash tests/generate_sandbox.sh

# Scan
python3 filehash_tool.py scan "$ROOT" --db "$DB" --mode verify --workers 2

# Export
python3 filehash_tool.py export "$ROOT" --db "$DB"

# Inspect result
jq . "$ROOT/.hashall/hashall.json" | less