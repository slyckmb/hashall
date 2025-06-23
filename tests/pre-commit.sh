#!/usr/bin/env bash
set -e

ROOT="sandbox/test_root"
DB="${DB:-$HOME/.hashall/hashall.sqlite3}"

echo "🔁 Pre-commit test scan + export..."
rm -rf "$ROOT"
mkdir -p "$(dirname "$DB")"
bash tests/generate_sandbox.sh

# Ensure old DB backup
if [ -f "$DB" ]; then
  cp "$DB" "$DB.bak.$(date +%Y%m%d%H%M%S)"
fi

# Run scan
python3 filehash_tool.py scan "$ROOT" --db "$DB" --mode verify --workers 2

# Run export
python3 filehash_tool.py export "$ROOT" --db "$DB"

# Validate JSON
jq . "$ROOT/.hashall/hashall.json" > /dev/null
echo "✅ Pre-commit check succeeded"
