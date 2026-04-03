# Hashall RT-Primary Agent Comms

Last updated: 2026-04-03

## What landed

- `hashall payload sync` now accepts `--source rt`.
- RT-backed payload sync reads from rTorrent session files and does not require qB to be up.
- `hashall refresh` now accepts `--payload-source rt` and passes that through to the final payload sync step.

## What is still qB-primary

- `rehome apply`
- `rehome followup`
- qB-backed repair flows that still depend on `BT_backup`

## What other agents should assume

- For catalog truth during RT-primary transition, prefer:
  - `hashall payload sync --source rt`
  - `hashall refresh --payload-source rt`
- Do not assume qB must be online just to refresh payload-backed catalog rows.
- Do not assume merged qB+RT inventory exists yet. Phase 1 is RT-backed sync, not full dual-client merge.

## Immediate next engineering slice

1. Add merged inventory mode after RT-only sync is stable.
2. Move `rehome apply` and followup off qB as sole runtime authority.
3. Replace qB `BT_backup` dependence with client-neutral torrent metadata persistence.
