# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/usr/bin/env bash
set -euo pipefail

echo "🧼 Full Repo Audit Starting..."

echo "1️⃣ Uninstall & reinstall in editable mode"
pip uninstall -y hashall || true
pip install -e .

echo "2️⃣ CLI entrypoint checks"
hashall --help
hashall scan --help
hashall export --help
hashall verify-trees --help

echo "3️⃣ Python import smoke tests"
for mod in cli scan export model diff verify verify_trees; do
  python - <<EOF
import hashall
from hashall import $mod
print("✅ hashall.$mod imported successfully")
EOF
done

echo "4️⃣ Command-path validations"
python - <<'EOF'
from hashall.cli import cli
# builds the click CLI tree
cli(["--help"])
cli(["scan","--help"])
cli(["export","--help"])
cli(["verify-trees","--help"])
print("✅ CLI commands properly wired")
EOF

echo "5️⃣ Basic scan→export→verify roundtrip"
TMPDB=$(mktemp /tmp/hashall_test_db_XXXX.db)
TMPJSON=$(mktemp /tmp/hashall_test_out_XXXX.json)
echo "  • Using DB: $TMPDB, JSON: $TMPJSON"
hashall scan . --db "$TMPDB"
hashall export . --db "$TMPDB" --out "$TMPJSON"
hashall verify-trees . . --db "$TMPDB"

echo "6️⃣ pytest dry-run"
pytest --maxfail=1 --disable-warnings -q

echo "7️⃣ Orphan source checks"
echo "📦 Looking for Python files lacking symbols..."
find src/hashall -name "*.py" -print0 | xargs -0 grep -LE "^\s*(def |class |import )" || true

echo "✅ Full Audit Passed!"
