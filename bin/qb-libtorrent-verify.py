#!/usr/bin/env python3
"""Offline torrent verification helper using libtorrent.

This validates whether existing data on disk can satisfy a .torrent payload
without relying on qBittorrent recheck behavior.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def maybe_reexec_system_python() -> None:
    if os.environ.get("HASHALL_NO_SYSTEM_PYTHON", "0").strip() in {"1", "true", "yes", "on"}:
        return
    if sys.executable == "/usr/bin/python3":
        return
    system_python = Path("/usr/bin/python3")
    if not system_python.exists():
        return
    # Re-exec using system Python so apt-installed python3-libtorrent is importable.
    os.execv(str(system_python), [str(system_python), *sys.argv])


def import_libtorrent():
    try:
        import libtorrent as lt  # type: ignore
        return lt
    except ModuleNotFoundError:
        maybe_reexec_system_python()
        import libtorrent as lt  # type: ignore
        return lt


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Verify torrent payload compatibility against candidate paths with libtorrent."
    )
    p.add_argument("--torrent", required=True, help="Path to .torrent file")
    p.add_argument(
        "--path",
        action="append",
        dest="paths",
        required=True,
        help="Candidate data path (repeatable)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Max seconds per candidate verify (default: 1800)",
    )
    p.add_argument(
        "--poll",
        type=float,
        default=1.0,
        help="Status poll interval seconds (default: 1)",
    )
    p.add_argument(
        "--show-progress",
        action="store_true",
        help="Print periodic progress lines while verifying",
    )
    p.add_argument(
        "--json-out",
        default="",
        help="Optional JSON output path",
    )
    p.add_argument(
        "--quiet-summary",
        action="store_true",
        help="Suppress final summary/report lines (for caller-managed UX)",
    )
    p.add_argument(
        "--quick-only",
        action="store_true",
        help="Only do file-tree quick comparison (no piece hash verify)",
    )
    return p


@dataclass(frozen=True)
class TorrentShape:
    entries: Tuple[Tuple[str, int], ...]
    top_root: str
    is_single_file: bool


def torrent_shape(lt, torrent_path: Path) -> tuple[object, TorrentShape]:
    ti = lt.torrent_info(str(torrent_path))
    files = ti.files()
    out: List[Tuple[str, int]] = []
    for i in range(files.num_files()):
        rel = str(files.file_path(i) or "").replace("\\", "/")
        rel = rel.lstrip("./").lstrip("/")
        if not rel:
            continue
        out.append((rel, int(files.file_size(i))))
    out.sort(key=lambda item: item[0])
    roots = {rel.split("/", 1)[0] for rel, _ in out}
    top_root = list(roots)[0] if len(roots) == 1 else ""
    is_single = len(out) == 1 and "/" not in out[0][0]
    shape = TorrentShape(entries=tuple(out), top_root=top_root, is_single_file=is_single)
    return ti, shape


def candidate_save_path(candidate: Path, shape: TorrentShape) -> Tuple[Path, str]:
    if shape.is_single_file:
        if candidate.is_file():
            return candidate.parent, "candidate_file"
        return candidate, "candidate_dir"
    if candidate.is_dir() and shape.top_root and candidate.name == shape.top_root:
        return candidate.parent, "candidate_is_top_root"
    if candidate.is_file():
        return candidate.parent, "candidate_file_parent"
    return candidate, "candidate_dir"


def build_actual_map(candidate: Path, shape: TorrentShape) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if shape.is_single_file:
        expected_name = shape.entries[0][0]
        if candidate.is_file():
            # Verifier runs single-file candidates with save_path=candidate.parent.
            # Mirror that behavior here to avoid false quick=0 when the expected
            # filename exists as a sibling of the provided candidate file.
            sibling_expected = candidate.parent / expected_name
            if sibling_expected.is_file():
                out[expected_name] = int(sibling_expected.stat().st_size)
                return out
            out[candidate.name] = int(candidate.stat().st_size)
            return out
        single = candidate / expected_name
        if single.is_file():
            out[expected_name] = int(single.stat().st_size)
            return out

    if candidate.is_file():
        out[candidate.name] = int(candidate.stat().st_size)
        return out

    base = candidate.parent if (candidate.is_dir() and shape.top_root and candidate.name == shape.top_root) else candidate
    for file_path in candidate.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            rel = file_path.relative_to(base).as_posix()
        except Exception:
            rel = file_path.name
        out[rel] = int(file_path.stat().st_size)
    return out


def quick_compare(candidate: Path, shape: TorrentShape) -> dict:
    expected = {rel: size for rel, size in shape.entries}
    actual = build_actual_map(candidate, shape)
    wanted_bytes = int(sum(expected.values()))
    matched_bytes = int(
        sum(size for rel, size in expected.items() if int(actual.get(rel, -1)) == int(size))
    )
    missing_count = int(sum(1 for rel, size in expected.items() if int(actual.get(rel, -1)) != int(size)))
    extra_count = int(sum(1 for rel in actual.keys() if rel not in expected))
    exact_tree = bool(expected == actual)
    exp_sizes = Counter(int(v) for v in expected.values() if int(v) > 0)
    act_sizes = Counter(int(v) for v in actual.values() if int(v) > 0)
    size_overlap_bytes = int(
        sum(int(size) * min(int(exp_sizes[size]), int(act_sizes.get(size, 0))) for size in exp_sizes.keys())
    )
    return {
        "expected_files": len(expected),
        "actual_files": len(actual),
        "wanted_bytes": wanted_bytes,
        "matched_bytes_quick": matched_bytes,
        "size_overlap_bytes": size_overlap_bytes,
        "missing_count_quick": missing_count,
        "extra_count_quick": extra_count,
        "quick_ratio": float(matched_bytes / wanted_bytes) if wanted_bytes > 0 else 0.0,
        "size_overlap_ratio": float(size_overlap_bytes / wanted_bytes) if wanted_bytes > 0 else 0.0,
        "exact_tree": exact_tree,
    }


def status_state_name(lt, state_value: int) -> str:
    names = {
        int(lt.torrent_status.queued_for_checking): "queued_for_checking",
        int(lt.torrent_status.checking_files): "checking_files",
        int(lt.torrent_status.downloading_metadata): "downloading_metadata",
        int(lt.torrent_status.downloading): "downloading",
        int(lt.torrent_status.finished): "finished",
        int(lt.torrent_status.seeding): "seeding",
        int(lt.torrent_status.allocating): "allocating",
        int(lt.torrent_status.checking_resume_data): "checking_resume_data",
    }
    return names.get(int(state_value), f"state_{state_value}")


def format_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    try:
        total = int(round(float(seconds)))
    except Exception:
        return "--:--:--"
    if total < 0:
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def progress_bar(ratio: float, width: int = 28) -> str:
    clamped = max(0.0, min(1.0, float(ratio)))
    filled = int(round(clamped * width))
    filled = max(0, min(width, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def compact_label(label: str, max_len: int = 96) -> str:
    raw = str(label or "")
    text = Path(raw).name or raw
    if len(text) <= max_len:
        return text
    keep = max(8, max_len - 3)
    return text[:keep] + "..."


def gib(n: int) -> float:
    return float(n) / float(1024 ** 3)


def emit_progress_line(
    line: str,
    *,
    interactive: bool,
    final: bool,
    last_len: int,
) -> int:
    if not interactive:
        print(line, flush=True)
        return 0
    text = str(line)
    pad = " " * max(0, last_len - len(text))
    sys.stdout.write("\r" + text + pad)
    sys.stdout.flush()
    next_len = len(text)
    if final:
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    return next_len


def verify_candidate(lt, ti, save_path: Path, timeout_s: float, poll_s: float, show_progress: bool, label: str) -> dict:
    session = lt.session()
    try:
        # Disable discovery/network side effects; this is a local hash check pass.
        session.apply_settings(
            {
                "enable_dht": False,
                "enable_lsd": False,
                "enable_upnp": False,
                "enable_natpmp": False,
                "announce_to_all_trackers": False,
                "announce_to_all_tiers": False,
                "active_downloads": 0,
                "active_seeds": 0,
            }
        )
    except Exception:
        pass

    flags = int(lt.torrent_flags.paused | lt.torrent_flags.auto_managed | lt.torrent_flags.upload_mode)
    handle = session.add_torrent(
        {
            "ti": ti,
            "save_path": str(save_path),
            "flags": flags,
        }
    )
    handle.pause()
    handle.force_recheck()

    start = time.monotonic()
    next_print = start
    timed_out = False
    seen_checking_files = False
    last_state = ""
    wanted = 0
    done = 0
    ratio = 0.0
    short_label = compact_label(label, max_len=42)
    progress_interactive = bool(show_progress and sys.stdout.isatty())
    progress_last_len = 0
    last_emitted_state = ""
    last_emitted_pct_tenths = -1
    last_emit_ts = 0.0

    queued_for_checking = int(lt.torrent_status.queued_for_checking)
    checking_resume_data = int(lt.torrent_status.checking_resume_data)
    checking_files = int(lt.torrent_status.checking_files)
    pending_states = {queued_for_checking, checking_resume_data}
    recheck_start_grace = max(3.0, min(30.0, float(poll_s) * 8.0))

    while True:
        status = handle.status()
        state_value = int(getattr(status, "state", -1))
        state_name = status_state_name(lt, state_value)
        wanted = int(getattr(status, "total_wanted", 0) or 0)
        done = int(getattr(status, "total_wanted_done", getattr(status, "total_done", 0)) or 0)
        ratio = float(done / wanted) if wanted > 0 else float(getattr(status, "progress", 0.0) or 0.0)
        last_state = state_name
        if state_value == checking_files:
            seen_checking_files = True

        now = time.monotonic()
        if show_progress and now >= next_print:
            elapsed_s = max(0.0, now - start)
            eta_s: Optional[float] = None
            if wanted > 0 and 0 < done < wanted and elapsed_s > 0.0:
                rate = float(done) / elapsed_s
                if rate > 0.0:
                    eta_s = float(wanted - done) / rate
            bar = progress_bar(ratio)
            pct_tenths = int((ratio * 1000.0) + 0.5)
            should_emit = False
            if last_emitted_state != state_name:
                should_emit = True
            elif last_emitted_pct_tenths != pct_tenths:
                should_emit = True
            elif now - last_emit_ts >= 10.0:
                should_emit = True
            if should_emit:
                progress_last_len = emit_progress_line(
                    f"verify_progress item={short_label} state={state_name} "
                    f"{bar} {ratio * 100.0:6.2f}% "
                    f"elapsed={format_hms(elapsed_s)} eta={format_hms(eta_s)} "
                    f"gib={gib(done):.2f}/{gib(wanted):.2f}",
                    interactive=progress_interactive,
                    final=False,
                    last_len=progress_last_len,
                )
                last_emitted_state = state_name
                last_emitted_pct_tenths = int(pct_tenths)
                last_emit_ts = float(now)
            next_print = now + max(0.2, poll_s)

        if now - start >= timeout_s:
            timed_out = True
            break
        if state_value in pending_states or state_value == checking_files:
            time.sleep(max(0.1, poll_s))
            continue
        if seen_checking_files:
            break
        # Do not trust preloaded resume-data completion until we have seen a
        # real checking_files transition from force_recheck().
        if now - start < recheck_start_grace:
            time.sleep(max(0.1, poll_s))
            continue
        break

    elapsed = float(time.monotonic() - start)
    verified = bool(wanted > 0 and done >= wanted and not timed_out and seen_checking_files)
    if timed_out:
        verify_reason = "timeout"
    elif seen_checking_files:
        verify_reason = "checked_files"
    elif done <= 0 and last_state in {"downloading", "downloading_metadata"}:
        verify_reason = "fast_fail_no_data"
    else:
        verify_reason = "no_recheck_transition"
    if show_progress:
        final_eta = 0.0 if wanted > 0 and done >= wanted else None
        _ = emit_progress_line(
            f"verify_progress item={short_label} state={last_state} "
            f"{progress_bar(ratio)} {ratio * 100.0:6.2f}% "
            f"elapsed={format_hms(elapsed)} eta={format_hms(final_eta)} "
            f"gib={gib(done):.2f}/{gib(wanted):.2f} final=true",
            interactive=progress_interactive,
            final=True,
            last_len=progress_last_len,
        )
    try:
        session.remove_torrent(handle)
    except Exception:
        pass

    return {
        "verified": verified,
        "timed_out": timed_out,
        "verify_state": last_state,
        "verify_done": int(done),
        "verify_wanted": int(wanted),
        "verify_ratio": float(ratio),
        "verify_elapsed_s": round(elapsed, 3),
        "verify_reason": verify_reason,
        "seen_checking_files": bool(seen_checking_files),
    }


def classify_result(verified: bool, exact_tree: bool, ratio: float) -> str:
    if verified and exact_tree:
        return "exact_tree"
    if verified:
        return "close_match"
    if ratio > 0.0:
        return "partial_match"
    return "no_match"


def main() -> int:
    args = build_parser().parse_args()
    lt = import_libtorrent()

    torrent_path = Path(args.torrent).expanduser()
    if not torrent_path.exists():
        print(f"ERROR torrent_not_found path={torrent_path}")
        return 2

    ti, shape = torrent_shape(lt, torrent_path)
    out_results: List[dict] = []

    for raw in args.paths:
        candidate = Path(raw).expanduser()
        item = {
            "path": str(candidate),
            "exists": bool(candidate.exists()),
        }
        if not candidate.exists():
            item.update(
                {
                    "classification": "no_match",
                    "reason": "path_not_found",
                    "verified": False,
                    "verify_ratio": 0.0,
                    "exact_tree": False,
                }
            )
            out_results.append(item)
            continue

        save_path, save_mode = candidate_save_path(candidate, shape)
        quick = quick_compare(candidate, shape)
        if args.quick_only:
            verify = {
                "verified": False,
                "timed_out": False,
                "verify_state": "quick_only",
                "verify_done": 0,
                "verify_wanted": int(quick.get("wanted_bytes", 0) or 0),
                "verify_ratio": float(quick.get("quick_ratio", 0.0) or 0.0),
                "verify_elapsed_s": 0.0,
                "verify_reason": "quick_only",
                "seen_checking_files": False,
            }
        else:
            verify = verify_candidate(
                lt=lt,
                ti=ti,
                save_path=save_path,
                timeout_s=float(args.timeout),
                poll_s=float(args.poll),
                show_progress=bool(args.show_progress),
                label=str(candidate),
            )
        classification = classify_result(
            verified=bool(verify["verified"]),
            exact_tree=bool(quick["exact_tree"]),
            ratio=float(verify["verify_ratio"]),
        )
        item.update(
            {
                "save_path_for_verify": str(save_path),
                "save_mode": save_mode,
                **quick,
                **verify,
                "classification": classification,
            }
        )
        out_results.append(item)

    out_results.sort(
        key=lambda r: (
            1 if r.get("verified") else 0,
            float(r.get("verify_ratio", 0.0)),
            1 if r.get("exact_tree") else 0,
        ),
        reverse=True,
    )

    payload = {
        "tool": "qb-libtorrent-verify",
        "generated_at": ts_iso(),
        "python": sys.executable,
        "torrent": str(torrent_path),
        "shape": {
            "file_count": len(shape.entries),
            "top_root": shape.top_root,
            "is_single_file": shape.is_single_file,
            "total_bytes": int(sum(size for _, size in shape.entries)),
        },
        "results": out_results,
        "summary": {
            "candidates": len(out_results),
            "verified": int(sum(1 for r in out_results if r.get("verified"))),
            "partial": int(sum(1 for r in out_results if r.get("classification") == "partial_match")),
            "best_classification": out_results[0]["classification"] if out_results else "no_match",
            "best_path": out_results[0]["path"] if out_results else "",
        },
    }

    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not args.quiet_summary:
        best = payload["summary"]["best_classification"]
        print(
            f"summary candidates={payload['summary']['candidates']} "
            f"verified={payload['summary']['verified']} partial={payload['summary']['partial']} "
            f"best_classification={best} best_path={payload['summary']['best_path']}"
        )
        if args.json_out:
            print(f"report_json={Path(args.json_out).expanduser()}")

    if args.quick_only:
        return 0
    return 0 if payload["summary"]["verified"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
