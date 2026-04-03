# Torrent Client Agnostic Plan

Last updated: 2026-04-02

## Goal

Make `hashall` operate correctly whether the active torrent client is:

- qBittorrent only
- rTorrent only
- both qBittorrent and rTorrent in parallel

The target state is not "remove qB-specific code." The target state is:

- no critical workflow depends on one specific client being alive
- repair, migration, refresh, and catalog reconciliation work from a shared torrent model
- qB can be shut down after rt stabilizes without breaking `hashall`

## Current State

`hashall` is already rt-aware, but it is not yet torrent-client agnostic.

### What already works with rTorrent

The repo has first-class rt repair/audit helpers in:

- `src/hashall/rtorrent.py`
- `src/hashall/cli.py`

Current rt commands include:

- `hashall rt session-audit`
- `hashall rt state-audit`
- `hashall rt repoint`
- `hashall rt recheck`
- `hashall rt session-reset`
- `hashall rt repair-report`
- `hashall rt repair-apply`

These are enough for:

- reading rt session state
- auditing live rt state
- repointing rt directory roots
- forcing rt hash checks
- rebuilding broken rt session state

Read-side note:

- as of `2026-04-02`, ordinary RT monitoring reads are now aligned to the shared cache contract
- `hashall rt state-audit` defaults to shared silo RT cache rather than live XMLRPC
- explicit live XMLRPC remains available only via `--live`
- mutation / repair commands still use direct XMLRPC intentionally

### What still depends on qBittorrent

The migration/catalog lane is still qB-backed.

Hard qB dependencies remain in:

- `hashall refresh`
  - ends in `payload sync --upgrade-missing`
- `hashall payload sync`
  - materializes torrent-backed `payloads` from qB torrent rows
- `rehome apply`
  - expects qB auth and qB runtime state
- `rehome followup`
  - verifies moved torrents against qB
- `rehome reality`
  - still treats qB/fastresume/runtime state as a primary truth source
- local piece verification in the current docker repair lane
  - depends on qB `BT_backup/*.torrent`

### Practical interpretation

Today, `hashall` is:

- rt-capable for repair
- qB-authoritative for migration, payload sync, and catalog truth

That means qB can stay running during transition work, but `hashall` is not yet safe to operate as a fully rt-only system.

## Current Priority Shift

The new operating target is:

- rt is the primary live client and source of truth
- qB remains available as a backup read-only mirror during transition
- `hashall` should stop requiring qB for ordinary catalog truth as quickly as practical

This does **not** mean qB should be deleted from the repo immediately. It means:

- new truth-building flows should be written RT-first
- qB-dependent flows should be downgraded to fallback / mirror status
- hidden qB assumptions should be surfaced and removed in priority order

## Phase 1 Status

As of `2026-04-03`, the first RT-primary catalog step has landed:

- `hashall payload sync` now supports:
  - `--source qb`
  - `--source rt`
- RT-backed payload sync reads from rTorrent session files and materializes payloads without talking to qB.
- `hashall refresh` now supports:
  - `--payload-source qb`
  - `--payload-source rt`

What this means today:

- you can refresh scans and then sync payloads from RT session truth
- qB is no longer the only way to materialize torrent-backed payload rows

What it does **not** mean yet:

- merged qB+RT inventory does not exist yet
- `rehome apply` is still qB-primary
- qB BT_backup is still part of some verification/repair flows

## Why This Matters

If qB is eventually shut down while `hashall` still assumes qB is the torrent authority:

- `refresh` becomes incomplete or fails
- `payload sync` stops materializing live torrent roots
- `rehome apply` fails before execution or followup
- migration state can no longer be reconciled correctly
- piece verification becomes harder unless `.torrent` metadata is preserved independently of qB

In short: rt repair may still work, but the catalog and migration system will drift from live truth.

## Agnostic End State

`hashall` should operate on a shared torrent-inventory model with per-client adapters.

### Shared model

The system should reason about torrents in a client-neutral shape:

- infohash
- content root
- save path
- content path
- root name
- completion state
- left bytes
- trackers
- tags / category / labels
- client-specific identifiers and runtime state

This model should be able to represent:

- one torrent present in qB only
- one torrent present in rt only
- one logical torrent present in both clients

### Client adapters

Implement adapters rather than embedding client-specific assumptions in the workflow.

Candidate abstraction:

- `TorrentClientAdapter`
  - `list_torrents()`
  - `get_torrent(hash)`
  - `get_files(hash)`
  - `export_torrent(hash)`
  - `recheck(hash)`
  - `set_location(hash, target)`
  - `pause(hash)`
  - `resume(hash)`
  - `read_trackers(hash)`
  - `write_trackers(hash)` if supported

Two concrete adapters:

- `QBittorrentAdapter`
- `RTorrentAdapter`

### Catalog truth

The catalog should stop treating qB as the only live torrent source.

Instead, catalog state should be built from:

- scanned filesystem truth
- shared torrent inventory
- client presence rows per hash per client

That means `payloads` should represent live torrent-backed content regardless of client.

## Required Changes

### 1. Add client-neutral torrent inventory tables

Current `torrent_instances` is qB-shaped.

Add or evolve schema to support:

- `torrent_clients`
  - `infohash`
  - `client_type` (`qb`, `rt`)
  - `present`
  - `save_path`
  - `content_path`
  - `root_name`
  - `category_or_label`
  - `tags`
  - `trackers_count`
  - `primary_tracker`
  - `last_seen_at`
