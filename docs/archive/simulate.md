🔍 Simulate \
--deep-audit \
--cli-walkthrough \
--import-tree-check \
--symbol-resolution \
--module-existence-check \
--build-and-install-check \
--entry-points-test \
--db-schema-sanity \
--json-roundtrip-test \
--pytest-dry-run \
--orphan-check \
--file-naming-check \
--argparse-vs-click-check \
--strict \
--fix=rename-bad-filenames,comment-missing-imports,add-missing-init \
--patch-report=renames,missing-import-guards \
--auto-makefile=with-install-test-lint-targets \
--multi-pass=structure,semantics,runtime,drift \
--drift-check \
--regression-save=before,after \
--hallucination-check \
--real-file-confirmation \
--assume-installed
--skip-network-ops\
--run-environment="pip install -e . || export PYTHONPATH=\$(pwd)/src:\$PYTHONPATH"

# 💡 How It Works:
# --run-environment="..." lets you inject shell-style prep.
# 
# The command pip install -e . || ... tries install first.
# 
# Fallback to setting PYTHONPATH=src if install not wanted.
