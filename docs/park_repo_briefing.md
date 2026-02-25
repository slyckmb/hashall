# Repo: hashall
## What it is
- Python CLI project for scanning file trees and storing metadata in SQLite, with JSON export for later verification. (`src/hashall/scan.py`, `src/hashall/export.py`)
- Intended “smart verify + treehash” workflow for comparing two trees after migration (see `src/hashall/verify_trees.py` and design doc `docs/smart-verify-treehash.md`).
- Includes dev tooling for ZFS-style rsync migrations and verification (`tools/dev-zfs-migrate/glider_migrate.sh`, `tools/dev-zfs-migrate/glider_verify.sh`).
- Contains older/experimental “filehash” utilities that build a separate SQLite DB for dedupe analysis (`tools/dev-filehash/*`, `analyze_hashes.py`).

## Key commands / entrypoints
- `hashall` console script via Click (`pyproject.toml` → `hashall = "hashall.cli:cli"`).
- `python3 -m hashall --help` failed due to missing dependency:
  ```
  ModuleNotFoundError: No module named 'click'
  ```
- Click subcommands (from `src/hashall/cli.py`):
  - `hashall scan <path> [--db PATH] [--parallel]`
  - `hashall export <db_path> [--root PATH] [--out PATH]`
  - `hashall verify-trees <src> <dst> [--repair] [--rsync-source PATH] [--db PATH] [--force] [--no-export]`
- Legacy/aux CLIs:
  - `archive/filehash_tool.py` (argparse-based scan/export/version; see README usage).
  - `analyze_hashes.py` (argparse CLI for dedupe grouping over a different DB schema).
  - ZFS helpers: `tools/dev-zfs-migrate/glider_migrate.sh`, `tools/dev-zfs-migrate/glider_verify.sh` (rsync based).

## Data formats / caches
- Primary cache: SQLite at `~/.hashall/hashall.sqlite3` (`DEFAULT_DB_PATH` in `src/hashall/cli.py`).
- Schema + migrations:
  - `schema.sql` and `src/hashall/migrations/*.sql` define `scan_sessions` and `files` (with `sha1`, `scan_session_id`).
- JSON export: `<root>/.hashall/hashall.json` written by `src/hashall/export.py`.
- Legacy/dev file hash DB: `~/.filehashdb.sqlite` from `tools/dev-filehash/hashall.sh` (table `file_hashes`).

## Hashing / grouping model
- File hashing: SHA1 computed in `src/hashall/scan.py` (`compute_sha1`), but the insert currently omits `sha1` (only `path,size,mtime,scan_session_id` are stored). This is a **schema/logic mismatch** against `schema.sql` which expects a `sha1` column.
- Tree hash: `src/hashall/treehash.py` builds a SHA1 digest of `rel_path|sha1|size|mtime` and expects `scan_id` + `rel_path` fields; these do **not** match the current `files` table schema in `schema.sql` (which uses `path` and `scan_session_id`).
- Duplicate grouping: `analyze_hashes.py` groups by SHA1 from a `file_hashes` table (different schema from the main app). This is useful but appears to target the dev-filehash DB, not the primary `hashall.sqlite3`.

## Hardlink / dedupe capabilities
- Core CLI does **not** create hardlinks.
- Hardlink awareness is described in the design doc `docs/smart-verify-treehash.md` and in `analyze_hashes.py` (inode-aware grouping and “reclaimable” size), but the primary scan path currently does not populate inode/device fields.
- No in-core dedupe operations beyond reporting; rsync repair hooks are placeholders (`src/hashall/repair.py`).

## Relevance to qBittorrent seed migration design
- **Best fit for hashing + tree verification** once schema/code alignment is fixed: SQLite index + JSON export + verify-trees scaffolding.
- **Not ready for hardlink creation**; only analysis/planning in docs and helper scripts.
- **Useful ZFS migration support** via rsync scripts in `tools/dev-zfs-migrate/`.
- **Potentially reusable primitives**:
  - `scan_path` (file walk + SHA1)
  - `export_json` (structured export)
  - `compute_treehash` concept
  - `analyze_hashes.py` grouping logic for reclaimable hardlinks (but against legacy schema)

