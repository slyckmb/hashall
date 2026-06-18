"""
Lane 1 execute: rename category directories and repoint clients.

Two code paths:
  A. Target-absent: os.rename(source_dir, canonical_path)  -- atomic
  B. Target-exists: deferred (not implemented in this module)

This module implements Path A only. Path A is used when the canonical
category directory does not yet exist.

Client behavior:
  RT: repoint via rt_apply_directory_repoint (restart=True, resumes seeding)
  qB: repoint via set_location (pauses torrent, stays paused -- DO NOT resume)
"""

import os
import time
from typing import Optional

from .lane1_plan import Lane1PlanItem
from .qbittorrent import QBittorrentClient
from .rtorrent import (
    DEFAULT_RT_RPC_URL,
    rt_apply_directory_repoint,
    rt_xmlrpc_call,
    _xmlrpc_scalar_text,
)


def _group_items(plan_items: list[dict], source_dir: str) -> list[dict]:
    """Filter plan items to a single source-dir group, sorted by hash."""
    group = [it for it in plan_items if (it.get("source_dir") or "") == source_dir]
    group.sort(key=lambda it: it.get("hash", ""))
    return group


def execute_lane1_group_atomic(
    group_items: list[dict],
    *,
    dry_run: bool = False,
    qb_client: Optional[QBittorrentClient] = None,
    rt_rpc_url: str = DEFAULT_RT_RPC_URL,
) -> dict:
    """
    Execute a single Lane 1 atomic-rename group.

    All items must share the same source_dir and canonical_path.
    The canonical_path must NOT exist before calling this function.

    Returns a result dict with rename_done, items (per-item results), errors.
    """
    if not group_items:
        return {
            "group_source": "",
            "group_canonical": "",
            "rename_done": False,
            "items": [],
            "errors": ["empty group"],
        }

    source_dir = group_items[0].get("source_dir", "")
    canonical_path = group_items[0].get("canonical_path", "")

    result = {
        "group_source": source_dir,
        "group_canonical": canonical_path,
        "rename_done": False,
        "items": [],
        "errors": [],
    }

    if dry_run:
        result["items"] = [
            {
                "hash": it.get("hash", ""),
                "name": it.get("name", ""),
                "rt": "dry_run",
                "qb": "dry_run",
                "notes": ["dry-run: no mutations performed"],
            }
            for it in group_items
        ]
        return result

    # Step 1 -- Pre-checks
    if not os.path.isdir(source_dir):
        result["errors"].append(f"source dir missing: {source_dir}")
        return result

    if os.path.exists(canonical_path):
        result["errors"].append(f"target already exists: {canonical_path}")
        return result

    # Check active downloads
    if qb_client:
        for it in group_items:
            h = it.get("hash", "")
            if not h:
                continue
            try:
                qb_info = qb_client.get_torrent_info(h)
                if qb_info and qb_info.state in (
                    "downloading", "stalledDL", "checkingDL", "metaDL",
                ):
                    result["errors"].append(
                        f"active download in group: {h[:16]} state={qb_info.state}"
                    )
                    return result
            except Exception as e:
                result["errors"].append(
                    f"could not check qB state for {h[:16]}: {e}"
                )
                return result

    # Step 2 -- Rename directory
    try:
        parent = os.path.dirname(canonical_path.rstrip("/"))
        os.makedirs(parent, exist_ok=True)
        os.rename(source_dir, canonical_path)
        result["rename_done"] = True
    except OSError as e:
        result["errors"].append(f"rename failed: {e}")
        return result

    # Step 3 -- Repoint each torrent
    for it in group_items:
        h = it.get("hash", "")
        name = it.get("name", "")
        item_res: dict = {
            "hash": h,
            "name": name,
            "rt": "pending",
            "qb": "pending",
            "notes": [],
        }

        # RT repoint
        if h:
            try:
                rt_apply_directory_repoint(
                    h, canonical_path,
                    rpc_url=rt_rpc_url, restart=True,
                )
                # Verify RT — allow RT directory at save-path level or one level deeper
                rt_dir_xml = rt_xmlrpc_call("d.directory", h, rpc_url=rt_rpc_url)
                rt_dir = _xmlrpc_scalar_text(rt_dir_xml).rstrip("/")
                rt_canon = canonical_path.rstrip("/")
                if rt_dir == rt_canon or rt_dir.startswith(rt_canon + "/"):
                    rt_state_xml = rt_xmlrpc_call("d.state", h, rpc_url=rt_rpc_url)
                    rt_state = _xmlrpc_scalar_text(rt_state_xml).strip()
                    item_res["rt"] = "ok"
                    item_res["notes"].append(f"RT directory={rt_dir} state={rt_state}")
                else:
                    item_res["rt"] = "failed"
                    item_res["notes"].append(
                        f"RT directory mismatch: got {rt_dir!r} expected {canonical_path!r}"
                    )
            except Exception as e:
                item_res["rt"] = "failed"
                item_res["notes"].append(f"RT repoint error: {e}")

        # qB set_location
        if h and qb_client:
            try:
                success = qb_client.set_location(h, canonical_path)
                if not success:
                    item_res["qb"] = "failed"
                    item_res["notes"].append("qB set_location returned False")
                else:
                    # Poll for save_path update (up to 10s)
                    qb_info = None
                    for _ in range(20):
                        try:
                            qb_info = qb_client.get_torrent_info(h)
                            if qb_info and qb_info.save_path.rstrip("/") == canonical_path.rstrip("/"):
                                break
                        except Exception:
                            pass
                        time.sleep(0.5)
                    if qb_info and qb_info.save_path.rstrip("/") == canonical_path.rstrip("/"):
                        # Save path confirmed — now re-pause if needed
                        PAUSED_STATES = {"pausedUP", "stoppedUP", "pausedDL", "stoppedDL"}
                        state = qb_info.state or ""

                        # Step A — wait for checkingUP to clear (up to 15s)
                        for _ in range(30):
                            if state != "checkingUP":
                                break
                            time.sleep(0.5)
                            try:
                                qb_info = qb_client.get_torrent_info(h)
                                state = (qb_info.state or "") if qb_info else ""
                            except Exception:
                                pass

                        # Step B — re-pause if not already paused
                        if state not in PAUSED_STATES:
                            try:
                                qb_client.pause_torrent(h)
                            except Exception as e:
                                state = f"{state} (pause_called_err={e})"

                        # Step C — poll up to 5s for paused state
                        for _ in range(10):
                            if state in PAUSED_STATES:
                                break
                            time.sleep(0.5)
                            try:
                                qb_info = qb_client.get_torrent_info(h)
                                state = (qb_info.state or "") if qb_info else ""
                            except Exception:
                                pass

                        # Step D — record
                        item_res["notes"].append(
                            f"qB save_path={canonical_path} state={state}"
                        )
                        if state in PAUSED_STATES:
                            item_res["qb"] = "ok"
                        else:
                            item_res["qb"] = "warn_not_paused"
                            item_res["notes"].append(
                                f"not paused after re-pause attempt: state={state}"
                            )
                    else:
                        item_res["qb"] = "failed"
                        item_res["notes"].append(
                            "qB save_path did not update after 10s poll"
                        )
            except Exception as e:
                item_res["qb"] = "failed"
                item_res["notes"].append(f"qB set_location error: {e}")

        # DO NOT resume qB -- stays paused
        result["items"].append(item_res)

    # Step 4 -- Post-group verification
    if os.path.exists(source_dir):
        result["errors"].append(
            f"source dir still exists after rename: {source_dir}"
        )
    if not os.path.isdir(canonical_path):
        result["errors"].append(
            f"canonical path missing after rename: {canonical_path}"
        )

    return result
