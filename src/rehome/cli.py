"""
Command-line interface for rehome.
"""

import click
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import rehome
from rehome import executor as rehome_executor
from rehome import view_builder as rehome_view_builder
from rehome import __version__
from rehome.followup import run_followup
from rehome.normalize import build_pool_path_normalization_batch
from rehome.planner import DemotionPlanner, PromotionPlanner
from rehome.executor import DemotionExecutor
from rehome.library_roots import collect_library_roots

DEFAULT_CATALOG_PATH = Path.home() / ".hashall" / "catalog.db"


def _debug_enabled() -> bool:
    return os.getenv("HASHALL_REHOME_QB_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}


def _print_post_apply_summary(executor: "DemotionExecutor", plans: list) -> bool:
    """
    Query qBittorrent for the final state of all affected torrents and print
    a summary table.

    Returns True if all torrents are in acceptable seed-ready states.
    Returns False if any torrent is in an unexpected/alarm state.
    """
    # Collect all affected hashes (deduplicated, preserving order).
    all_hashes = []
    seen: set = set()
    for plan in plans:
        for h in (plan.get("affected_torrents") or []):
            if h not in seen:
                seen.add(h)
                all_hashes.append(h)

    if not all_hashes:
        return True

    # States that are acceptable after a successful rehome.
    good_states = {
        "stalledup", "uploading", "queuedup", "forcedup",
        "stoppedup",  # paused by operator (was seeding, user paused it)
        "pausedup",
        "checkingup",  # transient post-recheck
    }
    # States that are alarm-worthy.
    alarm_states = {"stoppeddl", "pauseddl", "downloading", "stalleddl",
                    "missingfiles", "error"}

    click.echo()
    click.echo("── Post-apply torrent state summary ──────────────────────────────")
    click.echo(f"{'hash':<18}  {'state':<16}  {'progress':>8}  {'note'}")
    click.echo(f"{'─'*18}  {'─'*16}  {'─'*8}  {'─'*16}")

    alarm_count = 0
    missing_count = 0

    for h in all_hashes:
        info = executor.qbit_client.get_torrent_info(h)
        if not info:
            click.echo(f"{h[:16]}..  {'not_found':<16}  {'?':>8}  ⚠️  NOT IN QB")
            missing_count += 1
            continue

        state = str(getattr(info, "state", "") or "").strip().lower()
        progress_raw = getattr(info, "progress", None)
        try:
            progress = float(progress_raw) if progress_raw is not None else 0.0
        except (TypeError, ValueError):
            progress = 0.0

        if state in alarm_states:
            note = "🚨 ALARM"
            alarm_count += 1
        elif state in good_states or ("check" in state and "up" in state):
            note = "✓"
        else:
            note = "?"

        click.echo(
            f"{h[:16]}..  {state:<16}  {progress*100:>7.1f}%  {note}"
        )

    click.echo(f"{'─'*18}  {'─'*16}  {'─'*8}  {'─'*16}")
    total = len(all_hashes)
    alarm_total = alarm_count + missing_count
    if alarm_total > 0:
        click.echo(
            f"⚠️  Summary: {total} torrent(s) checked, "
            f"{alarm_count} alarm state(s), {missing_count} not found in qB"
        )
    else:
        click.echo(f"✅ Summary: {total} torrent(s) checked, all in acceptable state")

    return alarm_total == 0


def _acquire_rehome_lock() -> "file":
    """
    Acquire an exclusive process-level lock for rehome apply operations.

    Returns an open file handle that holds the lock.  The caller MUST close
    it (or use try/finally) to release the lock on exit.

    Raises SystemExit if the lock is held by another process.
    """
    lock_dir = Path.home() / ".hashall"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "rehome.lock"
    lock_fh = open(lock_path, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_fh.close()
        click.echo(
            "❌ Another rehome apply is already running "
            f"(lock held: {lock_path}). Aborting.",
            err=True,
        )
        raise SystemExit(1)
    lock_fh.write(f"pid={os.getpid()}\n")
    lock_fh.flush()
    return lock_fh


def _emit_banner() -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    script = Path(sys.argv[0]).name
    print(f"🧾 {script} v{__version__} @ {timestamp}", flush=True)


def _build_payload_sync_command(
    *,
    catalog: Path,
    pool_seeding_root: str,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 0,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "hashall.cli",
        "payload",
        "sync",
        "--db",
        str(catalog),
        "--path-prefix",
        str(pool_seeding_root),
    ]
    if category:
        cmd.extend(["--category", category])
    if tag:
        cmd.extend(["--tag", tag])
    if limit and int(limit) > 0:
        cmd.extend(["--limit", str(int(limit))])
    return cmd


def _refresh_catalog_from_qb(
    *,
    catalog: Path,
    pool_seeding_root: str,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 0,
) -> None:
    cmd = _build_payload_sync_command(
        catalog=catalog,
        pool_seeding_root=pool_seeding_root,
        category=category,
        tag=tag,
        limit=limit,
    )
    click.echo(
        "🔄 Pre-plan refresh: "
        f"{' '.join(cmd)}"
    )
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"payload sync refresh failed (exit={result.returncode})")


@click.group()
@click.version_option(__version__)
def cli():
    """Rehome - Seed payload demotion orchestrator."""
    _emit_banner()


@cli.command("plan")
@click.option("--demote", is_flag=True,
              help="Plan demotion from stash to pool")
@click.option("--promote", is_flag=True,
              help="Plan promotion from pool to stash (reuse only)")
@click.option("--torrent-hash",
              help="Torrent hash to demote (single-torrent mode)")
@click.option("--payload-hash",
              help="Payload hash to demote (batch mode - all torrents with this payload)")
@click.option("--tag",
              help="qBittorrent tag to demote (batch mode - all tagged torrents)")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
@click.option("--seeding-root", multiple=True, required=True,
              help="Seeding domain root(s) - paths outside these are external consumers")
@click.option("--library-root", multiple=True,
              help="Library roots that must be scanned to detect external consumers")
@click.option("--cross-seed-config", type=click.Path(),
              help="Path to cross-seed config.js to import dataDirs")
@click.option("--tracker-registry", type=click.Path(),
              help="Path to tracker-registry.yml to import qbittorrent.save_path")
@click.option("--stash-device", type=str, required=True,
              help="Device alias (e.g. 'stash') or integer device_id for stash storage")
@click.option("--pool-device", type=str, required=True,
              help="Device alias (e.g. 'pool') or integer device_id for pool storage")
@click.option("--stash-seeding-root", type=click.Path(),
              help="Base seeding root on stash (for save_path mapping)")
@click.option("--pool-seeding-root", type=click.Path(),
              help="Base seeding root on pool (for save_path mapping)")
@click.option("--pool-payload-root", type=click.Path(),
              help="Base payload root on pool (for MOVE target paths)")
@click.option("--output", "-o", type=click.Path(),
              help="Output plan file (default: rehome-plan-<mode>.json)")
def plan_cmd(demote, promote, torrent_hash, payload_hash, tag, catalog, seeding_root,
             library_root, cross_seed_config, tracker_registry, stash_device, pool_device,
             stash_seeding_root, pool_seeding_root, pool_payload_root, output):
    """
    Create a demotion plan for torrents.

    Supports three modes:
    - Single torrent: --torrent-hash <hash>
    - Batch by payload: --payload-hash <hash>
    - Batch by tag: --tag <tag>

    Analyzes payloads, checks for external consumers, and determines
    whether to BLOCK, REUSE, or MOVE each payload from stash to pool.
    """
    # Validate direction
    if demote == promote:
        click.echo("❌ Must specify exactly one of: --demote or --promote", err=True)
        raise click.Abort()

    # Validate mutually exclusive options
    mode_count = sum([bool(torrent_hash), bool(payload_hash), bool(tag)])
    if mode_count == 0:
        click.echo("❌ Must specify one of: --torrent-hash, --payload-hash, or --tag", err=True)
        raise click.Abort()
    if mode_count > 1:
        click.echo("❌ Cannot use --torrent-hash, --payload-hash, and --tag together", err=True)
        raise click.Abort()

    catalog_path = Path(catalog)

    if not catalog_path.exists():
        click.echo(f"❌ Catalog not found: {catalog_path}", err=True)
        raise click.Abort()

    # Resolve device alias/integer to current device_id
    try:
        from hashall.model import connect_db
        from hashall.device import resolve_device_id
        _resolve_conn = connect_db(catalog_path, read_only=True, apply_migrations=False)
        try:
            stash_device = resolve_device_id(_resolve_conn, stash_device)
            pool_device = resolve_device_id(_resolve_conn, pool_device)
        finally:
            _resolve_conn.close()
    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    # Validate mapping roots
    if bool(stash_seeding_root) ^ bool(pool_seeding_root):
        click.echo("❌ Must specify both --stash-seeding-root and --pool-seeding-root when using mapping", err=True)
        raise click.Abort()

    # Create planner
    try:
        library_roots, library_root_sources = collect_library_roots(
            explicit_roots=list(library_root),
            cross_seed_config=cross_seed_config,
            tracker_registry=tracker_registry,
        )
    except FileNotFoundError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    planner = (
        DemotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=list(seeding_root),
            library_roots=library_roots,
            stash_device=stash_device,
            pool_device=pool_device,
            stash_seeding_root=stash_seeding_root,
            pool_seeding_root=pool_seeding_root,
            pool_payload_root=pool_payload_root,
        ) if demote else PromotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=list(seeding_root),
            library_roots=library_roots,
            stash_device=stash_device,
            pool_device=pool_device,
            stash_seeding_root=stash_seeding_root,
            pool_seeding_root=pool_seeding_root,
        )
    )

    # Generate plan(s) based on mode
    try:
        if torrent_hash:
            # Single-torrent mode
            mode = "torrent"
            filter_val = torrent_hash
            action = "demotion" if demote else "promotion"
            click.echo(f"📋 Planning {action} for torrent {torrent_hash[:16]}...")
            plans = [planner.plan_demotion(torrent_hash)] if demote else [planner.plan_promotion(torrent_hash)]

        elif payload_hash:
            # Batch mode by payload hash
            mode = "payload"
            filter_val = payload_hash
            action = "demotion" if demote else "promotion"
            click.echo(f"📋 Planning batch {action} for payload {payload_hash[:16]}...")
            plans = [planner.plan_batch_demotion_by_payload_hash(payload_hash)] if demote else [
                planner.plan_batch_promotion_by_payload_hash(payload_hash)
            ]

        elif tag:
            # Batch mode by tag
            mode = "tag"
            filter_val = tag
            action = "demotion" if demote else "promotion"
            click.echo(f"📋 Planning batch {action} for tag '{tag}'...")
            plans = planner.plan_batch_demotion_by_tag(tag) if demote else planner.plan_batch_promotion_by_tag(tag)

    except Exception as e:
        click.echo(f"❌ Planning failed: {e}", err=True)
        raise click.Abort()

    # Default output filename
    if not output:
        if mode == "torrent":
            output = f"rehome-plan-{'demote' if demote else 'promote'}-{filter_val[:8]}.json"
        else:
            safe_filter = filter_val[:16] if mode == "payload" else filter_val.replace('/', '-')
            output = f"rehome-plan-{'demote' if demote else 'promote'}-{mode}-{safe_filter}.json"

    output_path = Path(output)

    # Write plan(s) to file
    if len(plans) == 1:
        if library_root_sources:
            plans[0]["library_roots_sources"] = library_root_sources
        with open(output_path, 'w') as f:
            json.dump(plans[0], f, indent=2)
    else:
        # Multiple plans - write as batch
        if library_root_sources:
            for plan in plans:
                plan["library_roots_sources"] = library_root_sources
        with open(output_path, 'w') as f:
            json.dump({
                'version': '1.0',
                'batch': True,
                'mode': mode,
                'filter': filter_val,
                'plans': plans
            }, f, indent=2)

    click.echo(f"✅ Plan written to: {output_path}")
    click.echo()

    # Display summary
    if len(plans) == 1:
        plan = plans[0]
        decision = plan['decision']

        if decision == 'BLOCK':
            click.echo("🚫 BLOCKED - Plan cannot proceed:")
            for reason in plan['reasons']:
                click.echo(f"   {reason}")
        elif decision == 'REUSE':
            if plan.get('direction') == 'promote':
                click.echo("♻️  REUSE - Payload already exists on stash")
            else:
                click.echo("♻️  REUSE - Payload already exists on pool")
            click.echo(f"   Payload hash: {plan['payload_hash'][:16]}...")
            click.echo(f"   Sibling torrents: {len(plan['affected_torrents'])}")
        elif decision == 'MOVE':
            click.echo("📦 MOVE - Payload will be moved to pool")
            click.echo(f"   Payload hash: {plan['payload_hash'][:16]}...")
            click.echo(f"   Files: {plan['file_count']}")
            click.echo(f"   Size: {plan['total_bytes'] / (1024**3):.2f} GB")
            click.echo(f"   Sibling torrents: {len(plan['affected_torrents'])}")
    else:
        # Batch summary
        click.echo(f"📦 Batch plan with {len(plans)} payload(s)")
        blocked = sum(1 for p in plans if p['decision'] == 'BLOCK')
        reuse = sum(1 for p in plans if p['decision'] == 'REUSE')
        move = sum(1 for p in plans if p['decision'] == 'MOVE')
        total_torrents = sum(len(p['affected_torrents']) for p in plans)

        click.echo(f"   BLOCKED: {blocked}")
        click.echo(f"   REUSE:   {reuse}")
        click.echo(f"   MOVE:    {move}")
        click.echo(f"   Total torrents: {total_torrents}")

    click.echo()
    click.echo(f"Next step: rehome apply {output_path} --dryrun")


