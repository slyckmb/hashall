# Hashall Handoff (Living)

Last updated: 2026-02-27

## Scope

This handoff tracks the active qB torrent repair campaign for unresolved `stoppedDL` / `missingFiles` items.

## Status

- New repair strategy is implemented in standalone tools (`qb-repair-v2`, `qb-repair-fresh`, `qb-fastresume-retarget`).
- Pilot path proved end-to-end mechanics:
  - candidate planning from live qB manifests
  - unique hardlink reconstruction
  - fastresume patching
  - `setLocation` + `recheck`
- Current operator instruction is to wait while qB checking backlog drains before next mutation batch.

## Safety Constraints

- One mutating qB workflow at a time.
- Preserve no-download policy during repairs.
- Treat `/data/media` and `/stash/media` as equivalent aliases.
- Keep per-hash unique payload roots when rebuilding.
- If a target root is exclusive to one hash and rejected, quarantine via `<root>.bad.<timestamp>.<hash>` before rebuild.

## What Worked

- Strict manifest-first matching improved confidence vs legacy heuristics.
- Fastresume alignment removed a major source of save-path reversion.
- Unique-root rebuild approach avoids accidental cross-seed root reuse.

## What Remains

- Continue batch repair for remaining unresolved hashes after checking queue stabilizes.
- Re-run classification and close out failure categories:
  - no-live-candidate
  - ambiguous/multiple sibling roots
  - cross-seed variants requiring parent-derived hardlink reconstruction

## Next Ordered Steps

1. Wait for checking queue to settle (per operator instruction).
2. Snapshot live unresolved set (`missingFiles`, `stoppedDL`) and export working hash list.
3. Run `qb-repair-v2 plan` against current live set.
4. Run `prepare --apply` for low-risk candidates.
5. Patch fastresume for prepared hashes.
6. Run `recheck --apply` with download-protection monitor.
7. Reclassify remaining failures and stage phase-3 strategy.
