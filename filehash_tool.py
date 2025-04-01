#!/usr/bin/env python3
# filehash_tool.py (rev v0.3.7)

import argparse
import sys

TOOL_VERSION = "v0.3.7"

def run_scan(args):
    print(f"🔍 Running scan on root: {args.root} [rev {TOOL_VERSION}]")

def run_verify(args):
    mode = "full" if args.full else "fast"
    print(f"🔁 Running {mode} verify [rev {TOOL_VERSION}]")

def run_clean(args):
    print(f"🧹 Cleaning stale records [rev {TOOL_VERSION}]")

def run_tree(args):
    print(f"🌲 Building folder signature hashes [rev {TOOL_VERSION}]")

def main():
    parser = argparse.ArgumentParser(description=f"filehash_tool.py (rev {TOOL_VERSION})")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan directory and hash files")
    p_scan.add_argument("root", help="Directory root to scan")
    p_scan.set_defaults(func=run_scan)

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify file hashes")
    p_verify.add_argument("--full", action="store_true", help="Force full hash verify")
    p_verify.set_defaults(func=run_verify)

    # clean
    p_clean = subparsers.add_parser("clean", help="Clean removed/missing entries")
    p_clean.set_defaults(func=run_clean)

    # tree
    p_tree = subparsers.add_parser("tree", help="Build folder signature hashes")
    p_tree.set_defaults(func=run_tree)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