@cli.command("plan-batch")
@click.option("--demote", is_flag=True,
              help="Plan demotion from stash to pool")
@click.option("--promote", is_flag=True,
              help="Plan promotion from pool to stash (reuse only)")
@click.option("--payload-hashes-file", type=click.Path(exists=True), required=True,
              help="Input file with payload hashes (one per line)")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
@click.option("--seeding-root", multiple=True, required=True,
              help="Seeding domain root(s) - paths outside these are external consumers")
@click.option("--library-root", multiple=True,
              help="Library roots that must be scanned to detect external consumers")
@click.option("--cross-seed-config", type=click.Path(),
              help="Path to cross-seed config.js to import dataDirs")
@click.option("--tracker-registry", type=click.Path(),
              help="Path to tracker-registry.yml to import qbittorrent.save_path")
@click.option("--stash-device", type=str, required=True,
              help="Device alias (e.g. 'stash') or integer device_id for stash storage")
@click.option("--pool-device", type=str, required=True,
              help="Device alias (e.g. 'pool') or integer device_id for pool storage")
@click.option("--stash-seeding-root", type=click.Path(),
              help="Base seeding root on stash (for save_path mapping)")
@click.option("--pool-seeding-root", type=click.Path(),
              help="Base seeding root on pool (for save_path mapping)")
