# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
"""
verify_session.py — Track and persist smart verify session metadata
"""

import json
from pathlib import Path
from datetime import datetime

def save_verify_session(session_dir: Path, metadata: dict):
    """
    Save verify session metadata as JSON to the given .hashall directory.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_file = session_dir / f"verify_session_{timestamp}.json"

    metadata["timestamp"] = timestamp
    metadata["version"] = "1.0"
    metadata["tool"] = "hashall"

    with open(output_file, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"📝 Saved verify session log: {output_file}")
    return output_file