- `torrent_groups` or equivalent logical join layer
  - one row per infohash/logical torrent
  - tracks which clients currently host it

Keep old qB columns during migration if needed, but stop adding new workflows that depend on qB-only shapes.

### 2. Make payload sync client-neutral

Replace qB-only payload materialization with a client-neutral sync lane.

New behavior:

- enumerate live torrents from all enabled client adapters
- resolve each torrent to scanned filesystem truth
- materialize or refresh payload rows from that shared inventory

Transitional behavior:

- if qB is enabled, include qB rows
- if rt is enabled, include rt rows
- if both are enabled, merge by hash and content root

Immediate next slice:

- keep `payload sync --source rt` stable
- add a merged inventory mode after RT-only sync is trusted operationally

### 3. Make refresh client-neutral

Current `refresh` does:

1. scan roots
2. dedupe
3. `payload sync --upgrade-missing`

The new requirement is:

1. scan roots
2. dedupe
3. `torrent sync` from enabled clients
4. `payload sync` from the merged torrent inventory

`refresh` must succeed even when qB is absent.

Immediate next slice:

- make `refresh --payload-source rt` the preferred operator path during RT-primary transition
- keep qB refresh path available until rehome/followup are also RT-first

### 4. Make rehome execution stop depending on qB as sole runtime authority

`rehome apply` and followup should verify moves against:

- filesystem truth
- merged torrent inventory
- enabled client adapters

Required change:

- client-specific mutation steps become optional per adapter
- success should be reported as:
  - `filesystem_aligned`
  - `torrent_inventory_aligned`
  - `client_alignment`

Cleanup gating should require all enabled clients to agree, not qB alone.

### 5. Move piece verification off qB `BT_backup`

Current high-confidence local-restore verification depends on qB `.torrent` files.

That is not viable long-term if qB is shut down.

We need a client-neutral torrent metadata store:

- persist `.torrent` bytes in `hashall`, or
- export/cache them from clients during sync, or
- maintain a local canonical torrent archive by infohash

Required capability:

- given an infohash and candidate path, verify payload bytes against torrent piece hashes without qB running

### 6. Unify tracker handling

Tracker state should be stored per torrent in the client-neutral model.

The qB cache enrichment work already helps on the qB side by caching:

- `tracker_urls`
- `tracker_urls_http`
- `primary_tracker`
- `trackers_count`
- `real_trackers_count`
- `tracker_domains`

Equivalent tracker visibility is needed for rt-hosted torrents too.

### 7. Make repair planning client-neutral

Repair should stop assuming:

- qB save path is authoritative
- qB fastresume is the canonical runtime truth

Repair planning should instead rank evidence like this:

1. filesystem truth
2. piece-verified torrent metadata truth
3. merged torrent inventory
4. client-specific runtime hints

## Phased Upgrade Plan

### Phase 1: Shared inventory foundation

Deliverables:

- add client-neutral torrent inventory tables
- add rt inventory ingestion
- keep qB inventory ingestion
- introduce a merged per-hash view

Exit criteria:

- the catalog can answer "where does this torrent live and which client owns it?" without qB-only joins

### Phase 2: Torrent metadata independence

Deliverables:

- cache/store `.torrent` metadata independent of qB
- add piece verification against stored torrent metadata

Exit criteria:

- `verify-local-payload` equivalent works without qB `BT_backup`

### Phase 3: Client-neutral payload sync

Deliverables:

- new sync flow materializes payloads from merged torrent inventory
- `refresh` succeeds whether qB, rt, or both are enabled

Exit criteria:

- qB can be stopped and `refresh` still produces correct torrent-backed payload rows

### Phase 4: Client-neutral rehome

Deliverables:

- `rehome apply` no longer requires qB auth to run
- followup verification supports rt-only environments
- cleanup gating checks all enabled clients

Exit criteria:

- stash/pool rehome can run safely in an rt-only environment

### Phase 5: qB demotion

Deliverables:

- qB becomes optional
- qB-specific logic remains only as an adapter, not as a workflow assumption

Exit criteria:

- shutting down qB does not break refresh, payload sync, repair planning, or rehome followup

## Proposed Near-Term Work

The next repo work should be:

1. add a client-neutral torrent inventory schema
2. ingest rt session/runtime rows into that schema
3. preserve `.torrent` metadata independently of qB
4. add a `torrent sync` command that merges qB and rt state
5. re-point `refresh` to that merged sync path

Do not start by rewriting every repair path at once.

The safest sequence is:

- first make the catalog client-neutral
- then make verification client-neutral
- then make execution client-neutral

## Operational Guidance Until Then

Until the above is complete:

- keep qB running for `refresh`, `payload sync`, and `rehome apply`
- keep using rt commands for rt repair
- do not treat rt repair support as proof that qB can be removed

In other words:

- rt is already a supported repair client
- qB is still the migration/catalog dependency

## Approval-Friendly Definition Of Done

`hashall` can be called torrent-client agnostic when all of the following are true:

1. `refresh` succeeds with qB stopped
2. `payload sync` can materialize live torrent-backed payloads from rt alone
3. piece verification works without qB `BT_backup`
4. `rehome apply` and followup do not require qB auth
5. repair planning can operate from shared torrent inventory and filesystem truth

Until those are true, qB should be treated as transitional infrastructure, not removable legacy.
