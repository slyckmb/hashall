# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/utils.py

from pathlib import Path

def find_db_path(db_path=None):
    """
    Return a Path to the SQLite DB.
    If db_path is not provided, use ~/.hashall/hashall.sqlite3.
    """
    if db_path:
        return Path(db_path)
    default = Path.home() / ".hashall" / "hashall.sqlite3"
    return default

def find_json_path(json_path=None, db_path=None):
    """
    Provide a fallback JSON path if one isn’t passed explicitly.
    Default: near the DB file, with a `.json` extension.
    """
    if json_path:
        return Path(json_path)
    db = find_db_path(db_path)
    return db.with_suffix(".json")
