task-log=j58-t02
status=done
job=j58
task=j58-t02

# j58-t02 Task Log

Implemented qB credential argv/log hardening.

Changed files:
- `src/hashall/cli.py`
- `bin/lib/script-metadata.sh`
- `bin/db-refresh-step4-payload-sync.sh`
- `docs/REFRESH_GUIDE.md`
- `tests/test_cli_payload_sync.py`

Summary:
- Redacted secret-bearing CLI arguments such as `--qbit-pass`, `--password`, and `-P` from the hashall run header.
- Added a deprecation warning when `hashall payload sync --qbit-pass` is used.
- Redacted the same password-style arguments in shared shell script metadata output.
- Removed `--qbit-user` and `--qbit-pass` from the DB refresh payload-sync wrapper; it now relies on the sourced qB secrets environment.
- Documented the safer env/file credential path in `docs/REFRESH_GUIDE.md`.
- Added focused tests proving qB password values are not echoed in CLI output/stderr and argv redaction masks secret values.

Validation:
- `source .venv/bin/activate && pytest tests/test_cli_payload_sync.py tests/test_qb_cache.py tests/test_qbittorrent.py` -> 74 passed
- `bash -n bin/lib/script-metadata.sh bin/db-refresh-step4-payload-sync.sh` -> pass

Friction:
- Both automated `t02` opencode dispatch attempts stalled with no diff; the bounded implementation was completed directly in the job worktree after file audit.

ops_closed=OP-73
follow_up_ops=none