@click.option("--pool-payload-root", type=click.Path(),
              help="Base payload root on pool (for MOVE target paths)")
@click.option("--output-dir", type=click.Path(), required=True,
              help="Directory to write per-payload plan files")
@click.option("--manifest", type=click.Path(), required=True,
              help="Manifest JSON path for checkpoint/resume")
@click.option("--report-tsv", type=click.Path(),
              help="Optional TSV report output path")
@click.option("--plannable-hashes-out", type=click.Path(),
              help="Optional output file of plannable payload hashes")
@click.option("--blocked-hashes-out", type=click.Path(),
              help="Optional output file of blocked payload hashes")
@click.option("--limit", type=int, default=0,
              help="Max payload hashes to process (0 = all)")
@click.option("--resume/--no-resume", default=True,
              help="Resume from existing manifest entries when available")
@click.option("--checkpoint-every", type=int, default=25,
              help="Write checkpoint manifest every N items (0 = final only)")
@click.option("--output-prefix", type=str, default="nohl",
              help="Per-plan filename prefix")
def plan_batch_cmd(
    demote,
    promote,
    payload_hashes_file,
    catalog,
    seeding_root,
    library_root,
    cross_seed_config,
    tracker_registry,
    stash_device,
    pool_device,
    stash_seeding_root,
    pool_seeding_root,
    pool_payload_root,
    output_dir,
    manifest,
    report_tsv,
    plannable_hashes_out,
    blocked_hashes_out,
    limit,
    resume,
    checkpoint_every,
    output_prefix,
):
    """Plan many payload hashes in one process with checkpoint/resume support."""
    if demote == promote:
        click.echo("❌ Must specify exactly one of: --demote or --promote", err=True)
        raise click.Abort()

    catalog_path = Path(catalog)

    # Resolve device alias/integer to current device_id
    try:
        from hashall.model import connect_db
        from hashall.device import resolve_device_id
        _resolve_conn = connect_db(catalog_path, read_only=True, apply_migrations=False)
        try:
            stash_device = resolve_device_id(_resolve_conn, stash_device)
            pool_device = resolve_device_id(_resolve_conn, pool_device)
        finally:
            _resolve_conn.close()
    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    hashes = []
    for raw_line in Path(payload_hashes_file).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        hashes.append(line.lower())
    if limit and int(limit) > 0:
        hashes = hashes[:int(limit)]
    if not hashes:
        click.echo("❌ No payload hashes found to plan", err=True)
        raise click.Abort()

    try:
        library_roots, library_root_sources = collect_library_roots(
            explicit_roots=list(library_root),
            cross_seed_config=cross_seed_config,
            tracker_registry=tracker_registry,
        )
    except FileNotFoundError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    planner = (
        DemotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=list(seeding_root),
            library_roots=library_roots,
            stash_device=stash_device,
            pool_device=pool_device,
            stash_seeding_root=stash_seeding_root,
            pool_seeding_root=pool_seeding_root,
            pool_payload_root=pool_payload_root,
        ) if demote else PromotionPlanner(
            catalog_path=catalog_path,
            seeding_roots=list(seeding_root),
            library_roots=library_roots,
            stash_device=stash_device,
            pool_device=pool_device,
            stash_seeding_root=stash_seeding_root,
            pool_seeding_root=pool_seeding_root,
        )
    )

    prior_entries_by_hash = {}
    if resume and manifest_path.exists():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in prior.get("entries", []):
                payload_hash = str(entry.get("payload_hash") or "").strip().lower()
                if payload_hash:
                    prior_entries_by_hash[payload_hash] = dict(entry)
            click.echo(
                f"checkpoint loaded={manifest_path} entries={len(prior_entries_by_hash)}"
            )
        except Exception as e:
            click.echo(f"checkpoint_load_failed path={manifest_path} error={e}")

    entries = []
    plannable_hashes = []
    blocked_hashes = []
    errors = 0
    start_all = datetime.now().timestamp()
    total = len(hashes)
    checkpoint_every = max(0, int(checkpoint_every))

    def _build_manifest_payload() -> dict:
        return {
            "generated_at": datetime.now().astimezone().isoformat(),
            "catalog": str(catalog_path),
            "direction": "demote" if demote else "promote",
            "hashes_input_file": str(payload_hashes_file),
            "output_dir": str(output_dir_path),
            "summary": {
                "input_hashes": total,
                "plannable": len(plannable_hashes),
                "blocked": len(blocked_hashes),
                "errors": errors,
                "elapsed_s": max(0, int(datetime.now().timestamp() - start_all)),
            },
            "entries": entries,
        }

    def _write_manifest_atomic() -> dict:
        payload = _build_manifest_payload()
        tmp_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(manifest_path)
        return payload

    db_conn = planner._get_db_connection()
    try:
        for idx, payload_hash in enumerate(hashes, start=1):
            plan_path = output_dir_path / f"{output_prefix}-plan-{idx:04d}-{payload_hash[:12]}.json"
            prior_entry = prior_entries_by_hash.get(payload_hash)

            if (
                prior_entry
                and str(prior_entry.get("status", "")).lower() == "ok"
                and Path(str(prior_entry.get("plan_path", ""))).exists()
            ):
                reused = dict(prior_entry)
                reused["idx"] = idx
                reused["total"] = total
                reused["resumed"] = True
                entries.append(reused)
                decision = str(reused.get("decision") or "").upper()
                if decision in {"MOVE", "REUSE"}:
                    plannable_hashes.append(payload_hash)
                elif decision == "BLOCK":
                    blocked_hashes.append(payload_hash)
                click.echo(
                    f"plan idx={idx}/{total} payload={payload_hash[:16]} status=resume decision={decision or '-'}"
                )
                if checkpoint_every and (idx == 1 or idx % checkpoint_every == 0 or idx == total):
                    _write_manifest_atomic()
                continue

            status = "ok"
            error = ""
            decision = ""
            source_path = ""
            target_path = ""
            item_started = datetime.now().timestamp()
            try:
                if demote:
                    plan = planner.plan_batch_demotion_by_payload_hash(payload_hash, conn=db_conn)
                else:
                    plan = planner.plan_batch_promotion_by_payload_hash(payload_hash, conn=db_conn)
                if library_root_sources:
                    plan["library_roots_sources"] = library_root_sources
                decision = str(plan.get("decision") or "").upper()
                source_path = str(plan.get("source_path") or "")
                target_path = str(plan.get("target_path") or "")
                plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
                if decision in {"MOVE", "REUSE"}:
                    plannable_hashes.append(payload_hash)
                elif decision == "BLOCK":
                    blocked_hashes.append(payload_hash)
            except Exception as e:
                status = "error"
                error = str(e)
                errors += 1

            elapsed_s = max(0, int(datetime.now().timestamp() - item_started))
            entries.append(
                {
                    "idx": idx,
                    "total": total,
                    "payload_hash": payload_hash,
                    "plan_path": str(plan_path),
                    "status": status,
                    "decision": decision,
                    "source_path": source_path,
                    "target_path": target_path,
                    "error": error,
                    "elapsed_s": elapsed_s,
                    "resumed": False,
                }
            )
            click.echo(
                f"plan idx={idx}/{total} payload={payload_hash[:16]} "
                f"decision={decision or '-'} status={status} elapsed_s={elapsed_s}"
            )
            if checkpoint_every and (idx == 1 or idx % checkpoint_every == 0 or idx == total):
                _write_manifest_atomic()
    finally:
        db_conn.close()

    payload = _write_manifest_atomic()

    if report_tsv:
        report_path = Path(report_tsv)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as out:
            out.write("idx\tpayload_hash\tdecision\tsource_path\ttarget_path\tstatus\tplan_path\terror\n")
            for entry in entries:
                out.write(
                    f"{entry.get('idx')}\t{entry.get('payload_hash')}\t{entry.get('decision')}\t"
                    f"{entry.get('source_path')}\t{entry.get('target_path')}\t{entry.get('status')}\t"
                    f"{entry.get('plan_path')}\t{entry.get('error')}\n"
                )
        click.echo(f"report_tsv={report_path}")

    if plannable_hashes_out:
        out_path = Path(plannable_hashes_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(plannable_hashes) + ("\n" if plannable_hashes else ""), encoding="utf-8")
        click.echo(f"plannable_hashes={out_path}")
    if blocked_hashes_out:
        out_path = Path(blocked_hashes_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(blocked_hashes) + ("\n" if blocked_hashes else ""), encoding="utf-8")
        click.echo(f"blocked_hashes={out_path}")

    click.echo(
        "summary "
        f"input_hashes={payload['summary']['input_hashes']} "
        f"plannable={payload['summary']['plannable']} "
        f"blocked={payload['summary']['blocked']} "
        f"errors={payload['summary']['errors']} "
        f"elapsed_s={payload['summary']['elapsed_s']}"
    )
    click.echo(f"manifest_json={manifest_path}")


