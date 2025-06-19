# hashall

`hashall` is a fast, threaded file hashing and deduplication utility. It uses partial and full SHA-1 hashes stored in a local SQLite database to index and compare large sets of files efficiently.

---

## 🔧 Features

- ✅ Fast, threaded directory scanning
- 🧠 Stores file metadata in SQLite (`.filehash.db`)
- 🔍 Verifies full hashes only for files with matching partial hashes
- 🧹 Removes stale DB entries for missing files
- 📦 Designed for deduping, archiving, and long-term seeding workflows
- 📊 tqdm-powered progress bars for all operations

---

## 📦 Installation

```bash
git clone git@github.com:slyckmb/hashall.git
cd hashall
python3 -m venv ~/.venvs/hashall
source ~/.venvs/hashall/bin/activate
pip install -r requirements.txt
```

(Requirements file coming soon.)

---

## 🚀 Usage

```bash
python filehash_tool.py scan <directory> [--verbose]
python filehash_tool.py verify [--verbose]
python filehash_tool.py clean [--verbose]
```

### Commands:
- `scan <dir>` — Index files into the database
- `verify` — Compute full hashes for potential dupes
- `clean` — Remove DB entries for missing files

---

## 📁 Database Schema

Each file indexed will store:
- Full path
- Size, mtime, inode
- Owner UID & GID
- Partial SHA-1
- Full SHA-1 (if verified)

Stored in: `~/.filehash.db`

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
- [ ] `dupes` reporting
- [ ] CSV/JSON export
- [ ] Dedup strategies (hardlink/move/delete)

---

## 📄 License
MIT

---

## 👤 Author
Maintained by [slyckmb](https://github.com/slyckmb)

---

Have feedback or ideas? PRs and issues welcome!

