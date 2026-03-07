#!/usr/bin/env python3
# Script name: qb-path-watch.py
# Version: 0.3.0
# Last-updated: 2026-03-07T15:20:00-05:00

# v0.2.1: Rename script to qb-path-watch.py.
# v0.2.1: Rename credential env vars to QBITTORRENTAPI_USERNAME and QBITTORRENTAPI_PASSWORD.
# v0.3.0: Add shared qB cache support and make cache reads the default path.

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar


SCRIPT_NAME = "qb-path-watch.py"
SCRIPT_VERSION = "0.3.0"
SCRIPT_UPDATED = "2026-03-07T15:20:00-05:00"
CACHE_AGENT_DEFAULT = os.environ.get(
    "QBIT_CACHE_AGENT",
    os.path.join(os.path.dirname(__file__), "qb-cache-agent.py"),
)


def print_lifecycle(status: str) -> None:
    print(
        f"script_name={SCRIPT_NAME} version={SCRIPT_VERSION} "
        f"updated={SCRIPT_UPDATED} status={status}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch qBittorrent torrents by save path and moving state.",
        epilog=(
            "Examples:\n"
            "  ./qb-path-watch.py --host http://localhost:9003 -U admin -P 'secret'\n\n"
            "  ./qb-path-watch.py -H http://localhost:9003 -U admin -P 'secret' -i 5\n\n"
            "  export QBITTORRENTAPI_USERNAME='admin'\n"
            "  export QBITTORRENTAPI_PASSWORD='secret'\n"
            "  ./qb-path-watch.py --host http://localhost:9003\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "-H", "--host",
        default="http://localhost:9003",
        help="qBittorrent base URL (default: http://localhost:9003)",
    )
    parser.add_argument(
        "-U", "--username",
        default=os.environ.get("QBITTORRENTAPI_USERNAME", ""),
        help="qBittorrent WebUI username (default: from QBITTORRENTAPI_USERNAME)",
    )
    parser.add_argument(
        "-P", "--password",
        default=os.environ.get("QBITTORRENTAPI_PASSWORD", ""),
        help="qBittorrent WebUI password (default: from QBITTORRENTAPI_PASSWORD)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=int,
        default=10,
        help="Refresh interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--old-path-match",
        default="/pool/data/media/",
        help="Substring identifying the old save path",
    )
    parser.add_argument(
        "--new-path-match",
        default="/pool/media/",
        help="Substring identifying the new save path",
    )
    parser.add_argument(
        "--old-du-path",
        default="/pool/data/media/torrents/seeding",
        help="Filesystem path to measure for old disk usage",
    )
    parser.add_argument(
        "--new-du-path",
        default="/pool/media/torrents/seeding",
        help="Filesystem path to measure for new disk usage",
    )
    parser.add_argument(
        "--use-cache",
        dest="use_cache",
        action="store_true",
        default=True,
        help="Read torrents/info from the shared qB cache agent (default: enabled)",
    )
    parser.add_argument(
        "--no-use-cache",
        dest="use_cache",
        action="store_false",
        help="Disable shared cache and query the qB WebUI API directly",
    )
    parser.add_argument(
        "--cache-agent-cmd",
        default=CACHE_AGENT_DEFAULT,
        help=f"Path to qb/qbit cache agent (default: {CACHE_AGENT_DEFAULT})",
    )
    parser.add_argument(
        "--cache-max-age",
        type=int,
        default=15,
        help="Max cache age seconds (default: 15)",
    )
    parser.add_argument(
        "--cache-wait-fresh",
        type=int,
        default=5,
        help="Seconds to wait for a fresh cache snapshot when stale (default: 5)",
    )
    parser.add_argument(
        "--cache-client-id",
        default=f"{SCRIPT_NAME}:{os.getpid()}",
        help="Client id to use when leasing the shared cache",
    )

    return parser.parse_args()


def build_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )
    return opener, cookie_jar


def join_url(host: str, path: str) -> str:
    return host.rstrip("/") + path


def login(opener: urllib.request.OpenerDirector, host: str, username: str, password: str) -> None:
    # v0.2.0: Perform documented cookie-based login and store SID in cookie jar.
    url = join_url(host, "/api/v2/auth/login")
    payload = urllib.parse.urlencode(
        {"username": username, "password": password}
    ).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with opener.open(req, timeout=15) as response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8").strip()

    if body == "Fails.":
        raise RuntimeError("login_failed invalid_credentials_or_auth_rejected")


