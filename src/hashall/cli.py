# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/cli.py
# ✅ Minimal fix: Added --no-export, fixed missing arg to verify_trees

import click
from pathlib import Path
from hashall.scan import scan_path
from hashall.export import export_json
from hashall.verify_trees import verify_trees
from hashall import __version__

DEFAULT_DB_PATH = Path.home() / ".hashall" / "hashall.sqlite3"

@click.group()
@click.version_option(__version__)
def cli():
    """Hashall — file hashing, verification, and migration tools"""
    pass

@cli.command("scan")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--parallel", is_flag=True, help="Use thread pool to hash faster.")
def scan_cmd(path, db, parallel):
    """Scan a directory and store file metadata in SQLite."""
    scan_path(db_path=Path(db), root_path=Path(path), parallel=parallel)

@cli.command("export")
@click.argument("db_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--root", "-r", type=click.Path(exists=True, file_okay=False),
              help="Optional source root path for context")
@click.option("--out", "-o", type=click.Path(),
              help="Output JSON file (default ~/.hashall/hashall.json)")
def export_cmd(db_path, root, out):
    """Export metadata from SQLite to JSON."""
    export_json(db_path=Path(db_path),
                root_path=Path(root) if root else None,
                out_path=out)

@cli.command("verify-trees")
@click.argument("src", type=click.Path(exists=True, file_okay=False))
@click.argument("dst", type=click.Path(exists=True, file_okay=False))
@click.option("--repair", is_flag=True, help="Run rsync repair if mismatches found.")
@click.option("--rsync-source", type=click.Path(exists=True, file_okay=False),
              help="Alternate rsync source path.")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH, help="SQLite DB path.")
@click.option("--force", is_flag=True, help="Actually perform scan and repair; otherwise dry-run.")
@click.option("--no-export", is_flag=True, help="Don't auto-write .hashall/hashall.json after scan.")
def verify_trees_cmd(src, dst, repair, rsync_source, db, force, no_export):
    """Verify that DST matches SRC, using SHA1 & smart scanning"""
    verify_trees(
        src_root=Path(src),
        dst_root=Path(dst),
        db_path=Path(db),
        repair=repair,
        dry_run=not force,
        rsync_source=Path(rsync_source) if rsync_source else None,
        auto_export=not no_export,
    )

if __name__ == "__main__":
    cli()
