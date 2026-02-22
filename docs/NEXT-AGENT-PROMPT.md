# HANDOFF-2026-02-20-rehome-stash-nohl-to-pool

## Scope

This handoff is focused on **rehome of stash noHL payload groups to pool**.
It intentionally does not focus on local pool-only migration troubleshooting.

## Objective

Move noHL stash seed payload groups to pool paths while keeping qB seeding intact, update tags, and track follow-up state.

## Confirmed Progress (Evidence)

1. Main large apply batch completed successfully:
   - Log: `out/reports/rehome-normalize/rehome-normalize-apply-20260219-112708.log`
   - `Batch plan: 20 payload(s)`
   - `Plan executed successfully`
   - Parsed totals from this run: `20` REUSE plan steps, `118` torrents relocated/reused.

2. Additional follow-on apply batch completed successfully:
   - Log: `out/reports/rehome-normalize/rehome-normalize-apply-20260219-111244.log`
   - Parsed totals: `1` REUSE plan step, `10` torrents.

3. Wrapper-based passes continued processing stash->pool rehome groups:
   - Logs: `out/reports/rehome-normalize/codex-says-run-this-next-20260219-184726.log`,
     `out/reports/rehome-normalize/codex-says-run-this-next-20260219-190258.log`
   - Each pass executed `15` REUSE payload plans and completed successfully.

4. Tagging confirms stash->pool transition workflow was applied:
   - `rehome_tag_update ... tags=rehome,rehome_from_stash,rehome_to_pool,...`
   - Unique hashes seen with `rehome_tag_update` across rehome logs: `153`.

## Current Follow-Up State (for stash noHL groups)

From latest completed wrapper follow-up (`...190258.log`):

- `groups: 17`
- `ok: 15`
- `pending: 2`
- `failed: 0`
- `cleanup_done: 0`

Pending payloads:

- `82d486a55784fa21`
- `b1ad45b746842fae`

Pending reasons (both):

- `db_reasons=stale_refs_on_source_payload`
- `source_reasons=source_has_torrent_refs`

## What This Means

- The core stash noHL rehome pipeline is working and has moved a large batch to pool.
- Remaining work is narrow: resolve the 2 pending groups with stale source refs, then rerun follow-up.

## Commits Relevant to This Handoff

- `6fb46b8` feat(bin): add Stage 0 legacy cross-seed migration
- `ccc7093` feat(bin): relocate non-seeds /pool torrents via qB as Stage 0
- `f000c2f` fix(rehome): add wrapper heartbeat logs for long-running steps
- `a76d7af` fix(rehome): stream stage0 progress and fail fast on stuck relocation

## Versions

- `rehome`: `0.3.24`
- `hashall`: `0.4.102`

## Next Agent Start Point

Start from the latest stash-noHL follow-up evidence:

- `out/reports/rehome-normalize/codex-says-run-this-next-20260219-190258.log`
  Focus only on clearing the 2 pending payload groups and closing follow-up.
