# Payload Orphan Audit Automation

This runbook defines a non-destructive daily snapshot loop for payload orphan health.

## Goal

Capture trendable snapshots so any agent can determine whether orphan state is stable before enabling destructive cleanup.

## One-command snapshot

```bash
make payload-orphan-snapshot \
  PAYLOAD_ORPHAN_AUDIT_ROOTS='/pool/data,/stash/media,/data/media'
```

Optional flags:

```bash
# Skip payload-auto dry-run capture (faster)
make payload-orphan-snapshot PAYLOAD_ORPHAN_AUDIT_SKIP_AUTO=1

# Custom output directory
make payload-orphan-snapshot PAYLOAD_ORPHAN_AUDIT_OUTPUT_DIR='/tmp/hashall-orphan-audit'
```

## What it runs

1. `hashall payload orphan-audit --json` (scoped by roots)
2. `scripts/payload_auto_workflow.py --dry-run` with the same DB/roots

Both are executed with the repo interpreter and `PYTHONPATH=src`.

## Output layout

Snapshots are written under:

- `~/.logs/hashall/orphan-audit/<timestamp-pid>/`

Each run directory contains:

- `orphan_audit_raw.txt`
- `orphan_audit.json`
- `payload_auto_dry_run.txt` (unless skipped)
- `summary.json`

## Metrics to trend daily

From `summary.json` -> `orphan_audit.json`:

- `true_orphans`
- `alias_artifacts`
- `gc_tracked_true_orphans`
- `gc_aged_true_orphans`

## Suggested decision rule (3-7 day baseline)

Do **not** enable destructive prune until:

1. `true_orphans` is stable or declining.
2. `alias_artifacts` is stable (not spiking).
3. `gc_aged_true_orphans` behavior is predictable across runs.

## Agent takeover checklist

1. Run one fresh snapshot command above.
2. Compare the latest 3-7 `summary.json` files.
3. Confirm no unexpected spikes.
4. If stable, propose phase-2 destructive prune policy with dry-run + safety caps + backup requirement.

## Optional systemd user timer (recommended)

Repo-managed unit files:

- `ops/systemd/user/hashall-payload-orphan-snapshot.service`
- `ops/systemd/user/hashall-payload-orphan-snapshot.timer`

Install + enable:

```bash
make payload-orphan-timer-install
```

Check status:

```bash
make payload-orphan-timer-status
```

Disable timer:

```bash
make payload-orphan-timer-disable
```

### Timer-run system email reminder

Timer runs send a local system email to `michael` by default with:

- run result and snapshot directory,
- when to review (default `within 24h`),
- how to review (`payload-orphan-timer-status`, latest `summary.json`),
- how to disable automation (`make payload-orphan-timer-disable`).

The service sets these defaults:

- `PAYLOAD_ORPHAN_AUDIT_NOTIFY_EMAIL=1`
- `PAYLOAD_ORPHAN_AUDIT_NOTIFY_TO=michael`
- `PAYLOAD_ORPHAN_AUDIT_NOTIFY_REVIEW_HOURS=24`

### Timer overrides via env file

Optional file: `~/.config/hashall/payload-orphan-snapshot.env`

Example:

```bash
PAYLOAD_ORPHAN_AUDIT_ROOTS=/pool/data,/stash/media,/data/media
PAYLOAD_ORPHAN_AUDIT_OUTPUT_DIR=/home/michael/.logs/hashall/orphan-audit
PAYLOAD_ORPHAN_AUDIT_SKIP_AUTO=0
PAYLOAD_ORPHAN_AUDIT_NOTIFY_EMAIL=1
PAYLOAD_ORPHAN_AUDIT_NOTIFY_TO=michael
PAYLOAD_ORPHAN_AUDIT_NOTIFY_REVIEW_HOURS=24
```

### Bootstrap-managed systems note

If your host uses a bootstrap-managed config repo for system/user files, keep these unit files as source-of-truth in repo and deploy via that bootstrap workflow (not ad-hoc edits under `~/.config/systemd/user` or `/etc/systemd/system`).

## Optional cron (operator-owned)

Example (every 6 hours):

```cron
15 */6 * * * cd /home/michael/dev/work/hashall && make payload-orphan-snapshot PAYLOAD_ORPHAN_AUDIT_ROOTS='/pool/data,/stash/media,/data/media' >> /home/michael/.logs/hashall/orphan-audit-cron.log 2>&1
```

Do not auto-install cron from agents; keep this an explicit operator action.
