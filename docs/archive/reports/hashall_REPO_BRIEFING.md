# hashall

## What it does & key workflows
- CLI to scan a directory tree, store file metadata in SQLite, export JSON, and compare two trees via `verify-trees`. (`src/hashall/cli.py`, `src/hashall/scan.py`, `src/hashall/export.py`, `src/hashall/verify_trees.py`)
- “Smart verify” flow: load `.hashall/hashall.json` if present, otherwise scan and export, then diff by `path/size/mtime`. (`src/hashall/verify_trees.py:33-64`, `src/hashall/verify.py:18-50`)
- Design docs include treehash, inode/hardlink tracking, and rsync repair concepts, but implementations are partial. (`docs/smart-verify-treehash.md`)

## Entry points / CLI surface (actual --help output excerpts)
- `python -m hashall --help`:
  ```
  Usage: python -m hashall [OPTIONS] COMMAND [ARGS]...

    Hashall — file hashing, verification, and migration tools

  Options:
    --version  Show the version and exit.
    --help     Show this message and exit.

  Commands:
    export        Export metadata from SQLite to JSON.
    scan          Scan a directory and store file metadata in SQLite.
    verify-trees  Verify that DST matches SRC, using SHA1 & smart scanning
  ```
- `python -m hashall scan --help`:
  ```
  Usage: python -m hashall scan [OPTIONS] PATH

  Options:
    --db PATH   SQLite DB path.
    --parallel  Use thread pool to hash faster.
  ```
- `python -m hashall export --help`:
  ```
  Usage: python -m hashall export [OPTIONS] DB_PATH

  Options:
    -r, --root DIRECTORY  Optional source root path for context
    -o, --out PATH        Output JSON file (default ~/.hashall/hashall.json)
  ```
- `python -m hashall verify-trees --help`:
  ```
  Usage: python -m hashall verify-trees [OPTIONS] SRC DST

  Options:
    --repair
    --rsync-source DIRECTORY
    --db PATH
    --force
    --no-export
  ```

## What data it emits/consumes (logs, temp files, formats)
- Primary SQLite DB: `~/.hashall/hashall.sqlite3` by default (`src/hashall/cli.py:11-23`).
- JSON export: `<root>/.hashall/hashall.json` (`src/hashall/export.py:30-33`).
- Console output via Rich (diff reporting) and tqdm (scan progress).

## Hashing / grouping / monitoring model
- File hashing: SHA1 computed per file (`src/hashall/scan.py:10-35`).
- Tree verification: compares `path`, `size`, `mtime` for two scan sessions, **not SHA1** in current `verify_paths` (`src/hashall/verify.py:18-44`).
- Treehash: implemented in `src/hashall/treehash.py`, but references schema fields that do not exist in the current schema (`rel_path`, `scan_id`, `scan_session` table).
- No internal monitoring; optional shell dashboard scripts exist (`scripts/hash-dash.sh`, `scripts/hash-dash-loop.sh`).

## Hardlink / dedupe capabilities
- No in-core hardlink creation.
- Hardlink/inode tracking is described in docs but not implemented in the active schema or scan path.
- `src/hashall/repair.py` is a placeholder for rsync repair.

## DB / cache schema (if applicable)
- `schema.sql` defines:
  - `scan_sessions(id, scan_id, root_path, started_at, treehash)`
  - `files(path, size, mtime, sha1, scan_session_id)` with FK to `scan_sessions(id)` (`schema.sql:3-18`).
- `src/hashall/model.py` initializes a **different** `files` schema: `path, size, mtime, scan_session_id TEXT` (no `sha1`, no `scan_sessions`) (`src/hashall/model.py:16-24`).

## Code ↔ schema mismatch map (if applicable)
- **scan_sessions table never populated**:
  - `schema.sql` expects scan sessions (`schema.sql:3-9`), but `scan_path()` never inserts into `scan_sessions` (`src/hashall/scan.py:17-38`).
- **`scan_session_id` type mismatch**:
  - Schema expects INTEGER FK (`schema.sql:16-18`), but `scan_path()` inserts a UUID string (`src/hashall/scan.py:21, 36-38`).
  - `model.py` also defines `scan_session_id TEXT` (`src/hashall/model.py:16-23`).
- **`sha1` computed but not persisted**:
  - `compute_sha1()` is called (`src/hashall/scan.py:34`), but SQL insert omits `sha1` (`src/hashall/scan.py:35-38`).
- **`treehash.py` references non-existent columns/tables**:
  - Uses `files.rel_path` and `files.scan_id` (`src/hashall/treehash.py:20-24`), but schema defines `files.path` and `files.scan_session_id` (`schema.sql:11-18`).
  - Updates `scan_session` table (singular) instead of `scan_sessions` (`src/hashall/treehash.py:36-38`).
- **`manifest.py` uses `relpath` and `scan_id` columns**:
  - Query uses `files.relpath` and `files.scan_id` (`src/hashall/manifest.py:16-23`), which are not present in schema.
- **`export_json()` expects scan_sessions**:
  - Queries `scan_sessions` (`src/hashall/export.py:10-21`), but scan path never creates a scan session row, so exports may fail/return nothing without manual DB prep.

## Relevance to qBittorrent seed migration & hardlink view creation
- **Usable today (with caveats)**:
  - `hashall scan` + `hashall verify-trees` can run end-to-end, but verification uses only size/mtime and relies on JSON import/scan sessions that are inconsistently stored.
  - `export` can emit JSON if a valid `scan_sessions` row exists; otherwise it reports “No scan session found”.
- **Potential reusable primitives**:
  - `scan_path()` for traversal + SHA1 computation (`src/hashall/scan.py:10-38`).
  - `verify_paths()` for basic path/size/mtime comparison (`src/hashall/verify.py:18-50`).
  - `export_json()` for JSON artifacts (`src/hashall/export.py:6-33`).
- **Controller integration**: CLI surface is stable and can be called with `python -m hashall …` for scans and verification; Python module functions are importable for tighter integration.

## Risks / TODO / integration notes
- **Schema inconsistencies are the main blocker** for using hashall as a reliable incremental cache/index.
- **Minimal fix set to make it usable as an incremental cache/index** (smallest changes implied by current code paths):
  1) Standardize on **one schema** and update code to match it. Recommended minimal delta to current schema:
     - Keep `scan_sessions(id INTEGER PRIMARY KEY, scan_id TEXT, root_path TEXT, started_at, treehash)` and `files(path, size, mtime, sha1, scan_session_id INTEGER FK)` as in `schema.sql`.
  2) Update `scan_path()` to:
     - Insert a row into `scan_sessions` with `(scan_id, root_path)` and capture its `id`.
     - Insert file rows with that integer `scan_session_id` and persist `sha1`.
  3) Update `model.init_db_schema()` to **not** create a conflicting `files` table or to match the unified schema.
  4) Fix `treehash.py` and `manifest.py` to use `files.path` and `files.scan_session_id`, and to update `scan_sessions` (plural table).
  5) Align `load_json_scan_into_db()` to map JSON into the same schema and, if needed, create a `scan_sessions` entry when importing JSON.
- **Verify logic does not compare SHA1**; it only compares size/mtime. For seed integrity, SHA1/size should be included in diff logic.
- Tests likely create temp DBs (`tests/test_treehash.py` uses temp DB and deletes it), but were not run due to the no-mutation requirement.

