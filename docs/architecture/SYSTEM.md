# Hashall System Architecture (Canonical)

Last updated: 2026-02-28
Status: canonical

## Purpose

This document is the single architecture reference for CLI agents and maintainers.

## System Model

Hashall is a unified file-catalog and payload-identity system for safe deduplication and rehome workflows.

- Catalog truth comes from scans of real filesystems.
- Payload identity maps torrent instances to on-disk content.
- Rehome uses this catalog to move or reuse payloads safely.

## Storage and Pathing Model

- Two pools: stash (active/hardlink-sensitive) and pool (cold/seed-focused).
- `/data/media` and `/stash/media` are treated as equivalent mount aliases.
- Hardlinks are only valid within a single filesystem/device boundary.

## Core Data Components

- Device registry (`devices`) with stable filesystem identity.
- Scan history and roots (`scan_sessions`, `scan_roots`).
- Per-device file tables (`files_<device_id>`).
- Payload tables (`payloads`, `torrent_instances`).
- Planning/execution tables for link/rehome workflows.

Schema source of truth: `src/hashall/migrations/*.sql`.
Legacy standalone schema file is archived at `docs/archive/legacy/schema.sql`.

## Operational Lanes

1. Scan lane: maintain filesystem truth.
2. Payload sync lane: map qB torrents to payload state.
3. Link lane: same-device hardlink dedup planning + execution.
4. Rehome lane: guarded stash/pool relocation with verification.
5. Recovery lane: classify and prune recovered non-seeding data.

## Safety Guarantees

- Plan-before-change workflow.
- Dry-run first for mutating operations.
- Cross-filesystem hardlink prevention.
- Verification gates before cleanup.
- Idempotent reruns for interrupted workflows.

## Architecture Extensions

- Collision detection and quick/full hash upgrade paths.
- Path canonicalization for symlink/bind-mount correctness.
- Rehome normalization and follow-up tagging for deferred cleanup.

## Related Canonical Docs

- `docs/REQUIREMENTS.md`
- `docs/tooling/CLI-OPERATIONS.md`
- `docs/tooling/REHOME-RUNBOOK.md`
- `docs/operations/RUN-STATE.md`
- `docs/project/AGENT-PLAYBOOK.md`
