#!/usr/bin/env python3
"""repair_cross_seed_nested_stubs v1.0.0 — replace zero-byte stub files with hardlinks from nested subfolder."""

from __future__ import annotations

import argparse
import os
import sys
import xmlrpc.client
from pathlib import Path
from typing import Any

SCRIPT_NAME = "repair_cross_seed_nested_stubs"
VERSION = "1.0.0"

RPC_URL = "http://127.0.0.1:18000/"
CONTAINER_TO_HOST = {"/data/media/": "/stash/media/"}


def host_path(p: str) -> str:
    for container_prefix, host_prefix in CONTAINER_TO_HOST.items():
        if p.startswith(container_prefix):
            return p.replace(container_prefix, host_prefix, 1)
    return p


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def scan_item(hdir: str) -> tuple[dict[str, tuple[str, int, int]], dict[str, tuple[str, int, int]]]:
    root_files: dict[str, tuple[str, int, int]] = {}
    nested_files: dict[str, tuple[str, int, int]] = {}
    try:
        entries = os.listdir(hdir)
    except PermissionError:
        return root_files, nested_files
    except FileNotFoundError:
        return root_files, nested_files

    for f in entries:
        fp = os.path.join(hdir, f)
        try:
            if os.path.isfile(fp):
                st = os.stat(fp)
                root_files[f] = (fp, st.st_size, st.st_nlink)
            elif os.path.isdir(fp):
                for nested_f in os.listdir(fp):
                    nfp = os.path.join(fp, nested_f)
                    if os.path.isfile(nfp):
                        nst = os.stat(nfp)
                        nested_files[nested_f] = (nfp, nst.st_size, nst.st_nlink)
        except OSError:
            continue

    return root_files, nested_files


def build_ops(
    root_files: dict[str, tuple[str, int, int]],
    nested_files: dict[str, tuple[str, int, int]],
) -> list[tuple[str, str, str | None, int]]:
    ops: list[tuple[str, str, str | None, int]] = []
    for fname, (root_fp, root_sz, root_nl) in root_files.items():
        if root_sz == 0:
            if fname in nested_files:
                nested_fp, nested_sz, nested_nl = nested_files[fname]
                if nested_sz > 0:
                    ops.append(("hardlink_stub", root_fp, nested_fp, nested_sz))
                else:
                    ops.append(("skip_nested_also_zero", root_fp, None, 0))
            else:
                ops.append(("skip_no_nested_match", root_fp, None, 0))
        elif root_sz > 0 and root_nl == 1:
            if fname in nested_files:
                nested_fp, nested_sz, nested_nl = nested_files[fname]
                if nested_sz == root_sz:
                    ops.append(("replace_downloaded_with_hardlink", root_fp, nested_fp, nested_sz))
                else:
                    ops.append(("skip_size_mismatch", root_fp, nested_fp, nested_sz))
    return ops


def print_item_header(h: str, name: str, ops: list[tuple[str, str, str | None, int]]) -> None:
    print(f"\nITEM {h}")
    print(f"  {name}")
    for op_type, root_fp, nested_fp, size in ops:
        basename = os.path.basename(root_fp)
        if op_type == "hardlink_stub":
            print(f"  hardlink_stub:                  {basename}  ({format_size(size)} from nested)")
        elif op_type == "replace_downloaded_with_hardlink":
            print(f"  replace_downloaded_with_hardlink: {basename}  ({format_size(size)} from nested)")
        elif op_type == "skip_no_nested_match":
            print(f"  skip_no_nested_match:            {basename}  (0 bytes — no nested match)")
        elif op_type == "skip_nested_also_zero":
            print(f"  skip_nested_also_zero:            {basename}  (nested also zero bytes)")
        elif op_type == "skip_size_mismatch":
            print(f"  skip_size_mismatch:              {basename}  (nested size {format_size(size)} differs)")


