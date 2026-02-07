#!/bin/bash
# Create test sandbox under sandbox/

set -e

ROOT_DIR="sandbox/test_root"

echo "🧹 Cleaning sandbox..."
rm -rf sandbox
mkdir -p "$ROOT_DIR"/{alpha,beta,gamma}

echo "📁 Generating dummy test files..."
for dir in alpha beta gamma; do
  for i in {1..5}; do
    echo "This is test file $i in $dir" > "$ROOT_DIR/$dir/file_$i.txt"
  done
done

echo "📎 Creating duplicate content for dedupe testing..."
echo "duplicate payload" > "$ROOT_DIR/alpha/dupe.txt"
cp "$ROOT_DIR/alpha/dupe.txt" "$ROOT_DIR/beta/dupe.txt"
ln "$ROOT_DIR/alpha/dupe.txt" "$ROOT_DIR/gamma/dupe_hl.txt"

RUN_VALIDATE="${HASHALL_SANDBOX_VALIDATE:-1}"
if [ "$RUN_VALIDATE" = "1" ]; then
  echo "🔍 Validating sandbox dedupe with jdupes..."
  if ! command -v jdupes >/dev/null 2>&1; then
    echo "⚠️  jdupes not found; skipping validation"
  else
    tmpdir="$(mktemp -d)"
    echo "jdupes probe" > "$tmpdir/a"
    cp "$tmpdir/a" "$tmpdir/b"
    probe_out="$(jdupes -L -1 -O -q "$tmpdir/a" "$tmpdir/b" 2>&1 || true)"
    rm -rf "$tmpdir"
    if echo "$probe_out" | grep -qi "File specs on command line disabled"; then
      echo "⚠️  jdupes build disables file arguments; skipping validation"
      echo "   Install a build that accepts file arguments to enable per-group tests"
      echo "✅ Sandbox ready at: $ROOT_DIR"
      exit 0
    fi
    DB_PATH="sandbox/catalog.db"
    PYTHONPATH="$(pwd)/src" python3 -m hashall scan "$ROOT_DIR" --db "$DB_PATH" --hash-mode full
    DEVICE_ID="$(python3 - <<PY
import os
print(os.stat("$ROOT_DIR").st_dev)
PY
)"
    PYTHONPATH="$(pwd)/src" python3 -m hashall link plan "sandbox dedupe" --db "$DB_PATH" --device "$DEVICE_ID" --no-upgrade-collisions
    PLAN_ID="$(python3 - <<PY
import sqlite3
conn = sqlite3.connect("$DB_PATH")
row = conn.execute("SELECT MAX(id) FROM link_plans").fetchone()
conn.close()
print(row[0] if row else "")
PY
)"
    PYTHONPATH="$(pwd)/src" python3 -m hashall link execute "$PLAN_ID" --db "$DB_PATH" --yes --jdupes --verify fast
    python3 - <<PY
import os
from pathlib import Path
root = Path("$ROOT_DIR")
paths = [
    root / "alpha/dupe.txt",
    root / "beta/dupe.txt",
    root / "gamma/dupe_hl.txt",
]
stats = [p.stat() for p in paths]
if len({(s.st_dev, s.st_ino) for s in stats}) != 1:
    raise SystemExit("jdupes validation failed: dupes not hardlinked")
print("✅ jdupes validation passed")
PY
  fi
fi

echo "✅ Sandbox ready at: $ROOT_DIR"
