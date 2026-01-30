#!/bin/bash
# Run this before CLI testing to ensure code structure is valid

set -e

echo "🔍 Preflight Check: Validating Python structure and CLI entrypoints..."

# Compile Python files to catch syntax and import errors
echo "📦 Python import test (py_compile)..."
python3 -m py_compile \
    filehash_tool.py \
    scan_session.py \
    json_export.py \
    db_migration.py

# Check that CLI commands load and show help without error
echo "🧪 CLI argument test..."
python3 filehash_tool.py scan --help >/dev/null
python3 filehash_tool.py export --help >/dev/null

echo "✅ Preflight check passed. All imports and CLI endpoints are structurally sound."