def execute_ops(ops: list[tuple[str, str, str | None, int]]) -> list[str]:
    link_failures = 0
    results: list[str] = []
    for op_type, root_fp, nested_fp, size in ops:
        if op_type == "hardlink_stub":
            try:
                os.unlink(root_fp)
                os.link(nested_fp, root_fp)
                st = os.stat(root_fp)
                if st.st_size != size:
                    raise OSError(f"size mismatch after hardlink: expected {size}, got {st.st_size}")
                results.append(f"  DONE hardlink_stub: {os.path.basename(root_fp)} ({format_size(size)})")
            except OSError as exc:
                link_failures += 1
                results.append(f"  FAIL hardlink_stub: {os.path.basename(root_fp)} — {exc}")
                if link_failures > 3:
                    results.append("  ABORT: too many hardlink failures")
                    break
        elif op_type == "replace_downloaded_with_hardlink":
            try:
                os.unlink(root_fp)
                os.link(nested_fp, root_fp)
                st = os.stat(root_fp)
                if st.st_size != size:
                    raise OSError(f"size mismatch after hardlink: expected {size}, got {st.st_size}")
                results.append(f"  DONE replace_downloaded_with_hardlink: {os.path.basename(root_fp)} ({format_size(size)})")
            except OSError as exc:
                link_failures += 1
                results.append(f"  FAIL replace_downloaded_with_hardlink: {os.path.basename(root_fp)} — {exc}")
                if link_failures > 3:
                    results.append("  ABORT: too many hardlink failures")
                    break
        elif op_type in ("skip_no_nested_match", "skip_nested_also_zero", "skip_size_mismatch"):
            results.append(f"  SKIP {op_type}: {os.path.basename(root_fp)}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"{SCRIPT_NAME} v{VERSION} — replace zero-byte stubs with hardlinks from nested subfolder",
    )
    parser.add_argument("--dry-run", action="store_true", default=True, help="Default. List planned operations; touch nothing.")
    parser.add_argument("--execute", action="store_true", help="Perform hardlinks. Requires explicit flag.")
    parser.add_argument("--hash", type=str, default=None, help="Process only this RT torrent hash (40-char uppercase).")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N items.")
    parser.add_argument("--rpc-url", type=str, default=RPC_URL, help=f"RT XMLRPC URL (default: {RPC_URL}).")
    args = parser.parse_args(argv)

    execute_mode = args.execute
    if execute_mode:
        args.dry_run = False

    prefix = "[EXECUTE]" if execute_mode else "[DRY-RUN]"
    print(f"{prefix} {SCRIPT_NAME} v{VERSION}")
    print()

    proxy = xmlrpc.client.ServerProxy(args.rpc_url)
    stopped = proxy.download_list("", "stopped")

    items_scanned = 0
    items_with_ops = 0
    items_fully_fixable = 0
    items_partial = 0
    items_unchanged = 0
    counts: dict[str, int] = {}
    partial_names: list[str] = []

    for h in stopped:
        if args.hash and h != args.hash:
            continue
        if args.limit is not None and items_scanned >= args.limit:
            break

        items_scanned += 1
        name = proxy.d.name(h)
        directory = proxy.d.directory(h)
        hdir = host_path(directory)

        if not os.path.exists(hdir):
            continue

        root_files, nested_files = scan_item(hdir)
        ops = build_ops(root_files, nested_files)

        if not ops:
            items_unchanged += 1
            continue

        items_with_ops += 1
        has_skip = any(
            op[0] in ("skip_no_nested_match", "skip_nested_also_zero", "skip_size_mismatch")
            for op in ops
        )
        if has_skip:
            items_partial += 1
            partial_names.append(name)
        else:
            items_fully_fixable += 1

        print_item_header(h, name, ops)

        if execute_mode:
            exec_results = execute_ops(ops)
            for r in exec_results:
                print(r)
            abort = any(r.startswith("  ABORT") for r in exec_results)
            if abort:
                print("\n  ABORTED due to failures")
                break

        for op_type, _, _, _ in ops:
            counts[op_type] = counts.get(op_type, 0) + 1

    print()
    print("SUMMARY")
    print(f"  items_scanned:   {items_scanned}")
    print(f"  items_with_ops:  {items_with_ops}")
    for op_type in ("hardlink_stub", "replace_downloaded_with_hardlink", "skip_no_nested_match",
                     "skip_nested_also_zero", "skip_size_mismatch"):
        print(f"  {op_type}: {counts.get(op_type, 0)}")
    print(f"  items_fully_fixable:    {items_fully_fixable}")
    if items_partial:
        for pn in partial_names:
            print(f"  items_partial:   {items_partial}   ({pn})")
    else:
        print(f"  items_partial:   {items_partial}")
    print(f"  items_unchanged: {items_unchanged}  (no ops needed)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
