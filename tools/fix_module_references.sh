# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/bin/bash

# Refactor module import paths only — keep scan_session table name
echo "🔧 Replacing Python module references (scan_session → scan, json_export → export)..."

# Fix .py source files only (excluding binary & special files)
find ./src ./tests ./scripts ./tools ./archive \
    -type f -name "*.py" \
    -exec sed -i \
    -e 's/from hashall\.scan_session/from hashall.scan/g' \
    -e 's/import scan_session/import scan/g' \
    -e 's/from scan_session/from scan/g' \
    -e 's/from json_export/from export/g' \
    -e 's/import json_export/import export/g' \
    {} +

# Update bash scripts and Dockerfile
sed -i 's/scan_session\.py/scan.py/g' scripts/*.sh Dockerfile
sed -i 's/json_export\.py/export.py/g' scripts/*.sh Dockerfile

# Confirm changes
echo "✅ Module reference update complete."
