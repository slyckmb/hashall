# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
````markdown
# 🛡️ Hashall Development Guardrails (v2)

## ✅ 1. State Locking & Diff Validation
- Compare patches against Last-Known-Good (LKG)
- Use semantic diff: no regressions in logic, imports, or public API

## 📂 2. Module Presence & Import Resolution
- Every `from hashall.X import Y`:
  - `X` must be a real file or package in `src/hashall/`
  - `Y` must exist in `X` as a top-level symbol

## 🚫 3. Patch Blocking Rules
- Block if:
  - CLI fails to run `hashall --help`
  - There are unresolved imports or missing symbols
  - Behavior regresses

## 🏷️ 4. Patch Provenance Tracking
Each file must include:
- `# Based on working version from: YYYY‑MM‑DD HH:MM`
- Description of changes and rationale

## 🔐 5. CLI Entrypoint Runtime Check
Before acceptance:
```bash
python3 -c "from hashall.cli import cli; cli(['--help'])"
```
Must pass without error.

## 🔬 6. Import Chain Resolution
All CLI subcommands must import successfully along with their dependencies.

## 🧪 7. Test-First Dry Run
Before merge:
- Run `pytest`
- Confirm `hashall --help` works
- Validate all `hashall <command> --help`

## 🔁 8. Commit Bundle Assembly
Ensure patch bundle:
- Contains all changed files
- Passes `run_full_audit.sh`
- Is ready-to-install

Use this document to enforce consistency across the team.
````