def fetch_torrents(opener: urllib.request.OpenerDirector, host: str) -> list[dict]:
    url = join_url(host, "/api/v2/torrents/info?filter=all")
    req = urllib.request.Request(url, method="GET")

    with opener.open(req, timeout=15) as response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8")
        data = json.loads(body)

    if not isinstance(data, list):
        raise ValueError("api_response_not_json_list")

    return data


def fetch_torrents_from_cache(args: argparse.Namespace) -> list[dict]:
    cmd = [
        args.cache_agent_cmd,
        "--max-age",
        str(args.cache_max_age),
        "--wait-fresh",
        str(args.cache_wait_fresh),
        "--client-id",
        args.cache_client_id,
        "--requested-interval",
        str(max(args.interval, 1)),
        "--ensure-daemon",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit_{result.returncode}"
        raise RuntimeError(f"cache_agent_failed detail={detail}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cache_agent_json_decode_failed reason={exc}") from exc
    if not isinstance(data, list):
        raise ValueError("cache_agent_response_not_json_list")
    return data


def get_du_size(path: str) -> str:
    # v0.2.0: Preserve original du -sh behavior when available.
    if shutil.which("du"):
        try:
            result = subprocess.run(
                ["du", "-sh", path],
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout.strip()
            if output:
                return output.split()[0]
        except Exception:
            pass
    return "N/A"


def summarize(
    torrents: list[dict],
    old_path_match: str,
    new_path_match: str,
    old_du_path: str,
    new_du_path: str,
) -> None:
    old = [t for t in torrents if old_path_match in t.get("save_path", "")]
    new = [
        t for t in torrents
        if new_path_match in t.get("save_path", "")
        and old_path_match not in t.get("save_path", "")
    ]
    moving = [t for t in torrents if t.get("state") == "moving"]

    du_old = get_du_size(old_du_path)
    du_new = get_du_size(new_du_path)

    print("\n[📊 Summary]")
    print(
        f"old_path_count={len(old)} "
        f"new_path_count={len(new)} "
        f"moving_count={len(moving)}"
    )
    print(
        f"old_disk_usage={du_old} "
        f"new_disk_usage={du_new}"
    )


def main() -> int:
    args = parse_args()

    if args.interval <= 0:
        print("error=invalid_interval value_must_be_gt_0", file=sys.stderr)
        return 1

    if args.cache_max_age < 0:
        print("error=invalid_cache_max_age value_must_be_gte_0", file=sys.stderr)
        return 1

    if args.cache_wait_fresh < 0:
        print("error=invalid_cache_wait_fresh value_must_be_gte_0", file=sys.stderr)
        return 1

    if args.use_cache and not os.path.exists(args.cache_agent_cmd):
        print(
            f"error=missing_cache_agent hint='set --cache-agent-cmd' path={args.cache_agent_cmd}",
            file=sys.stderr,
        )
        return 1

    if not args.use_cache and not args.username:
        print(
            "error=missing_username hint='pass --username or set QBITTORRENTAPI_USERNAME'",
            file=sys.stderr,
        )
        return 1

    if not args.use_cache and not args.password:
        print(
            "error=missing_password hint='pass --password or set QBITTORRENTAPI_PASSWORD'",
            file=sys.stderr,
        )
        return 1

    print_lifecycle("start")

    opener, _cookie_jar = build_opener()

    try:
        if args.use_cache:
            print(
                "fetch_mode=shared_cache "
                f"cache_agent={args.cache_agent_cmd} "
                f"cache_max_age={args.cache_max_age} "
                f"cache_wait_fresh={args.cache_wait_fresh}"
            )
        else:
            login(opener, args.host, args.username, args.password)
            print("auth_status=ok method=session_cookie")

        while True:
            if args.use_cache:
                torrents = fetch_torrents_from_cache(args)
            else:
                try:
                    torrents = fetch_torrents(opener, args.host)
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        print(f"auth_status=retry reason=http_{exc.code}", file=sys.stderr)
                        login(opener, args.host, args.username, args.password)
                        torrents = fetch_torrents(opener, args.host)
                    else:
                        raise

            summarize(
                torrents=torrents,
                old_path_match=args.old_path_match,
                new_path_match=args.new_path_match,
                old_du_path=args.old_du_path,
                new_du_path=args.new_du_path,
            )

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nstatus=interrupted reason=keyboard_interrupt")
    except urllib.error.URLError as exc:
        print(f"error=request_failed reason={exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error=json_decode_failed reason={exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error=unexpected_failure reason={exc}", file=sys.stderr)
        return 1
    finally:
        print_lifecycle("end")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
