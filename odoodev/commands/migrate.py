"""odoodev migrate - Migration mode for cross-version database migrations."""

from __future__ import annotations

import os
import subprocess

import click

from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import print_error, print_info, print_success, print_warning


@click.group()
def migrate() -> None:
    """Manage migration groups for cross-version database migrations.

    Migration mode allows sharing a PostgreSQL container and filestore
    between two Odoo versions during database migration.

    Only the database and filestore are shared — each version keeps its
    own venv, odoo-bin, configuration, and repositories.
    """


@migrate.command("create")
@click.option("--from", "from_version", required=True, help="Source Odoo version (e.g., 16)")
@click.option("--to", "to_version", required=True, help="Target Odoo version (e.g., 18)")
@click.option("--name", default=None, help="Group name (default: {from}-to-{to})")
@click.option("--pg-version", default=None, help="PostgreSQL image override (default: source version's image)")
def migrate_create(from_version: str, to_version: str, name: str | None, pg_version: str | None) -> None:
    """Create a new migration group."""
    from odoodev.core.migration_config import create_migration_group

    from_version = str(from_version)
    to_version = str(to_version)

    # Validate versions exist
    versions = load_versions()
    try:
        source_cfg = get_version(from_version, versions)
    except KeyError:
        print_error(f"Source version '{from_version}' not found in version registry")
        raise SystemExit(1) from None

    try:
        target_cfg = get_version(to_version, versions)
    except KeyError:
        print_error(f"Target version '{to_version}' not found in version registry")
        raise SystemExit(1) from None

    if from_version == to_version:
        print_error("Source and target version must be different")
        raise SystemExit(1)

    # Determine PostgreSQL version
    if pg_version is None:
        pg_version = source_cfg.postgres
        # Warn if source and target use different PG major versions
        source_pg_major = source_cfg.postgres.split(".")[0]
        target_pg_major = target_cfg.postgres.split(".")[0]
        if source_pg_major != target_pg_major:
            print_warning(
                f"PostgreSQL version conflict: "
                f"v{from_version} uses postgres:{source_cfg.postgres}, "
                f"v{to_version} uses postgres:{target_cfg.postgres}"
            )
            print_info(f"Shared container will use source version: postgres:{source_cfg.postgres}")
            print_info("Use --pg-version to override if needed")

    # Build shared filestore path
    group_name = name or f"{from_version}-to-{to_version}"
    shared_filestore_base = os.path.join("~", "odoo-share", "migration", group_name)

    try:
        group = create_migration_group(
            from_version=from_version,
            to_version=to_version,
            pg_version=pg_version,
            shared_db_port=source_cfg.ports.db,
            shared_filestore_base=shared_filestore_base,
            name=group_name,
        )
        print_success(f"Migration group '{group.name}' created")
        _print_group_summary(group)
        print_info(f"Activate with: odoodev migrate activate {group.name}")
    except ValueError as e:
        print_error(str(e))
        raise SystemExit(1) from None


@migrate.command("activate")
@click.argument("name")
def migrate_activate(name: str) -> None:
    """Activate a migration group.

    When active, the target version's database commands use the source
    version's PostgreSQL container and a shared filestore path.
    """
    from odoodev.core.migration_config import activate_migration, load_migration_config

    config = load_migration_config()
    if config.active and config.active != name:
        print_warning(f"Deactivating current migration '{config.active}' first")

    try:
        group = activate_migration(name)
        print_success(f"Migration '{name}' activated")
        _print_group_summary(group)
        print_info(
            f"v{group.to_version} now uses v{group.from_version}'s PostgreSQL container (port {group.shared_db_port})"
        )
    except KeyError as e:
        print_error(str(e))
        raise SystemExit(1) from None


