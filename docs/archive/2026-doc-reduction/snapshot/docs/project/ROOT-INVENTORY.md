# Root Inventory

Last updated: 2026-02-28

## Classification

### Keep at Root (authoritative or compatibility)

- `README.md`, `AGENTS*.md`, `pyproject.toml`, `Makefile`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.gitignore`, `.bumpver.toml`
- top-level directories: `src/`, `bin/`, `docs/`, `tests/`, `benchmarks/`, `scripts/`, `tools/`, `ops/`, `archive/`
- compatibility wrappers:
  - `hashall-smart-scan`
  - `hashall-auto-scan`
  - `hashall-plan-scan`
  - `hashall-tune-presets`
  - `iowatch`
- compatibility stub:
  - `TODO.md` (points to `docs/project/TODO.md`)

### Moved in This Refactor

- `bench-fast-hash-workers.py` -> `benchmarks/bench-fast-hash-workers.py`
- `bench-fast-hash-workers-io.py` -> `benchmarks/bench-fast-hash-workers-io.py`
- `test-collision-detection.py` -> `tests/manual/test-collision-detection.py`
- `recovery-rsync-pass.sh` -> `bin/recovery-rsync-pass.sh`
- `hashall-smart-scan` (implementation) -> `bin/scan/hashall-smart-scan`
- `hashall-auto-scan` (implementation) -> `bin/scan/hashall-auto-scan`
- `hashall-plan-scan` (implementation) -> `bin/scan/hashall-plan-scan`
- `hashall-tune-presets` (implementation) -> `bin/scan/hashall-tune-presets`
- `iowatch` (implementation) -> `bin/tools/iowatch`
- `TODO.md` (content) -> `docs/project/TODO.md`

### Archived

- `schema.sql` -> `docs/archive/legacy/schema.sql`

## Notes

- Runtime schema source-of-truth remains migrations under `src/hashall/migrations/`.
- Root wrappers are intentionally minimal and should not diverge from canonical scripts.
