"""
Lane 1 execute: rename category directories and repoint clients.

Two code paths:
  A. Target-absent (execute_lane1_group_atomic):
     os.rename(source_dir, canonical_path) — atomic category-dir rename.
     Used when the canonical category directory does not yet exist.

  B. Merge-into-existing (execute_lane1b_merge_group):
     os.rename(source_dir/item, canonical_path/item) — per-item rename.
     Used when the canonical category directory already exists.
     After all items moved, source_dir is removed if empty.

Client behavior (both paths):
  RT: repoint via rt_apply_directory_repoint(hash, canonical_path, restart=True)
      After repoint: polled until d.hashing=0, then verified complete=1 and
      down_rate=0. If RT starts downloading the group is flagged warn_downloading.
  qB: repoint via set_location(hash, canonical_path, resume_after=False)
      Stays paused — DO NOT resume.
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


def _rt_fetch_health(
    torrent_hash: str,
    rpc_url: str,
) -> dict:
    """
    Fetch RT torrent health fields in one snapshot.

    Returns dict with keys: complete (int), hashing (int), down_rate (int).
    Returns empty dict on RPC error.
    """
    try:
        return {
            "complete": int(_xmlrpc_scalar_text(
                rt_xmlrpc_call("d.complete", torrent_hash, rpc_url=rpc_url)
            ).strip()),
            "hashing": int(_xmlrpc_scalar_text(
                rt_xmlrpc_call("d.hashing", torrent_hash, rpc_url=rpc_url)
            ).strip()),
            "down_rate": int(_xmlrpc_scalar_text(
                rt_xmlrpc_call("d.down.rate", torrent_hash, rpc_url=rpc_url)
            ).strip()),
        }
    except Exception:
        return {}


def _rt_health_check(
    torrent_hash: str,
    rpc_url: str,
    poll_secs: float = 15.0,
) -> dict:
    """
    Poll RT until hashing clears, then verify complete=1 and down_rate=0.

    Returns:
      ok (bool)       — True if complete=1 and down_rate=0 after hashing clears
      complete (int)  — final d.complete value
      down_rate (int) — final d.down.rate value
      hashing (int)   — final d.hashing value
      note (str)      — human-readable status
    """
    polls = max(1, int(poll_secs / 0.5))
    fields: dict = {}

    for _ in range(polls):
        fields = _rt_fetch_health(torrent_hash, rpc_url)
        if not fields:
            return {"ok": False, "complete": -1, "down_rate": -1, "hashing": -1,
                    "note": "RPC error fetching RT health"}
        if fields["hashing"] == 0:
            break
        time.sleep(0.5)

    complete = fields.get("complete", -1)
    down_rate = fields.get("down_rate", -1)
    hashing = fields.get("hashing", -1)

    # If poll timed out but complete=1 and down_rate=0, RT is only verifying —
    # not downloading. Treat as ok; it will settle to stalledUP when done.
    if hashing != 0 and (complete != 1 or down_rate > 0):
        return {"ok": False, "complete": complete, "down_rate": down_rate,
                "hashing": hashing,
                "note": f"RT still hashing after {poll_secs:.0f}s poll and not complete or downloading"}
    if complete != 1 and hashing == 0:
        return {"ok": False, "complete": complete, "down_rate": down_rate,
                "hashing": hashing,
                "note": f"RT incomplete after hashing: complete={complete}"}
    if down_rate > 0 and hashing == 0:
        return {"ok": False, "complete": complete, "down_rate": down_rate,
                "hashing": hashing,
                "note": f"RT downloading after hashing: down_rate={down_rate}"}
    note = "RT seeding ok" if hashing == 0 else f"RT verifying (hashing={hashing}), complete=1 down_rate=0"
    return {"ok": True, "complete": complete, "down_rate": down_rate,
            "hashing": hashing, "note": note}


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

    # Check qB active downloads
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
                        f"active qB download in group: {h[:16]} state={qb_info.state}"
                    )
                    return result
            except Exception as e:
                result["errors"].append(
                    f"could not check qB state for {h[:16]}: {e}"
                )
                return result

    # Check RT not downloading pre-rename
    for it in group_items:
        h = it.get("hash", "")
        if not h:
            continue
        fields = _rt_fetch_health(h, rt_rpc_url)
        if not fields:
            continue  # RPC unavailable — don't block on transient error
        if fields.get("complete", 1) != 1 or fields.get("down_rate", 0) > 0:
            result["errors"].append(
                f"RT downloading pre-rename: {h[:16]} "
                f"complete={fields.get('complete')} down_rate={fields.get('down_rate')}"
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
                    rpc_url=rt_rpc_url, restart=True, check_before_start=True,
                    validate_target_exists=True,
                )
                # Verify RT directory
                rt_dir_xml = rt_xmlrpc_call("d.directory", h, rpc_url=rt_rpc_url)
                rt_dir = _xmlrpc_scalar_text(rt_dir_xml).rstrip("/")
                rt_canon = canonical_path.rstrip("/")
                if rt_dir == rt_canon or rt_dir.startswith(rt_canon + "/"):
                    # Poll until RT hash-check clears, then assert seeding (not downloading)
                    health = _rt_health_check(h, rt_rpc_url, poll_secs=15.0)
                    item_res["notes"].append(
                        f"RT directory={rt_dir} complete={health['complete']} "
                        f"down_rate={health['down_rate']} hashing={health['hashing']}"
                    )
                    if health["ok"]:
                        item_res["rt"] = "ok"
                    else:
                        item_res["rt"] = "warn_downloading"
                        item_res["notes"].append(f"RT health: {health['note']}")
                else:
                    item_res["rt"] = "failed"
                    item_res["notes"].append(
                        f"RT directory mismatch: got {rt_dir!r} expected {canonical_path!r}"
                    )
            except Exception as e:
                item_res["rt"] = "failed"
                item_res["notes"].append(f"RT repoint error: {e}")

        # qB set_location — always attempt even if RT warns, path must be corrected
        if h and qb_client:
            try:
                success = qb_client.set_location(h, canonical_path, resume_after=False)
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
                        # Save path confirmed — re-pause safety net
                        PAUSED_STATES = {"pausedUP", "stoppedUP", "pausedDL", "stoppedDL"}
                        state = qb_info.state or ""

                        # Wait for checkingUP to clear (up to 15s)
                        for _ in range(30):
                            if state != "checkingUP":
                                break
                            time.sleep(0.5)
                            try:
                                qb_info = qb_client.get_torrent_info(h)
                                state = (qb_info.state or "") if qb_info else ""
                            except Exception:
                                pass

                        # Re-pause if not already paused
                        if state not in PAUSED_STATES:
                            try:
                                qb_client.pause_torrent(h)
                            except Exception as e:
                                state = f"{state} (pause_called_err={e})"

                        # Poll up to 5s for paused state
                        for _ in range(10):
                            if state in PAUSED_STATES:
                                break
                            time.sleep(0.5)
                            try:
                                qb_info = qb_client.get_torrent_info(h)
                                state = (qb_info.state or "") if qb_info else ""
                            except Exception:
                                pass

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

    # Propagate any RT warn_downloading to group-level errors for visibility
    rt_warn = [it for it in result["items"] if it.get("rt") == "warn_downloading"]
    if rt_warn:
        result["errors"].append(
            f"RT downloading post-repoint: {len(rt_warn)} item(s) — "
            + ", ".join(it["hash"][:16] for it in rt_warn)
        )

    return result


def execute_lane1b_merge_group(
    group_items: list[dict],
    *,
    dry_run: bool = False,
    qb_client: Optional[QBittorrentClient] = None,
    rt_rpc_url: str = DEFAULT_RT_RPC_URL,
) -> dict:
    """
    Execute a single Lane 1b merge group (per-item rename into existing category dir).

    All items must share the same source_dir and canonical_path.
    The canonical_path MUST already exist (this is the merge-into-existing path).
    Each item is renamed individually: os.rename(source_dir/name, canonical_path/name).
    After all items, source_dir is removed if empty.

    RT and qB repoint logic is identical to execute_lane1_group_atomic.
    """
    if not group_items:
        return {
            "group_source": "",
            "group_canonical": "",
            "items_moved": 0,
            "source_removed": False,
            "items": [],
            "errors": [],
        }

    source_dir = group_items[0].get("source_dir", "")
    canonical_path = group_items[0].get("canonical_path", "")

    result: dict = {
        "group_source": source_dir,
        "group_canonical": canonical_path,
        "items_moved": 0,
        "source_removed": False,
        "items": [],
        "errors": [],
    }

    if dry_run:
        result["items"] = [
            {
                "hash": it.get("hash", ""),
                "name": it.get("name", ""),
                "source_item": os.path.join(source_dir, it.get("name", "")),
                "target_item": os.path.join(canonical_path, it.get("name", "")),
                "rt": "dry_run",
                "qb": "dry_run",
                "notes": ["dry-run: no mutations performed"],
            }
            for it in group_items
        ]
        return result

    # Pre-checks
    if not os.path.isdir(source_dir):
        result["errors"].append(f"source dir missing: {source_dir}")
        return result

    if not os.path.isdir(canonical_path):
        result["errors"].append(f"canonical dir missing (must exist for merge): {canonical_path}")
        return result

    # Verify no target item conflicts
    for it in group_items:
        target_item = os.path.join(canonical_path, it.get("name", ""))
        if os.path.exists(target_item):
            result["errors"].append(f"target item already exists: {target_item}")
            return result

    # Check qB active downloads
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
                        f"active qB download in group: {h[:16]} state={qb_info.state}"
                    )
                    return result
            except Exception as e:
                result["errors"].append(f"could not check qB state for {h[:16]}: {e}")
                return result

    # RT pre-flight: check not downloading
    for it in group_items:
        h = it.get("hash", "")
        if not h:
            continue
        fields = _rt_fetch_health(h, rt_rpc_url)
        if not fields:
            continue  # transient RPC error — don't block
        if fields.get("complete", 1) != 1 or fields.get("down_rate", 0) > 0:
            result["errors"].append(
                f"RT downloading pre-move: {h[:16]} "
                f"complete={fields.get('complete')} down_rate={fields.get('down_rate')}"
            )
            return result

    PAUSED_STATES = {"pausedUP", "stoppedUP", "pausedDL", "stoppedDL"}

    # Per-item rename + repoint
    for it in group_items:
        h = it.get("hash", "")
        name = it.get("name", "")
        source_item = os.path.join(source_dir, name)
        target_item = os.path.join(canonical_path, name)

        item_res: dict = {
            "hash": h,
            "name": name,
            "source_item": source_item,
            "target_item": target_item,
            "rt": "pending",
            "qb": "pending",
            "notes": [],
        }

        # Move the item (skip OS rename if already at target — cross-seed duplicate case)
        source_exists = os.path.exists(source_item)
        target_exists = os.path.exists(target_item)

        if not source_exists and not target_exists:
            item_res["rt"] = "skipped"
            item_res["qb"] = "skipped"
            item_res["notes"].append(f"source item missing: {source_item}")
            result["items"].append(item_res)
            continue

        if source_exists:
            try:
                os.rename(source_item, target_item)
                item_res["notes"].append(f"moved: {source_item} → {target_item}")
                result["items_moved"] += 1
            except OSError as e:
                item_res["rt"] = "failed"
                item_res["qb"] = "failed"
                item_res["notes"].append(f"rename failed: {e}")
                result["items"].append(item_res)
                result["errors"].append(f"rename failed for {name}: {e}")
                continue
        else:
            # target already exists — another item in this group moved it (cross-seed dup)
            item_res["notes"].append(f"already at target (cross-seed dup): {target_item}")
            result["items_moved"] += 1

        # RT repoint — same as lane1: set d.directory to canonical_path (category level)
        if h:
            try:
                rt_apply_directory_repoint(
                    h, canonical_path,
                    rpc_url=rt_rpc_url, restart=True, check_before_start=True,
                    validate_target_exists=True,
                )
                rt_dir_xml = rt_xmlrpc_call("d.directory", h, rpc_url=rt_rpc_url)
                rt_dir = _xmlrpc_scalar_text(rt_dir_xml).rstrip("/")
                rt_canon = canonical_path.rstrip("/")
                if rt_dir == rt_canon or rt_dir.startswith(rt_canon + "/"):
                    health = _rt_health_check(h, rt_rpc_url, poll_secs=15.0)
                    item_res["notes"].append(
                        f"RT directory={rt_dir} complete={health['complete']} "
                        f"down_rate={health['down_rate']} hashing={health['hashing']}"
                    )
                    item_res["rt"] = "ok" if health["ok"] else "warn_downloading"
                    if not health["ok"]:
                        item_res["notes"].append(f"RT health: {health['note']}")
                else:
                    item_res["rt"] = "failed"
                    item_res["notes"].append(
                        f"RT directory mismatch: got {rt_dir!r} expected prefix {canonical_path!r}"
                    )
            except Exception as e:
                item_res["rt"] = "failed"
                item_res["notes"].append(f"RT repoint error: {e}")

        # qB repoint — set save_path to canonical_path (category level), same as lane1
        if h and qb_client:
            try:
                success = qb_client.set_location(h, canonical_path, resume_after=False)
                if not success:
                    item_res["qb"] = "failed"
                    item_res["notes"].append("qB set_location returned False")
                else:
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
                        state = qb_info.state or ""
                        for _ in range(30):
                            if state != "checkingUP":
                                break
                            time.sleep(0.5)
                            try:
                                qb_info = qb_client.get_torrent_info(h)
                                state = (qb_info.state or "") if qb_info else ""
                            except Exception:
                                pass
                        if state not in PAUSED_STATES:
                            try:
                                qb_client.pause_torrent(h)
                            except Exception as e:
                                state = f"{state} (pause_err={e})"
                        for _ in range(10):
                            if state in PAUSED_STATES:
                                break
                            time.sleep(0.5)
                            try:
                                qb_info = qb_client.get_torrent_info(h)
                                state = (qb_info.state or "") if qb_info else ""
                            except Exception:
                                pass
                        item_res["notes"].append(f"qB save_path={canonical_path} state={state}")
                        item_res["qb"] = "ok" if state in PAUSED_STATES else "warn_not_paused"
                        if state not in PAUSED_STATES:
                            item_res["notes"].append(f"not paused after re-pause attempt: state={state}")
                    else:
                        item_res["qb"] = "failed"
                        item_res["notes"].append("qB save_path did not update after 10s poll")
            except Exception as e:
                item_res["qb"] = "failed"
                item_res["notes"].append(f"qB set_location error: {e}")

        result["items"].append(item_res)

    # Remove source dir if now empty
    try:
        remaining = os.listdir(source_dir)
        if not remaining:
            os.rmdir(source_dir)
            result["source_removed"] = True
        else:
            result["errors"].append(
                f"source dir not empty after merge ({len(remaining)} entries remain): {source_dir}"
            )
    except FileNotFoundError:
        result["source_removed"] = True  # already gone
    except OSError as e:
        result["errors"].append(f"could not remove source dir: {e}")

    # Propagate RT warn_downloading
    rt_warn = [it for it in result["items"] if it.get("rt") == "warn_downloading"]
    if rt_warn:
        result["errors"].append(
            f"RT downloading post-repoint: {len(rt_warn)} item(s) — "
            + ", ".join(it["hash"][:16] for it in rt_warn)
        )

    return result
