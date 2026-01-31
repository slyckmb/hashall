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
@click.option("--torrent-hash", required=True,
              help="Torrent hash to demote")
@click.option("--catalog", type=click.Path(exists=True), default=DEFAULT_CATALOG_PATH,
              help="Path to hashall catalog database")
@click.option("--seeding-root", multiple=True, required=True,
              help="Seeding domain root(s) - paths outside these are external consumers")
@click.option("--stash-device", type=int, required=True,
              help="Device ID for stash storage")
@click.option("--pool-device", type=int, required=True,
              help="Device ID for pool storage")
@click.option("--output", "-o", type=click.Path(),
              help="Output plan file (default: rehome-plan-<hash>.json)")
def plan_cmd(demote, torrent_hash, catalog, seeding_root, stash_device, pool_device, output):
    """
    Create a demotion plan for a torrent.

    Analyzes the payload, checks for external consumers, and determines
    whether to BLOCK, REUSE, or MOVE the payload from stash to pool.
    """
    catalog_path = Path(catalog)

    if not catalog_path.exists():
        click.echo(f"❌ Catalog not found: {catalog_path}", err=True)
        raise click.Abort()

    # Default output filename
    if not output:
        output = f"rehome-plan-{torrent_hash[:8]}.json"

    output_path = Path(output)

    # Create planner
    planner = DemotionPlanner(
        catalog_path=catalog_path,
        seeding_roots=list(seeding_root),
        stash_device=stash_device,
        pool_device=pool_device
    )

    # Generate plan
    click.echo(f"📋 Planning demotion for torrent {torrent_hash[:16]}...")

    try:
        plan = planner.plan_demotion(torrent_hash)
    except Exception as e:
        click.echo(f"❌ Planning failed: {e}", err=True)
        raise click.Abort()

    # Write plan to file
    with open(output_path, 'w') as f:
        json.dump(plan, f, indent=2)

    click.echo(f"✅ Plan written to: {output_path}")
    click.echo()

    # Display summary
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
        plan = json.load(f)

    decision = plan['decision']

    if decision == 'BLOCK':
        click.echo("🚫 Plan is BLOCKED - cannot apply")
        click.echo("Reasons:")
        for reason in plan['reasons']:
            click.echo(f"   {reason}")
        raise click.Abort()

    # Create executor
    executor = DemotionExecutor(catalog_path=catalog_path)

    # Execute or dry-run
    mode = "DRY-RUN" if dryrun else "EXECUTE"
    click.echo(f"{'🔍' if dryrun else '⚙️'} {mode} MODE")
    click.echo()

    try:
        if dryrun:
            executor.dry_run(plan)
        else:
            executor.execute(plan)
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
