# How to reach the qBittorrent Web API (localhost:9003) using a secrets env

This is a living document. If you discover new behavior, edge cases, or environment differences that aren’t covered here, update this doc so the next operator/agent doesn’t have to rediscover it.

## Goal

Allow any user/CLI agent to talk to the qBittorrent Web UI/API at `http://localhost:9003` without hardcoding credentials in commands, by loading an existing secrets environment file and using cookie-based auth.

## Assumptions

- qBittorrent Web UI/API is reachable at `http://localhost:9003`.
- Credentials are provided via a secrets env file (never print them; never commit them; never paste them into chat logs).
- You can use `curl` for spot checks.
- You have a safe place for temporary cookies (e.g., `/tmp`).

## Secrets env (this environment)

Secrets file path:

- `/mnt/config/secrets/qbittorrent/api.env`

Variables provided by that env file (values must remain secret):

- `QBITTORRENTAPI_USERNAME`
- `QBITTORRENTAPI_PASSWORD`

## Security rules

- Use `set +x` (disable shell tracing) before sourcing secrets.
- Do not `env`, `printenv`, or echo secret variables.
- Do not paste cookie jar contents.
- Remove cookie files when done.

## API version note (qB v5 behavior)

qBittorrent v5 uses the same Web API base (`/api/v2/...`), but operationally you must assume **start/stop** is the correct control surface and **pause/resume may be deprecated or unreliable** in some environments.

- Use:
  - `/api/v2/torrents/start`
  - `/api/v2/torrents/stop`
- Avoid (unless you have verified they work in your environment):
  - `/api/v2/torrents/pause`
  - `/api/v2/torrents/resume`

Always verify behavior by reading back the torrent `state` from `/api/v2/torrents/info?hashes=<HASH>` after an action.

## Minimal procedure

### 1) Load secrets env (no output)

```bash
set +x
source /home/michael/dev/secrets/qbittorrent/api.env 2>/dev/null || true
```

Optional: normalize to local variable names (do not print them):

```bash
QB_URL="http://localhost:9003"
QB_USER="$QBITTORRENTAPI_USERNAME"
QB_PASS="$QBITTORRENTAPI_PASSWORD"
```

### 2) Confirm API reachability

```bash
curl -fsS "$QB_URL/api/v2/app/version" || true
```

### 3) Login and obtain a session cookie

qBittorrent Web API auth is cookie-based.

```bash
COOKIE_JAR="$(mktemp /tmp/qb.cookies.XXXXXX)"
curl -fsS -c "$COOKIE_JAR" -X POST "$QB_URL/api/v2/auth/login" \
  --data-urlencode "username=$QB_USER" \
  --data-urlencode "password=$QB_PASS" >/dev/null
```

### 4) Call authenticated endpoints using the cookie

Example: basic transfer stats

```bash
curl -fsS -b "$COOKIE_JAR" "$QB_URL/api/v2/transfer/info"
```

Example: query a specific torrent by hash

```bash
HASH="...40hex..."
curl -fsS -b "$COOKIE_JAR" "$QB_URL/api/v2/torrents/info?hashes=$HASH"
```

### 5) Control torrents (qB v5: start/stop)

Start (preferred over resume):

```bash
curl -fsS -b "$COOKIE_JAR" -X POST "$QB_URL/api/v2/torrents/start" \
  --data-urlencode "hashes=$HASH" >/dev/null
```

Stop (preferred over pause):

```bash
curl -fsS -b "$COOKIE_JAR" -X POST "$QB_URL/api/v2/torrents/stop" \
  --data-urlencode "hashes=$HASH" >/dev/null
```

Always verify action results by re-querying state:

```bash
curl -fsS -b "$COOKIE_JAR" "$QB_URL/api/v2/torrents/info?hashes=$HASH"
```

### 6) Cleanup

```bash
rm -f "$COOKIE_JAR"
```

## Operational guidance

- Prefer repo-provided watchdog/monitor scripts for “containment semantics” (system-level safety checks). Use raw API calls only for verification/triage or when implementing new safety logic.
- If an agent needs the exact env path or variable names and they aren’t in this doc, do not load an entire transcript into context. Retrieve a targeted excerpt containing only the env path + variable names.

## Troubleshooting checklist

- If you see intermittent connection errors (e.g., “Empty reply from server”):
  - Retry exactly once after re-login.
  - If it persists, stop and investigate server/reverse-proxy/container health.
- If an action “succeeds” (HTTP 200, empty body) but state doesn’t change:
  - Re-check that you’re hitting the correct instance (`QB_URL`).
  - Confirm you’re using `/start` and `/stop` in v5 environments.
  - Verify by querying `/torrents/info?hashes=...` rather than inferring from the HTTP response alone.
