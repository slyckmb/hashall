# Next Agent Prompt Entry (Compact-Safe)

Canonical state document:
`docs/operations/RUN-STATE.md`

Prompt-critical context (2026-03-06):

- Use worktree/branch:
  - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
  - `chatrap/codex-hashall-20260305-181919`
- Latest fixed blocker:
  - `qb-stoppeddl-drain` empty-bucket index now no-ops cleanly.
  - commit `657eccc`, script semver `0.1.23`.
- Strategic objective changed from tactical qB-only fixes to Hashall identity redesign:
  - migrate payload/torrent/rehome identity from transient `device_id` to stable `fs_uuid`.
- New identity repair tooling is now live:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
  - `hashall` version now `0.4.133`.
- Known catalog inconsistencies to account for in migrations and repair logic:
  - stale/missing device identities in payload/torrent tables (`141`, `NULL`, legacy `49`).
  - parked negative `device_id` in devices table.
- Current unresolved identity scope after apply passes:
  - 100 remaining candidates are all `/pool/media` rooted rows waiting on valid device mapping in `devices`.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/NEXT-AGENT-PROMPT.md`
