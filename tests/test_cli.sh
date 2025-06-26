# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/bin/bash
set -e

echo "🔁 Uninstalling previous hashall..."
pip uninstall -y hashall || true

echo "📦 Reinstalling in editable mode..."
pip install -e .

echo "✅ Verifying CLI entrypoint..."
hashall --help

echo "📂 Testing scan..."
hashall scan ~/Downloads --db /tmp/test_hashall.sqlite3

echo "📤 Testing export..."
hashall export --db /tmp/test_hashall.sqlite3 --out /tmp/test_export.json

echo "🔍 Testing verify-trees..."
hashall verify-trees ~/Downloads ~/Downloads --db /tmp/test_hashall.sqlite3 --dry-run

echo "✅ All commands ran successfully!"
