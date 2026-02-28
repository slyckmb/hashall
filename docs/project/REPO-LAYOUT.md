# Repo Layout Policy

Last updated: 2026-02-28

## Goal

Keep repo root small and stable while preserving operator-friendly entrypoints.

## Placement Rules

- `src/`: application code only (`hashall`, `rehome`).
- `bin/`: operational scripts and utilities.
- `bin/scan/`: scan/planning helper scripts.
- `bin/tools/`: standalone operational tools (for example `iowatch`).
- `tests/`: automated test suites.
- `tests/manual/`: manual/integration helper scripts that are not part of normal pytest collection.
- `benchmarks/`: benchmarking scripts and benchmark outputs.
- `docs/`: active documentation.
- `docs/archive/`: historical and legacy artifacts.

## Root Directory Rules

Keep only:
- project metadata (`README.md`, `pyproject.toml`, `Makefile`, etc.),
- compatibility entrypoint wrappers,
- top-level project directories.

Do not add new operational scripts at root unless they are compatibility wrappers.

## Compatibility Wrappers

Root wrapper commands are retained for operator continuity:
- `hashall-smart-scan` -> `bin/scan/hashall-smart-scan`
- `hashall-auto-scan` -> `bin/scan/hashall-auto-scan`
- `hashall-plan-scan` -> `bin/scan/hashall-plan-scan`
- `hashall-tune-presets` -> `bin/scan/hashall-tune-presets`
- `iowatch` -> `bin/tools/iowatch`

These wrappers should remain thin `exec` shims only.