## Notes / risks / TODO
- Git metadata:
  - `git branch --show-current`: `dev/smart-verify`
  - `git status --porcelain=v1` shows many modified files (example output):
    ```
    M src/hashall/cli.py
    M src/hashall/scan.py
    M src/hashall/treehash.py
    ...
    ```
  - `git log -5 --oneline`:
    ```
    2b54fe9 🔖 Release: Hashall v0.4.0 — Smart Verify & Treehash Foundation
    c4c6cda 🚀 Release v0.4.0 — Smart Tree Verification, Sessions, Migrations
    1e4a43c 🔨 Add Docker scan + export tooling with DSM support and Hash-Dash monitor
    1e1491b 🐳 Docker Workflow: Scan, Export, and Test Scripts
    ece8e13 🛠️ Infrastructure & Tooling Updates
    ```
- **Schema vs code mismatch** (scan writes `scan_session_id` as UUID string into a column defined as INTEGER FK; treehash and manifest refer to `rel_path/scan_id`). This needs reconciliation before production use.
- CLI help could not be executed because `click` is not installed in this environment.

---

# Repo: hashdeep
## What it is
- C/C++ toolset for file hashing: `hashdeep`, `md5deep`, `sha1deep`, `sha256deep`, `tigerdeep`, `whirlpooldeep`.
- Supports recursive hashing, audit/match against known hash sets, and multiple algorithms per file.

## Key commands / entrypoints
- Binaries in `src/` (e.g., `src/hashdeep`, `src/md5deep`, `src/sha1deep`, `src/sha256deep`).
- Man pages in `man/` (e.g., `man/hashdeep.1`) describe flags like `-c`, `-r`, `-k`, `-a`, `-m/-x`, `-p` (piecewise mode).

## Data formats / caches
- Output format documented in `FILEFORMAT` (hashdeep file format v1.0): CSV-like with header lines and columns like `size,md5,sha256,filename`.
- No persistent DB/cache; hash lists are plain text files.

## Hashing / grouping model
- File hashing via MD5/SHA1/SHA256/Tiger/Whirlpool (`README.md`).
- Can “audit” or match against known hash sets but does not build a structured duplicate grouping DB on its own.
- Piecewise hashing mode (`-p`) for chunked hashing.

## Hardlink / dedupe capabilities
- No hardlink creation.
- Dedup is limited to matching/audit output against known hash sets.

## Relevance to qBittorrent seed migration design
- Useful as a **standalone hashing engine** or for generating audit files for external comparison.
- Not a subtree-hash or hardlink tool; no structured cache or incremental update system.

## Notes / risks / TODO
- Git metadata:
  - `git branch --show-current`: `master`
  - `git status --porcelain=v1` includes modified files and untracked `md5deep-4.4.zip` and `tmp/`.
  - `git log -5 --oneline`:
    ```
    8776134 Merge pull request #361 from kraj/master
    36350d4 Merge pull request #373 from Makishima/patch-1
    6767fdb Update README.md
    6ef69a2 Fix errors found by clang
    72e41af Add release hashes
    ```

---

# Repo: jdupster
## What it is
- Real-time monitor for `jdupes` runs; provides progress/ETA by watching open file descriptors (`jdupster.py`).
- Includes a wrapper script to run `jdupes` with a hash DB and optional hardlink dedupe (`scripts/jdupes_scan.sh`).

## Key commands / entrypoints
- `python3 jdupster.py` (monitor). `--help` failed due to missing dependency:
  ```
  ModuleNotFoundError: No module named 'psutil'
  ```
- `scripts/jdupes_monitor.sh`: Bash monitor using `lsof`.
- `scripts/jdupes_scan.sh`: CLI wrapper around `jdupes` with options for `--hldupes` (hardlink), `--dry-run`, `--hashdb`.

## Data formats / caches
- `jdupes_scan.sh` default cache: `~/.jdupes-cache/hashdb.txt` (jdupes hash DB file).
- Logs: `~/logs/jdupes/jdupes-<timestamp>.log`.
- No internal DB of its own; it reads process state and filesystem sizes.

## Hashing / grouping model
- No hashing logic inside Jdupster; it relies on `jdupes` for hashing and duplicate grouping.

