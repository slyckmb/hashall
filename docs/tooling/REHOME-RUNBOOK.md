# Rehome Runbook (Canonical)

Last updated: 2026-02-28
Status: canonical

## Purpose

Single operational runbook for rehome planning, apply flow, and safety gates.

## Rehome Principles

- Preserve hardlink safety.
- Prefer reuse over risky movement.
- Apply only from fresh scan + payload sync state.
- Treat `/data/media` and `/stash/media` as equivalent aliases.

## Baseline Workflow

1. Refresh catalog state with scans.
2. Sync payloads from qB.
3. Build rehome plan.
4. Review plan outputs and blockers.
5. Dry-run apply.
6. Apply if safe.
7. Verify qB + filesystem state.
8. Cleanup only after verification gates pass.

## Required Safety Gates

- No active-download regressions on repaired/rehomed hashes.
- Source cleanup only when relocated content is validated.
- Manual-action tags remain until follow-up completes.

## qB Integration Defaults

- Preferred mutation order: `setLocation -> recheck -> verify seeding-safe state`.
- Batch fastresume patching when required by selected hashes.
- Avoid concurrent mutating workflows.
- Treat `~/.hashall/seed-root-state.json` as the authoritative published seeding-root contract for external orchestration.

## Observed Failure Modes And Required Mitigations

- Hidden interactive child prompt inside `rehome refresh`
  - Failure: refresh appeared hung during delegated `hashall link execute`
  - Root cause: child command waited for confirmation on stdin
  - Mitigation: refresh must run non-interactively with `--yes`

- `ActionInfo` crash after refresh-created `Plan #59`
  - Failure: `hashall link execute` aborted with `UnboundLocalError`
  - Root cause: local import shadowed module-level `ActionInfo` inside `execute_plan()`
  - Mitigation: keep type/import resolution at module scope; covered by regression

- Mixed-root dedup during migration
  - Failure mode: refresh dedup can currently operate inside both `/pool/data/media/...` and legacy `/pool/data/seeds/...`
  - Risk: operational confusion and incorrect assumptions about converged root ownership
  - Mitigation: treat dedup as inode cleanup only, not as proof of migration convergence

- Long quiet periods during delegated work
  - Failure mode: operator cannot distinguish progress from hang
  - Mitigation:
    - watch `~/.logs/hashall/hashall.log`
    - keep delegated-step progress lines visible
    - continue improving heartbeat output in orchestrators

- qB repair/migration donor drift across roots/filesystems
  - Failure mode: repair tooling can select the wrong donor/root class unless guarded tightly
  - Mitigation:
    - fail closed on cross-filesystem donor selection
    - require explicit allowed-save-root / allowed-donor-root policy
    - verify with libtorrent before any qB mutation
    - protect against download-like state flips after apply

## Dataset Migration Strategy

Target migration:
- source: `/pool/data/media/torrents/seeding`
- target: `/pool/media/torrents/seeding`

Chosen approach:
- hybrid
  - use existing `hashall` / `rehome` catalog, identity, and published seed-root-state contract
  - use dedicated qB repair/migration safety tooling for qB-facing mutations and verification

Reason:
- `hashall` should own long-term seed placement and published seeding-root truth
- qB repair/migration requires stricter save-path/content-path, fastresume, and download-guard logic than generic rehome/dedup flows

## Production-Safe Migration Sequence

1. Publish and verify `~/.hashall/seed-root-state.json`
   - active/target must advertise `/pool/media/torrents/seeding`
   - legacy `/pool/data/...` roots remain explicit as mirrors/source roots while migration is incomplete

2. Run `rehome refresh --verbose`
   - require preflight clean
   - watch both:
     - `~/.logs/hashall/rehome/refresh/*.log`
     - `~/.logs/hashall/hashall.log`

3. Audit qB risk set before mutation
   - stoppedDL / missingFiles / pausedDL / error
   - mixed save_path/content_path
   - roots outside allowed seeding roots

4. Repair qB items in guarded batches
   - donor/root policy must be explicit
   - require same-filesystem enforcement unless intentionally overridden
   - require libtorrent verification before any location change or fastresume patch
   - post-apply: recheck and abort on download-like states

5. Migrate validated healthy payloads from source dataset to target dataset
   - batch by payload class
   - verify qB save_path/content_path and seeding-safe state after each batch
   - keep old root as explicit migration source until batch follow-up is complete

6. Only after qB and filesystem verification
   - cleanup legacy views/temporary repair roots
   - reduce old-root participation in published `mirror_roots`

## Pilot Dry-Run Commands

Use the existing `rehome` dry-run/apply pair first. Do not invent an untracked apply path.

1. Refresh first:

```bash
rehome refresh --verbose
```

2. Generate pilot MOVE candidates from the old pool dataset to the new one without applying:

```bash
rehome auto --from pool-data --to pool-media --limit 1
```

Notes:
- default mode is dry-run
- plan JSON is written under:
  - `~/.logs/hashall/reports/rehome-runs/plans/`
- the command prints the next `rehome apply ... --dryrun` step

3. Dry-run the specific generated plan:

```bash
rehome apply ~/.logs/hashall/reports/rehome-runs/plans/<plan>.json --dryrun
```

4. Only after reviewing the dry-run output and confirming:
- source root is under `/pool/data/media/torrents/seeding`
- target save paths are under `/pool/media/torrents/seeding`
- no blocked reasons are ignored
- no unexpected alias/root drift appears

then execute the exact same plan:

```bash
rehome apply ~/.logs/hashall/reports/rehome-runs/plans/<plan>.json --force
```

5. Immediate post-apply checks:
- qB save path matches expected target save path
- torrent reaches seed-ready state, not `stoppedDL`/`missingFiles`
- no download-like flip is observed by the guard tooling
- source cleanup is deferred until follow-up validation passes

## Overnight-Safe Dry-Run Posture

For unattended planning-only runs:

```bash
rehome auto --from pool-data --to pool-media --limit 25
```

That is still dry-run only. It should generate plans and reports but must not mutate qB, fastresume, or filesystem state.

## Operational Artifacts

- Plans: generated JSON plan files.
- Apply reports: execution result logs/reports.
- Follow-up tags: verification/cleanup backlog tracking.

## Related Canonical Docs

- `docs/tooling/CLI-OPERATIONS.md`
- `docs/operations/RUN-STATE.md`
- `docs/REQUIREMENTS.md`
