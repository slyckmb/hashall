# GPT-SIM-CHECK

[MODE]: full-audit
[LANGUAGE]: python
[REPO]: [ZIP uploaded]
[CONFIG]:
  install_deps: true
  editable_mode: true
  run_linters: true
  run_tests: true
  run_coverage: true
  run_typing: true
  run_security: true
  strict_mode: true
  skip_network_ops: true
  patch_mode: true
  simulate_cli: true
  run_environment: "pip install -e . || export PYTHONPATH=$(pwd)/src:$PYTHONPATH"

[ANALYSIS]:
  multi_pass: [structure, semantics, runtime, drift]
  import_tree_check: true
  module_existence_check: true
  build_and_install_check: true
  entry_points_test: true
  db_schema_sanity: true
  json_roundtrip_test: true
  orphan_check: true
  file_naming_check: true
  symbol_resolution: true
  hallucination_check: true
  real_file_confirmation: true
  argparse_vs_click_check: true
  regression_save: [before, after]

[AUTO_FIX]:
  enable: true
  fixes: [rename-bad-filenames, comment-missing-imports, add-missing-init]
  patch_report: [renames, missing-import-guards]

[ACTIONS]:
  - pip install -e .[dev]
  - black . --check
  - flake8 your_package/
  - mypy your_package/
  - bandit -r your_package/
  - pylint your_package/
  - pytest --dry-run
  - pytest --cov=your_package --cov-report=term-missing
  - check-manifest
  - python setup.py check

[OUTPUT]:
  - uncovered_lines
  - static_analysis_issues
  - drift_report
  - patch_diff
  - proposed_fixes