@migrate.command("deactivate")
def migrate_deactivate() -> None:
    """Deactivate the current migration group.

    Restores normal per-version isolation. Does not stop any containers.
    """
    from odoodev.core.migration_config import deactivate_migration, load_migration_config

    config = load_migration_config()
    if not config.active:
        print_info("No migration group is currently active")
        return

    active_name = config.active
    deactivate_migration()
    print_success(f"Migration '{active_name}' deactivated")
    print_info("All versions now use their own isolated environments")


@migrate.command("status")
def migrate_status() -> None:
    """Show migration status and active group details."""
    from odoodev.core.migration_config import load_migration_config

    config = load_migration_config()

    if not config.active:
        print_info("No migration group is currently active")
        if config.groups:
            print_info(f"Available groups: {', '.join(sorted(config.groups.keys()))}")
            print_info("Activate with: odoodev migrate activate <name>")
        return

    group = config.groups.get(config.active)
    if not group:
        print_warning(f"Active group '{config.active}' not found in config")
        return

    from rich.table import Table

    from odoodev.output import console

    table = Table(title=f"Migration: {group.name} [ACTIVE]", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Source", f"v{group.from_version} (postgres:{group.pg_version})")
    table.add_row("Target", f"v{group.to_version} → redirected to port {group.shared_db_port}")
    table.add_row("Shared DB Port", str(group.shared_db_port))

    filestore_path = os.path.expanduser(group.shared_filestore_base)
    filestore_exists = os.path.isdir(os.path.join(filestore_path, "filestore"))
    fs_status = "[green](exists)[/green]" if filestore_exists else "[yellow](not yet created)[/yellow]"
    table.add_row("Shared Filestore", f"{group.shared_filestore_base} {fs_status}")
    table.add_row("Created", group.created_at[:19] if group.created_at else "unknown")

    # Check if source container is running
    container_status = _check_container_running(group.from_version)
    table.add_row("Source Container", container_status)

    console.print(table)


@migrate.command("list")
def migrate_list() -> None:
    """List all defined migration groups."""
    from odoodev.core.migration_config import load_migration_config

    config = load_migration_config()

    if not config.groups:
        print_info("No migration groups defined")
        print_info("Create one with: odoodev migrate create --from 16 --to 18")
        return

    from rich.table import Table

    from odoodev.output import console

    table = Table(title="Migration Groups")
    table.add_column("Name", style="bold")
    table.add_column("From")
    table.add_column("To")
    table.add_column("PostgreSQL")
    table.add_column("Shared Port")
    table.add_column("Status")

    for name, group in sorted(config.groups.items()):
        is_active = config.active == name
        status = "[green]ACTIVE[/green]" if is_active else "inactive"
        table.add_row(
            name,
            f"v{group.from_version}",
            f"v{group.to_version}",
            group.pg_version,
            str(group.shared_db_port),
            status,
        )

    console.print(table)


@migrate.command("remove")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Force removal even if active")
def migrate_remove(name: str, yes: bool) -> None:
    """Remove a migration group definition."""
    from odoodev.core.migration_config import remove_migration_group

    try:
        remove_migration_group(name, force=yes)
        print_success(f"Migration group '{name}' removed")
    except KeyError as e:
        print_error(str(e))
        raise SystemExit(1) from None
    except ValueError as e:
        print_error(str(e))
        raise SystemExit(1) from None


def _print_group_summary(group) -> None:
    """Print a compact summary of a migration group."""
    print_info(f"  Source:    v{group.from_version} (postgres:{group.pg_version})")
    print_info(f"  Target:    v{group.to_version}")
    print_info(f"  DB Port:   {group.shared_db_port}")
    print_info(f"  Filestore: {group.shared_filestore_base}")


def _check_container_running(version: str) -> str:
    """Check if the source version's PostgreSQL container is running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name=dev-db-{version}-native", "--format", "{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = result.stdout.strip()
        if status:
            return f"[green]running[/green] ({status})"
        return "[yellow]not running[/yellow]"
    except Exception:
        return "[dim]unknown[/dim]"
