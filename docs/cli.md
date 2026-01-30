# hashall CLI

## Entry point

Use the module entry point (preferred for dev):

```bash
python -m hashall --help
```

Installed console script (if installed via `pip`):

```bash
hashall --help
```

## Core commands

### scan

```bash
python -m hashall scan /path/to/root [--db PATH] [--parallel]
```

- Default DB path: `~/.hashall/hashall.sqlite3`
- Scans a directory tree and stores file metadata in SQLite.

### export

```bash
python -m hashall export /path/to/hashall.sqlite3 [--root /path/to/root] [--out /path/to/output.json]
```

- Writes JSON to `<root>/.hashall/hashall.json` if `--out` is not set.

### verify-trees

```bash
python -m hashall verify-trees /src/root /dst/root [--db PATH] [--repair] [--rsync-source PATH] [--force] [--no-export]
```

- Loads `.hashall/hashall.json` if present; otherwise scans and exports.
- Compares scans and reports differences to stdout.

