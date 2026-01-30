# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# src/hashall/diff.py
# Based on working version from: 2025-06-25 16:10
# ✅ Corrected import of DiffReport

from hashall.model import DiffReport

def diff_scan_sessions(conn, src_session_id, dst_session_id):
    """Diffs two scan sessions and returns report object."""
    report = DiffReport(entries=[])
    # TODO: populate entries list with actual diff logic
    return report