@cli.command("audit-tags")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
@click.option("--run-id", type=int,
              help="Specific rehome run ID to audit (default: latest successful run)")
@click.option("--samples", type=int, default=5,
              help="How many non-compliant torrent samples to print")
def audit_tags_cmd(catalog, run_id, samples):
    """Audit rehome provenance tags for a run using catalog torrent tag snapshots."""

    def _parse_tags(raw: Optional[str]) -> set[str]:
        if not raw:
            return set()
        return {tag.strip() for tag in str(raw).split(',') if tag and tag.strip()}

    conn = sqlite3.connect(catalog)
    try:
        if run_id is None:
            run_row = conn.execute(
                """
                SELECT id, direction, payload_id, payload_hash, status, started_at, finished_at
                FROM rehome_runs
                WHERE status = 'success'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            if not run_row:
                click.echo("❌ No successful rehome_runs found", err=True)
                raise click.Abort()
        else:
            run_row = conn.execute(
                """
                SELECT id, direction, payload_id, payload_hash, status, started_at, finished_at
                FROM rehome_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if not run_row:
                click.echo(f"❌ Run not found: {run_id}", err=True)
                raise click.Abort()

        run_id_v, direction, payload_id, payload_hash, status, started_at, finished_at = run_row

        if status != 'success':
            click.echo(f"⚠ Run {run_id_v} status is '{status}' (expected success)")

        if direction == 'promote':
            expected_core = {'rehome', 'rehome_from_pool', 'rehome_to_stash'}
        else:
            expected_core = {'rehome', 'rehome_from_stash', 'rehome_to_pool'}

        payload_ids = [payload_id]
        torrents = conn.execute(
            """
            SELECT torrent_hash, tags
            FROM torrent_instances
            WHERE payload_id = ?
            ORDER BY torrent_hash
            """,
            (payload_id,),
        ).fetchall()

        if not torrents and payload_hash:
            payload_rows = conn.execute(
                "SELECT payload_id FROM payloads WHERE payload_hash = ? ORDER BY payload_id",
                (payload_hash,),
            ).fetchall()
            payload_ids = [int(row[0]) for row in payload_rows]
            if payload_ids:
                placeholders = ",".join("?" for _ in payload_ids)
                torrents = conn.execute(
                    f"""
                    SELECT torrent_hash, tags
                    FROM torrent_instances
                    WHERE payload_id IN ({placeholders})
                    ORDER BY torrent_hash
                    """,
                    payload_ids,
                ).fetchall()

        if not torrents:
            click.echo(
                f"⚠ No torrent_instances found for payload_id={payload_id}"
                f" (payload_hash={str(payload_hash)[:16]}...)"
            )
            return

        bad = []
        for torrent_hash, tags_raw in torrents:
            tags = _parse_tags(tags_raw)
            missing_core = sorted(expected_core - tags)
            has_date = any(tag.startswith('rehome_at_') for tag in tags)
            if missing_core or not has_date:
                bad.append((torrent_hash, missing_core, has_date, tags_raw or ''))

        compliant = len(torrents) - len(bad)

        click.echo("🔎 Rehome tag audit")
        click.echo(f"   run_id: {run_id_v}")
        click.echo(f"   direction: {direction}")
        click.echo(f"   payload_hash: {str(payload_hash)[:16]}...")
        click.echo(f"   payload_ids_checked: {payload_ids}")
        click.echo(f"   torrents: {len(torrents)}")
        click.echo(f"   compliant: {compliant}")
        click.echo(f"   non_compliant: {len(bad)}")

        if bad:
            click.echo("   samples:")
            for torrent_hash, missing_core, has_date, raw_tags in bad[: max(1, samples)]:
                missing_str = ','.join(missing_core) if missing_core else '-'
                date_str = 'yes' if has_date else 'no'
                click.echo(
                    f"     {torrent_hash[:16]}... missing_core={missing_str} has_rehome_at={date_str} tags={raw_tags}"
                )
            raise click.exceptions.Exit(1)

        click.echo("✅ Rehome tags are compliant for this run")
    finally:
        conn.close()


@cli.command("apply")
@click.argument("plan_file", type=click.Path(exists=True))
@click.option("--dryrun", is_flag=True,
              help="Show what would happen without making changes")
@click.option("--force", is_flag=True,
              help="Execute the plan (mutually exclusive with --dryrun)")
@click.option("--spot-check", type=int, default=0,
              help="Spot-check N files by SHA256 after payload verification")
@click.option("--rescan", is_flag=True,
              help="Rescan source/target roots after execution to refresh catalog")
@click.option("--cleanup-source-views", is_flag=True,
              help="Remove torrent views at source side (never payload roots)")
@click.option("--cleanup-empty-dirs", is_flag=True,
              help="Remove empty directories under seeding roots only")
@click.option("--cleanup-duplicate-payload", is_flag=True,
              help="Remove source payload root after REUSE (explicit opt-in)")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
def apply_cmd(plan_file, dryrun, force, spot_check, rescan, cleanup_source_views,
              cleanup_empty_dirs, cleanup_duplicate_payload, catalog):
    """
    Apply a demotion plan.

    Use --dryrun to preview actions without making changes.
    Use --force to execute the plan.
    """
    if dryrun and force:
        click.echo("❌ Cannot use --dryrun and --force together", err=True)
        raise click.Abort()

    if not dryrun and not force:
        click.echo("❌ Must specify either --dryrun or --force", err=True)
        raise click.Abort()

    catalog_path = Path(catalog)
    plan_path = Path(plan_file)

    # Load plan
    with open(plan_path) as f:
        plan_data = json.load(f)

    # Check if batch plan
    is_batch = plan_data.get('batch', False)

    if is_batch:
        # Batch plan
        plans = plan_data['plans']
        click.echo(f"📦 Batch plan: {len(plans)} payload(s)")

        # Filter out BLOCKED plans
        executable_plans = [p for p in plans if p['decision'] != 'BLOCK']
        blocked_plans = [p for p in plans if p['decision'] == 'BLOCK']

        if blocked_plans:
            click.echo(f"⚠️  {len(blocked_plans)} payload(s) BLOCKED (will skip)")

        if not executable_plans:
            click.echo("❌ All plans are BLOCKED - nothing to apply", err=True)
            raise click.Abort()

        plans_to_apply = executable_plans
    else:
        # Single plan
        plans_to_apply = [plan_data]

        if plan_data['decision'] == 'BLOCK':
            click.echo("🚫 Plan is BLOCKED - cannot apply")
            click.echo("Reasons:")
            for reason in plan_data['reasons']:
                click.echo(f"   {reason}")
            raise click.Abort()

    # Create executor
    executor = DemotionExecutor(catalog_path=catalog_path)

    # Execute or dry-run
    mode = "DRY-RUN" if dryrun else "EXECUTE"
    click.echo(f"{'🔍' if dryrun else '⚙️'} {mode} MODE")
    click.echo()
    if _debug_enabled():
        click.echo(f"debug_module rehome={Path(rehome.__file__).resolve()}")
        click.echo(f"debug_module rehome.executor={Path(rehome_executor.__file__).resolve()}")
        click.echo(f"debug_module rehome.view_builder={Path(rehome_view_builder.__file__).resolve()}")
        click.echo(f"debug_version rehome={__version__}")

    # Acquire exclusive lock for execute mode — dry-run is read-only and does
    # not need a lock.  Two concurrent execute runs corrupt each other's state
    # (confirmed amplifying factor in Feb-2026 incident).
    lock_fh = None
    if not dryrun:
        lock_fh = _acquire_rehome_lock()

    try:
        for i, plan in enumerate(plans_to_apply, 1):
            if len(plans_to_apply) > 1:
                click.echo(f"--- Plan {i}/{len(plans_to_apply)} ---")
                click.echo(f"Payload: {plan['payload_hash'][:16]}... ({plan['decision']})")

            if dryrun:
                executor.dry_run(
                    plan,
                    cleanup_source_views=cleanup_source_views,
                    cleanup_empty_dirs=cleanup_empty_dirs,
                    cleanup_duplicate_payload=cleanup_duplicate_payload,
                    spot_check=spot_check
                )
            else:
                executor.execute(
                    plan,
                    cleanup_source_views=cleanup_source_views,
                    cleanup_empty_dirs=cleanup_empty_dirs,
                    cleanup_duplicate_payload=cleanup_duplicate_payload,
                    rescan=rescan,
                    spot_check=spot_check
                )

            if len(plans_to_apply) > 1:
                click.echo()

    except Exception as e:
        click.echo(f"❌ {mode} failed: {e}", err=True)
        if _debug_enabled():
            click.echo("debug_traceback_begin", err=True)
            click.echo(traceback.format_exc(), err=True)
            click.echo("debug_traceback_end", err=True)
        raise click.Abort()
    finally:
        if lock_fh is not None:
            lock_fh.close()

    click.echo()
    if dryrun:
        click.echo("✅ Dry-run completed successfully")
        click.echo(f"To execute: rehome apply {plan_file} --force")
    else:
        click.echo("✅ Plan executed successfully")
        # Mandatory post-apply summary: query qBittorrent for final torrent states.
        # Exit non-zero if any torrent is in an alarm/stoppedDL state so CI/scripts
        # can detect silent failures without reading logs.
        all_ok = _print_post_apply_summary(executor, plans_to_apply)
        if not all_ok:
            click.echo(
                "❌ One or more torrents are in alarm state — "
                "investigate before continuing.",
                err=True,
            )
            raise click.exceptions.Exit(1)


@cli.command("followup")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
@click.option("--cleanup", is_flag=True,
              help="Attempt cleanup for groups tagged rehome_cleanup_source_required")
@click.option("--payload-hash", "payload_hashes", multiple=True,
              help="Limit follow-up to specific payload hash(es)")
@click.option("--limit", type=int, default=0,
              help="Max payload groups to process (0 = all)")
@click.option("--retry-failed", is_flag=True,
              help="Include rehome_verify_failed groups in this pass")
@click.option("--strict", is_flag=True,
              help="Exit non-zero if any group remains pending or failed")
@click.option("--output", type=click.Path(),
              help="Write JSON report to file")
@click.option("--print-torrents", is_flag=True,
              help="Print per-torrent follow-up gate details")
def followup_cmd(catalog, cleanup, payload_hashes, limit, retry_failed, strict, output, print_torrents):
    """Run rehome verification follow-up and optional deferred cleanup retry."""
    catalog_path = Path(catalog)
    try:
        report = run_followup(
            catalog_path=catalog_path,
            cleanup=cleanup,
            payload_hashes=set(payload_hashes) if payload_hashes else None,
            limit=limit,
            retry_failed=retry_failed,
        )
    except Exception as e:
        click.echo(f"❌ FOLLOWUP failed: {e}", err=True)
        raise click.Abort()

    summary = report.get("summary", {})
    click.echo("🔁 Rehome follow-up summary")
    click.echo(f"   catalog: {catalog_path}")
    click.echo(f"   groups: {summary.get('groups_total', 0)}")
    click.echo(f"   ok: {summary.get('groups_ok', 0)}")
    click.echo(f"   pending: {summary.get('groups_pending', 0)}")
    click.echo(f"   failed: {summary.get('groups_failed', 0)}")
    click.echo(f"   cleanup_attempted: {summary.get('cleanup_attempted', 0)}")
    click.echo(f"   cleanup_done: {summary.get('cleanup_done', 0)}")
    click.echo(f"   cleanup_failed: {summary.get('cleanup_failed', 0)}")

    for entry in report.get("entries", []):
        payload_hash = str(entry.get("payload_hash", ""))
        click.echo(
            f"payload={payload_hash[:16]} outcome={entry.get('outcome')} "
            f"cleanup_required={str(bool(entry.get('cleanup_required'))).lower()} "
            f"cleanup_result={entry.get('cleanup_result')}"
        )
        db_reasons = entry.get("db_reasons") or []
        source_reasons = entry.get("source_reasons") or []
        if db_reasons:
            click.echo(f"  db_reasons={','.join(db_reasons)}")
        if source_reasons:
            click.echo(f"  source_reasons={','.join(source_reasons)}")
        if print_torrents:
            for gate in entry.get("qb_checks", []):
                reasons = gate.get("reasons") or []
                reason_text = ",".join(reasons) if reasons else "none"
                click.echo(
                    "  torrent="
                    f"{str(gate.get('torrent_hash', ''))[:16]} "
                    f"ok={str(bool(gate.get('ok'))).lower()} "
                    f"progress={gate.get('progress')} "
                    f"state={gate.get('state')} "
                    f"auto_tmm={gate.get('auto_tmm')} "
                    f"reasons={reason_text}"
                )

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        click.echo(f"report={output_path}")

    pending_or_failed = int(summary.get("groups_pending", 0)) + int(summary.get("groups_failed", 0))
    if strict and pending_or_failed > 0:
        raise click.exceptions.Exit(1)


@cli.command("normalize-plan")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
@click.option("--pool-device", type=str, required=True,
              help="Device alias (e.g. 'pool') or integer device_id for pool storage")
@click.option("--pool-seeding-root", type=click.Path(), required=True,
              help="Pool seeding root (example: /pool/data/seeds)")
@click.option("--stash-seeding-root", type=click.Path(),
              help="Optional stash seeding root for source-relative mapping")
@click.option("--payload-hash", "payload_hashes", multiple=True,
              help="Restrict normalization planning to specific payload hash(es)")
@click.option("--limit", type=int, default=0,
              help="Max normalization candidates to include (0 = all)")
@click.option("--flat-only/--all-mismatches", default=True,
              help="Plan only payloads directly under pool root (default) or all mismatches")
@click.option("--output", "-o", type=click.Path(),
              help="Output batch plan JSON (default: rehome-plan-normalize-<timestamp>.json)")
@click.option("--print-skipped", is_flag=True,
              help="Print skipped payload reasons")
@click.option("--refresh-before-plan", is_flag=True,
              help="Refresh qB torrent metadata into catalog before normalization planning")
@click.option("--refresh-category", type=str,
              help="Optional qB category filter for pre-plan refresh")
@click.option("--refresh-tag", type=str,
              help="Optional qB tag filter for pre-plan refresh")
@click.option("--refresh-limit", type=int, default=0,
              help="Optional torrent limit for pre-plan refresh (0 = all in scope)")
def normalize_plan_cmd(
    catalog,
    pool_device,
    pool_seeding_root,
    stash_seeding_root,
    payload_hashes,
    limit,
    flat_only,
    output,
    print_skipped,
    refresh_before_plan,
    refresh_category,
    refresh_tag,
    refresh_limit,
):
    """Create batch plan(s) to normalize pool payload root paths."""
    catalog_path = Path(catalog)

    # Resolve device alias/integer to current device_id
    try:
        from hashall.model import connect_db
        from hashall.device import resolve_device_id
        _resolve_conn = connect_db(catalog_path, read_only=True, apply_migrations=False)
        try:
            pool_device = resolve_device_id(_resolve_conn, pool_device)
        finally:
            _resolve_conn.close()
    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    try:
        if refresh_before_plan:
            _refresh_catalog_from_qb(
                catalog=catalog_path,
                pool_seeding_root=pool_seeding_root,
                category=refresh_category,
                tag=refresh_tag,
                limit=refresh_limit,
            )
        report = build_pool_path_normalization_batch(
            catalog_path=catalog_path,
            pool_device=pool_device,
            pool_seeding_root=pool_seeding_root,
            stash_seeding_root=stash_seeding_root,
            payload_hashes=set(payload_hashes) if payload_hashes else None,
            limit=limit,
            flat_only=flat_only,
        )
    except Exception as e:
        click.echo(f"❌ normalize-plan failed: {e}", err=True)
        raise click.Abort()

    if not output:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        output = f"rehome-plan-normalize-{stamp}.json"

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    summary = report.get("summary", {})
    plans = report.get("plans", [])
    click.echo(f"✅ Normalize plan written to: {output_path}")
    click.echo(
        "summary="
        f"candidates:{summary.get('candidates', 0)} "
        f"reuse:{summary.get('decision_reuse', 0)} "
        f"move:{summary.get('decision_move', 0)} "
        f"skipped:{summary.get('skipped', 0)} "
        f"fallback:{summary.get('fallback_used', 0)} "
        f"review:{summary.get('review_required', 0)}"
    )
    if plans:
        for plan in plans[:5]:
            click.echo(
                f"  {str(plan.get('decision', '')):5s} "
                f"payload={str(plan.get('payload_hash', ''))[:16]} "
                f"source={plan.get('source_path')} "
                f"target={plan.get('target_path')}"
            )
        if len(plans) > 5:
            click.echo(f"  ... ({len(plans) - 5} more)")

    if print_skipped:
        for item in report.get("skipped", []):
            click.echo(
                f"  skipped payload={str(item.get('payload_hash', ''))[:16]} "
                f"reason={item.get('reason')} source={item.get('source_path')}"
            )

    click.echo()
    click.echo(f"Next step: rehome apply {output_path} --dryrun")


@cli.command("auto")
@click.option("--limit", default=5, show_default=True, help="Max candidates to process")
@click.option("--apply", "do_apply", is_flag=True, help="Execute (default: dry-run only)")
@click.option("--refresh", "do_refresh", is_flag=True,
              help="Scan stash/pool roots and sync qBit payloads before finding candidates")
@click.option("--workers", default=8, show_default=True, help="Scan worker threads (used with --refresh)")
@click.option("--stash-device", default=None, help="Override config stash device alias/id")
@click.option("--pool-device", default=None, help="Override config pool device alias/id")
@click.option("--pool-payload-root", default=None, help="Override config pool payload root")
@click.option("--seeding-root", default=None, help="Override config seeding root")
@click.option("--catalog", default=None, help="Override config catalog path")
def auto_cmd(limit, do_apply, do_refresh, workers, stash_device, pool_device,
             pool_payload_root, seeding_root, catalog):
    """Find safe MOVE candidates and rehome them (dry-run by default)."""
    from rehome.config import load_config
    from rehome.auto import run_auto, run_refresh
    from hashall.model import connect_db
    from hashall.device import resolve_device_id

    cfg = load_config()

    catalog_str = catalog or cfg["catalog"]
    catalog_path = Path(catalog_str).expanduser()
    if not catalog_path.exists():
        click.echo(f"❌ Catalog not found: {catalog_path}", err=True)
        raise click.Abort()

    stash_alias = stash_device or cfg["stash_device"]
    pool_alias = pool_device or cfg["pool_device"]
    ppr = pool_payload_root or cfg["pool_payload_root"]
    sr = seeding_root or cfg["seeding_root"]
    lr = cfg["library_root"]

    if do_refresh:
        from rehome.config import parse_extra_scan_roots
        extra_roots = parse_extra_scan_roots(cfg.get("extra_scan_roots") or [])
        refresh_code = run_refresh(
            catalog_path=catalog_path,
            seeding_root=sr,
            pool_payload_root=ppr,
            stash_device=stash_alias,
            pool_device=pool_alias,
            workers=workers,
            skip_dedup=True,
            extra_roots=extra_roots,
        )
        if refresh_code != 0:
            click.echo("❌ Refresh failed — aborting auto", err=True)
            raise click.exceptions.Exit(refresh_code)
        print()

    try:
        _conn = connect_db(catalog_path, read_only=True, apply_migrations=False)
        try:
            stash_id = resolve_device_id(_conn, stash_alias)
            pool_id = resolve_device_id(_conn, pool_alias)
        finally:
            _conn.close()
    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        raise click.Abort()

    log_base = Path.home() / ".logs" / "hashall" / "reports" / "rehome-runs"
    plan_log_dir = log_base / "plans"
    run_log_dir = log_base

    exit_code = run_auto(
        catalog_path=catalog_path,
        stash_device_id=stash_id,
        pool_device_id=pool_id,
        pool_payload_root=ppr,
        seeding_root=sr,
        library_root=lr,
        limit=limit,
        do_apply=do_apply,
        plan_log_dir=plan_log_dir,
        run_log_dir=run_log_dir,
    )
    if exit_code != 0:
        raise click.exceptions.Exit(exit_code)


@cli.command("refresh")
@click.option("--workers", default=8, show_default=True, help="Scan worker threads")
@click.option("--no-dedup", "skip_dedup", is_flag=True,
              help="Skip dedup plan (dedup dry-run runs by default)")
@click.option("--apply-dedup", is_flag=True,
              help="Execute dedup link plan (modifies filesystem)")
@click.option("--stash-device", default=None, help="Override config stash device alias")
@click.option("--pool-device", default=None, help="Override config pool device alias")
@click.option("--seeding-root", default=None, help="Override config seeding root path")
@click.option("--pool-payload-root", default=None, help="Override config pool payload root path")
@click.option("--catalog", default=None, help="Override config catalog path")
def refresh_cmd(workers, skip_dedup, apply_dedup, stash_device, pool_device,
                seeding_root, pool_payload_root, catalog):
    """Scan all roots, upgrade SHA256, run dedup dry-run, then sync qBit payloads.

    Dedup (plan + dry-run) runs by default. Use --no-dedup to skip it.
    Use --apply-dedup to execute the dedup plan (modifies filesystem).
    """
    from rehome.config import load_config, parse_extra_scan_roots
    from rehome.auto import run_refresh

    cfg = load_config()

    catalog_str = catalog or cfg["catalog"]
    catalog_path = Path(catalog_str).expanduser()
    if not catalog_path.exists():
        click.echo(f"❌ Catalog not found: {catalog_path}", err=True)
        raise click.Abort()

    stash_alias = stash_device or cfg["stash_device"]
    pool_alias = pool_device or cfg["pool_device"]
    sr = seeding_root or cfg["seeding_root"]
    ppr = pool_payload_root or cfg["pool_payload_root"]
    extra_roots = parse_extra_scan_roots(cfg.get("extra_scan_roots") or [])

    exit_code = run_refresh(
        catalog_path=catalog_path,
        seeding_root=sr,
        pool_payload_root=ppr,
        stash_device=stash_alias,
        pool_device=pool_alias,
        workers=workers,
        apply_dedup=apply_dedup,
        skip_dedup=skip_dedup,
        extra_roots=extra_roots,
    )
    if exit_code != 0:
        raise click.exceptions.Exit(exit_code)


@cli.group("config")
def config_group():
    """Manage rehome defaults (~/.hashall/rehome.toml)."""


@config_group.command("show")
def config_show():
    """Print current config (file + defaults)."""
    from rehome.config import load_config, CONFIG_PATH
    cfg = load_config()
    click.echo(f"# {CONFIG_PATH}")
    for key, value in sorted(cfg.items()):
        click.echo(f"{key} = {value!r}")


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a scalar config key (writes to ~/.hashall/rehome.toml)."""
    from rehome.config import load_config, save_config_key, DEFAULTS
    scalar_keys = {k for k, v in DEFAULTS.items() if not isinstance(v, list)}
    if key not in scalar_keys:
        known = ", ".join(sorted(scalar_keys))
        click.echo(f"❌ Unknown scalar key '{key}'. Known keys: {known}", err=True)
        click.echo("  (For list keys like extra_scan_roots use: rehome config add-root / remove-root)", err=True)
        raise click.Abort()
    save_config_key(key, value)
    click.echo(f"✅ {key} = {value!r}")


@config_group.command("add-root")
@click.argument("path")
@click.argument("alias")
def config_add_root(path, alias):
    """Add (or update) an extra scan root with its device alias.

    \b
    Example:
      rehome config add-root /mnt/hotspare6tb hotspare6tb
    """
    from rehome.config import add_scan_root
    add_scan_root(path, alias)
    click.echo(f"✅ added extra_scan_root: {path} → {alias}")


@config_group.command("remove-root")
@click.argument("path")
def config_remove_root(path):
    """Remove an extra scan root by path.

    \b
    Example:
      rehome config remove-root /mnt/hotspare6tb
    """
    from rehome.config import remove_scan_root
    removed = remove_scan_root(path)
    if removed:
        click.echo(f"✅ removed extra_scan_root: {path}")
    else:
        click.echo(f"⚠️  no entry found for path: {path}", err=True)
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    cli()
