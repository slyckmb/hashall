# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/bin/bash
set -euo pipefail
rm -f test.db /tmp/foo.json
rm -rf ~/.hashall

echo "🔄 Rebuilding..."
pip install -e .

echo "📦 Init schema..."
python -c 'from hashall.model import init_db_schema, connect_db; init_db_schema(connect_db("test.db"))'

echo "🚀 CLI smoke check..."
hashall scan ~/Downloads --db test.db
hashall export --db test.db --out /tmp/foo.json
