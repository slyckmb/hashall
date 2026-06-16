#!/usr/bin/env python3
"""Search all prowlarr Torznab indexers from CLI.

Usage:
    ps.py <search query>
    ps.py "Saturday Night Live S51E18"

Searches every enabled Torznab-capable indexer in parallel (10 workers)
via prowlarr's per-indexer API at /{id}/api?t=search&q=...
"""

import sys, json, subprocess, re, html
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

query = sys.argv[1] if len(sys.argv) > 1 else sys.exit(f"Usage: {sys.argv[0]} <query>")
API_KEY = "722e1228a4314380b07b2a813d8dc0c3"

out = subprocess.run(
    ["docker", "exec", "prowlarr", "curl", "-s",
     f"http://localhost:9696/api/v1/indexer?apikey={API_KEY}"],
    capture_output=True, text=True, timeout=10
).stdout
idxrs = json.loads(out)
results = []


def search_indexer(i):
    if not i.get("enable") or i.get("protocol") != "torrent":
        return []
    iid, name = i["id"], i["name"]
    q = quote(query)
    cmd = (
        f"curl -s --max-time 10 "
        f"'http://localhost:9696/{iid}/api?apikey={API_KEY}&t=search&q={q}&limit=10'"
    )
    try:
        out = subprocess.run(
            ["docker", "exec", "prowlarr", "sh", "-c", cmd],
            capture_output=True, text=True, timeout=12
        ).stdout
    except:
        return []
    items = [
        x for x in re.split(r"<item>|</item>", out)
        if "<title>" in x and "<title>Prowlarr</title>" not in x
    ]
    found = []
    for item in items[:5]:
        m = re.search(r"<title>(.*?)</title>", item)
        title = html.unescape(m.group(1)) if m else "?"
        m = re.search(r"<size>(\d+)</size>", item)
        size = round(int(m.group(1)) / 1073741824, 2) if m else 0
        m = re.search(r"torznab:seeders.*?>(\d+)<", item)
        seeds = int(m.group(1)) if m else 0
        m = re.search(r"<pubDate>(.*?)</pubDate>", item)
        pub = m.group(1)[:10] if m else "?"
        found.append((seeds, size, name, pub, title[:120]))
    return found


with ThreadPoolExecutor(max_workers=10) as ex:
    futures = {ex.submit(search_indexer, i): i for i in idxrs}
    for f in as_completed(futures):
        results.extend(f.result())

results.sort(key=lambda x: -x[0])
if not results:
    print(f"No results for: {query}")
else:
    print(f"{len(results)} results for: {query}\n")
    for s, sz, idx, pub, t in results:
        print(f"  {s:>4d}s  {sz:>6.2f}G  [{idx:30s}]  {pub}  {t}")
