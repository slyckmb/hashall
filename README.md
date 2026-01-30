# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# hashall

`hashall` is a fast, threaded file hashing and verification utility that stores file metadata in a local SQLite database for scan/export/compare workflows.

---

## 🔧 Features

- ✅ Fast, threaded directory scanning
- 🧠 Stores file metadata in SQLite (`hashall.sqlite3`)
- 🔍 Verifies file trees via scan sessions and JSON exports
- 📦 Designed for deduping, archiving, and long-term seeding workflows
- 📊 tqdm-powered progress bars for all operations
- 🧾 Exports scan sessions to `.hashall/hashall.json` for external tooling
- 🧠 Tracks scan sessions using UUIDs and persistent metadata
- 🌲 New: Smart tree verification via `verify-trees` command

---

## 📦 Installation

```bash
git clone git@github.com:slyckmb/hashall.git
cd hashall
python3 -m venv $HOME/.venvs/hashall
source $HOME/.venvs/hashall/bin/activate
pip install -r requirements.txt
```

(Requirements file coming soon — add `pytest` if testing)

---

## 🚀 Usage

```bash
python -m hashall scan /path/to/root [--db PATH] [--parallel]
python -m hashall export /path/to/hashall.sqlite3 [--root /path/to/root] [--out /path/to/output.json]
python -m hashall verify-trees /src/root /dst/root [--repair] [--force] [--no-export] [--db PATH]
```

See `docs/cli.md` for the full CLI reference.

---

## 🌲 verify-trees: Smart File Tree Comparison

Compare two directory trees using previously stored scan sessions.

```bash
hashall verify-trees /path/to/source /path/to/destination [--repair] [--force]
```

| Flag        | Description |
|-------------|-------------|
| `--repair`  | Emit file list for potential rsync-style repair |
| `--force`   | Force a fresh rescan even if session data exists |
| `--help`    | Show command help |

### Example:
```bash
hashall verify-trees /mnt/dataA /mnt/dataB --repair
```

💡 This performs a session-based scan/load and hash comparison of both trees, emitting diffs and (soon) a repair manifest.

---

## 🧪 Running Tests

```bash
pytest tests/
```

You can also run individual test files:

```bash
python3 tests/test_verify_trees.py
python3 tests/test_diff.py
python3 tests/test_cli_all.py
```

---

## 📁 Database Schema

See `docs/schema.md` and `schema.sql`.

---

## 📄 Example JSON Output

See `docs/architecture.md` for the data flow and artifacts.

---

## ⌨️ Make Targets

Coming soon:
```bash
make scan DIR=~/media
make verify
make clean
```

---

## 📌 Roadmap
- [x] Base scan/verify/clean tool
- [x] TUI/CLI progress feedback
- [x] JSON export with metadata
- [x] UUID-based scan session tracking
- [x] Treehash-based smart comparison
- [ ] `verify-trees` repair manifest via `--files-from`
- [ ] Rsync repair integration
- [ ] `dupes` reporting
- [ ] Dedup strategies (hardlink/move/delete)
- [ ] Export filters and incremental updates

---

## 📄 License
MIT

---

## 👤 Author
Maintained by [slyckmb](https://github.com/slyckmb)

---

Have feedback or ideas? PRs and issues welcome!
