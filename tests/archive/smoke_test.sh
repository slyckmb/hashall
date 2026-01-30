#!/bin/bash
# tests/smoke_test.sh – End-to-end functional smoke test

set -e

echo "🧪 Smoke Test: Init sandbox..."

# Preflight validation (import, CLI, symbol sanity)
bash tests/preflight_check.sh

echo "🧹 Cleaning sandbox..."
rm -rf sandbox/

echo "📁 Generating dummy test files..."
bash tests/generate_sandbox.sh

echo "📦 Running scan..."
python3 filehash_tool.py scan sandbox/test_root --mode verify --workers 2

echo "📤 Exporting..."
python3 filehash_tool.py export sandbox/test_root

echo "🔍 Validating JSON schema..."
python3 tests/smoke/validate_json.py

echo "✅ Smoke test passed."
