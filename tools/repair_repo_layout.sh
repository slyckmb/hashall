# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
#!/usr/bin/env bash
set -e

echo "🔧 Starting repo layout repair..."

# Ensure src/hashall exists
mkdir -p src/hashall

# Silence noisy commands
exec 3>&1 1>/dev/null 2>&1

# Git-safe move of functional files into src/hashall/
FILES=(
  cli.py diff.py verify.py verify_trees.py
  repair.py treehash.py model.py manifest.py
  verify_session.py scan.py
)

for file in "${FILES[@]}"; do
  [ -f "$file" ] && git mv "$file" src/hashall/ 2>/dev/null || mv "$file" src/hashall/
done

# Clean up bad nested dir if exists
[ -d "src/src" ] && rm -rf src/src

# Ensure __init__.py for module recognition
touch src/hashall/__init__.py

# Auto-fix pyproject.toml project layout and script entry
sed -i 's|src.hashall.cli|hashall.cli|' pyproject.toml
if ! grep -q '\[tool.setuptools\]' pyproject.toml; then
  echo -e "\n[tool.setuptools]\npackages = [\"hashall\"]\npackage-dir = {\"\" = \"src\"}" >> pyproject.toml
fi

# Optional: fix import references in .py files
find src/hashall -type f -name "*.py" -exec sed -i 's|from src\.hashall|from hashall|g' {} +
find src/hashall -type f -name "*.py" -exec sed -i 's|import src\.hashall|import hashall|g' {} +

# Restore stdout
exec 1>&3

echo "✅ Repo structure and imports repaired!"