## Hardlink / dedupe capabilities
- Hardlink dedupe via `jdupes` when `scripts/jdupes_scan.sh --hldupes` is used (jdupes `-L`).
- Jdupster itself does not create links.

## Relevance to qBittorrent seed migration design
- **Useful for monitoring long jdupes runs** and for a standardized jdupes wrapper script.
- Does not implement hashing or subtree identity; it wraps/observes external dedupe tooling.

## Notes / risks / TODO
- Git metadata:
  - `git branch --show-current`: `dev/v4.x`
  - `git status --porcelain=v1` shows modified `jdupster.py` and script symlink changes.
  - `git log -5 --oneline`:
    ```
    5d795c4 Merge pull request #1 from slyckmb/codex/replace-placeholder-in-license-with-mit-license
    72922d8 Replace placeholder MIT license
    e6687f6 Initial commit of jdupster v4.1: Real-time jdupes monitor with adaptive ETA
    29fd2c3 Initial commit: add README to main
    ```

---

# Repo: rehash
## What it is
- CLI tool for parsing ChatGPT exports into structured JSON; unrelated to file hashing or dedupe (`README.md`).

## Key commands / entrypoints
- `rehash` CLI (argparse). `--help` works:
  ```
  usage: rehash [-h] {parse-export,extract-day,extract-session} ...
  ```
- Console scripts: `rehash` and `rehashit` (`pyproject.toml`).

## Data formats / caches
- Reads `chatgpt-export.zip` and writes per-conversation JSON to output dirs (`src/rehash/extract_export.py`).

## Hashing / grouping model
- None; no file hashing or subtree identity logic.

## Hardlink / dedupe capabilities
- None.

## Relevance to qBittorrent seed migration design
- **Not relevant** to hashing/dedupe/migration pipeline.

## Notes / risks / TODO
- Git metadata:
  - `git branch --show-current`: `main`
  - `git status --porcelain=v1` shows multiple modified files in `src/rehash/` and `tests/`.
  - `git log -5 --oneline`:
    ```
    3e1fe32 release: rehash v0.4.0 with CLI + fitness filtering
    704da61 chore: cleanup gitignore and package init
    ebf36ac tests: update pyproject and expand integration + edgecase coverage (v0.4.x)
    b46a2a9 docs: add REQUIREMENTS-0.4.x.md and rehash_dev_requirements_v1.md (v0.4.x)
    7a1c5cb 🚀 Add Rehash CLI + structured export support
    ```

---

# Cross-repo synthesis
## Capability matrix
| Repo      | File hash | Subtree hash | Duplicate grouping | Hardlink ops | Cache/index | Incremental update |
|-----------|-----------|--------------|--------------------|--------------|-------------|--------------------|
| hashall   | Yes (SHA1 in `scan.py`, but not persisted) | Planned/partial (`treehash.py` + design doc; schema mismatch) | Partial (legacy `analyze_hashes.py` on `file_hashes`) | Planned only; no core hardlink ops | SQLite (`~/.hashall/hashall.sqlite3`) + JSON export | Unclear; no explicit incremental logic found |
| hashdeep  | Yes (md5/sha1/sha256/tiger/whirlpool) | No | Audit/match against known hashes (not grouping) | No | Hash list text files (`FILEFORMAT`) | No |
| jdupster  | No (delegates to `jdupes`) | No | Delegates to `jdupes` | Via `jdupes -L` in `scripts/jdupes_scan.sh` | jdupes hash DB (`~/.jdupes-cache/hashdb.txt`) | jdupes hashdb reuse (external) |
| rehash    | No | No | No | No | JSON output (ChatGPT exports) | No |

## Suggested integration plan
1) **Base library: hashall** for scanning + SQLite index + JSON exports, once schema/code are aligned and SHA1/inode fields are actually stored.
2) **Hardlink dedupe stage**: use `jdupes` (with `scripts/jdupes_scan.sh --hldupes`) after hashall verifies identical content; keep `jdupster` for monitoring long runs.
3) **Optional external audit**: use `hashdeep` to generate/hash list files if you need a non-SQLite, portable verification artifact.

