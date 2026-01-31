"""
Command-line interface for rehome.
"""

import click
import json
from pathlib import Path
from typing import Optional

from rehome import __version__
from rehome.planner import DemotionPlanner
from rehome.executor import DemotionExecutor

DEFAULT_CATALOG_PATH = Path.home() / ".hashall" / "catalog.db"


@click.group()
@click.version_option(__version__)
def cli():
    """Rehome - Seed payload demotion orchestrator."""
    pass


@cli.command("plan")
@click.option("--demote", is_flag=True, required=True,
              help="Plan demotion from stash to pool")
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
@click.option("--stash-device", type=int, required=True,
              help="Device ID for stash storage")
@click.option("--pool-device", type=int, required=True,
              help="Device ID for pool storage")
@click.option("--output", "-o", type=click.Path(),
              help="Output plan file (default: rehome-plan-<mode>.json)")
def plan_cmd(demote, torrent_hash, payload_hash, tag, catalog, seeding_root, stash_device, pool_device, output):
    """
    Create a demotion plan for torrents.

    Supports three modes:
    - Single torrent: --torrent-hash <hash>
    - Batch by payload: --payload-hash <hash>
    - Batch by tag: --tag <tag>

    Analyzes payloads, checks for external consumers, and determines
    whether to BLOCK, REUSE, or MOVE each payload from stash to pool.
    """
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

    # Create planner
    planner = DemotionPlanner(
        catalog_path=catalog_path,
        seeding_roots=list(seeding_root),
        stash_device=stash_device,
        pool_device=pool_device
    )

    # Generate plan(s) based on mode
    try:
        if torrent_hash:
            # Single-torrent mode
            mode = "torrent"
            filter_val = torrent_hash
            click.echo(f"📋 Planning demotion for torrent {torrent_hash[:16]}...")
            plans = [planner.plan_demotion(torrent_hash)]

        elif payload_hash:
            # Batch mode by payload hash
            mode = "payload"
            filter_val = payload_hash
            click.echo(f"📋 Planning batch demotion for payload {payload_hash[:16]}...")
            plans = [planner.plan_batch_demotion_by_payload_hash(payload_hash)]

        elif tag:
            # Batch mode by tag
            mode = "tag"
            filter_val = tag
            click.echo(f"📋 Planning batch demotion for tag '{tag}'...")
            plans = planner.plan_batch_demotion_by_tag(tag)

    except Exception as e:
        click.echo(f"❌ Planning failed: {e}", err=True)
        raise click.Abort()

    # Default output filename
    if not output:
        if mode == "torrent":
            output = f"rehome-plan-{filter_val[:8]}.json"
        else:
            safe_filter = filter_val[:16] if mode == "payload" else filter_val.replace('/', '-')
            output = f"rehome-plan-{mode}-{safe_filter}.json"

    output_path = Path(output)

    # Write plan(s) to file
    if len(plans) == 1:
        with open(output_path, 'w') as f:
            json.dump(plans[0], f, indent=2)
    else:
        # Multiple plans - write as batch
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
            click.echo("🚫 BLOCKED - External consumers detected:")
            for reason in plan['reasons']:
                click.echo(f"   {reason}")
        elif decision == 'REUSE':
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


@cli.command("apply")
@click.argument("plan_file", type=click.Path(exists=True))
@click.option("--dryrun", is_flag=True,
              help="Show what would happen without making changes")
@click.option("--force", is_flag=True,
              help="Execute the plan (mutually exclusive with --dryrun)")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
def apply_cmd(plan_file, dryrun, force, catalog):
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

    try:
        for i, plan in enumerate(plans_to_apply, 1):
            if len(plans_to_apply) > 1:
                click.echo(f"--- Plan {i}/{len(plans_to_apply)} ---")
                click.echo(f"Payload: {plan['payload_hash'][:16]}... ({plan['decision']})")

            if dryrun:
                executor.dry_run(plan)
            else:
                executor.execute(plan)

            if len(plans_to_apply) > 1:
                click.echo()

    except Exception as e:
        click.echo(f"❌ {mode} failed: {e}", err=True)
        raise click.Abort()

    click.echo()
    if dryrun:
        click.echo("✅ Dry-run completed successfully")
        click.echo(f"To execute: rehome apply {plan_file} --force")
    else:
        click.echo("✅ Plan executed successfully")


if __name__ == "__main__":
    cli()
