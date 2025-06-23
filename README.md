# hashall

`hashall` is a fast, threaded file hashing and deduplication utility. It uses partial and full SHA-1 hashes stored in a local SQLite database to index and compare large sets of files efficiently.

---

## 🔧 Features

- ✅ Fast, threaded directory scanning
- 🧠 Stores file metadata in SQLite (`hashall.sqlite3`)
- 🔍 Verifies full hashes only for files with matching partial hashes
- 🧹 Removes stale DB entries for missing files
- 📦 Designed for deduping, archiving, and long-term seeding workflows
- 📊 tqdm-powered progress bars for all operations
- 🧾 Exports scan sessions to `.hashall/hashall.json` for external tooling
- 🧠 Tracks scan sessions using UUIDs and persistent metadata

---

## 📦 Installation

```bash
git clone git@github.com:slyckmb/hashall.git
cd hashall
python3 -m venv $HOME/.venvs/hashall
source $HOME/.venvs/hashall/bin/activate
pip install -r requirements.txt
```

(Requirements file coming soon.)

---

## 🚀 Usage

```bash
python filehash_tool.py scan <directory> [--db DB] [--mode MODE] [--workers N] [--debug]
python filehash_tool.py export <directory> [--db DB]
python filehash_tool.py version
```

### Commands:
- `scan <dir>` — Index files into the database and associate with a scan session
- `export <dir>` — Export JSON metadata for the latest scan session under `.hashall/hashall.json`
- `version` — Display version info

---

## 📁 Database Schema

Each file indexed stores:
- Full absolute path (`abs_path`)
- Relative path (`rel_path`)
- Device ID (`dev`), inode (`ino`)
- Size, mtime, UID, GID
- Partial SHA-1 and full SHA-1
- `scan_id` foreign key linking to `scan_session`

Stored in: `hashall.sqlite3`

---

## 📄 Example JSON Output

Located at: `<root>/.hashall/hashall.json`

```json
{
  "scan_id": "uuid-v4",
  "scan_time": "2025-06-17T18:45:22Z",
  "scan_root": "/mnt/data/movies",
  "hashall_version": "0.3.8-dev",
  "files": [
    {
      "rel_path": "movie1.avi",
      "size": 123456,
      "sha1": "abcdef123456..."
    },
    ...
  ]
}
```

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
