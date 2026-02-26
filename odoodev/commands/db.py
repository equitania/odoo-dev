"""odoodev db - Database operations (backup, restore, list, drop)."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime

import click

from odoodev.cli import resolve_version
from odoodev.core.database import (
    backup_database_sql,
    copy_filestore,
    create_backup_zip,
    create_database,
    database_exists,
    deactivate_cloud,
    deactivate_cronjobs,
    detect_backup_type,
    drop_database,
    extract_backup,
    get_filestore_path,
    list_databases,
    restore_database,
)
from odoodev.core.version_registry import get_version
from odoodev.output import confirm, console, print_error, print_info, print_success, print_warning


def _get_db_params(version_cfg, env_vars: dict[str, str] | None = None) -> dict:
    """Get database connection parameters."""
    if env_vars is None:
        env_vars = {}
    return {
        "host": env_vars.get("PGHOST", "localhost"),
        "port": int(env_vars.get("DB_PORT", str(version_cfg.ports.db))),
        "user": env_vars.get("PGUSER", "ownerp"),
    }


def _load_env_vars(version_cfg) -> dict[str, str]:
    """Load .env file for the version."""
    env_file = os.path.join(version_cfg.paths.native_dir, ".env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()
    return env_vars


@click.group()
def db() -> None:
    """Database operations (backup, restore, list, drop)."""


@db.command("list")
@click.argument("version", required=False)
@click.pass_context
def db_list(ctx: click.Context, version: str | None) -> None:
    """List all databases."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    databases = list_databases(host=params["host"], port=params["port"], user=params["user"])
    if databases:
        print_info(f"Databases on {params['host']}:{params['port']}:")
        for db_name in databases:
            console.print(f"  {db_name}")
    else:
        print_warning("No databases found (or PostgreSQL not accessible)")


@db.command("drop")
@click.argument("version", required=False)
@click.option("-n", "--name", required=True, help="Database name to drop")
@click.pass_context
def db_drop(ctx: click.Context, version: str | None, name: str) -> None:
    """Drop a database."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    if not confirm(f"Drop database '{name}'? This cannot be undone.", default=False):
        print_info("Aborted.")
        return

    if drop_database(name, host=params["host"], port=params["port"], user=params["user"]):
        print_success(f"Database '{name}' dropped")
    else:
        print_error(f"Failed to drop database '{name}'")
        raise SystemExit(1)


@db.command("restore")
@click.argument("version", required=False)
@click.option("-n", "--name", required=True, help="New database name")
@click.option("-z", "--backup-file", required=True, type=click.Path(exists=True), help="Backup file path")
@click.option("--drop/--no-drop", default=True, help="Drop existing database first")
@click.option("--deactivate-cron/--no-deactivate-cron", default=True, help="Deactivate cron jobs after restore")
@click.option(
    "--deactivate-cloud-integrations/--no-deactivate-cloud-integrations",
    "deactivate_cloud_flag",
    default=True,
    help="Deactivate cloud integrations",
)
@click.option("--keep-temp", is_flag=True, help="Keep extracted temp files")
@click.pass_context
def db_restore(
    ctx: click.Context,
    version: str | None,
    name: str,
    backup_file: str,
    drop: bool,
    deactivate_cron: bool,
    deactivate_cloud_flag: bool,
    keep_temp: bool,
) -> None:
    """Restore a database from backup file.

    Supports ZIP, 7z, tar, gz, and SQL formats.
    Automatically detects backup structure and handles filestore.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    backup_file = os.path.abspath(backup_file)
    print_info(f"Restoring database '{name}' from {os.path.basename(backup_file)}")

    # Drop existing
    if drop:
        if not drop_database(name, **params):
            print_error(f"Failed to drop existing database '{name}'")
            raise SystemExit(1)

    # Extract backup
    extract_path = tempfile.mkdtemp(prefix="odoodev_restore_")
    print_info("Extracting backup...")
    if not extract_backup(backup_file, extract_path):
        print_error("Backup extraction failed")
        raise SystemExit(1)

    # Detect structure
    backup_info = detect_backup_type(extract_path)
    if not backup_info:
        print_error("Could not detect backup structure (no dump.sql found)")
        raise SystemExit(1)

    sql_file = backup_info["sql_file"]
    filestore_src = backup_info.get("filestore")

    # Create and restore
    print_info("Creating database...")
    if not create_database(name, **params):
        print_error(f"Failed to create database '{name}'")
        raise SystemExit(1)

    print_info("Restoring database (this may take a while)...")
    if not restore_database(name, sql_file, **params):
        print_error("Database restore failed")
        raise SystemExit(1)

    print_success(f"Database '{name}' restored successfully")

    # Copy filestore
    if filestore_src and os.path.isdir(filestore_src):
        filestore_dest = get_filestore_path(version, name)
        print_info(f"Copying filestore to {filestore_dest}...")
        if copy_filestore(filestore_src, filestore_dest):
            print_success("Filestore copied")
        else:
            print_warning("Filestore copy failed — attachments may be missing")

    # Post-restore operations
    if deactivate_cron:
        print_info("Deactivating cron jobs and mail servers...")
        deactivate_cronjobs(name, **params)

    if deactivate_cloud_flag:
        print_info("Deactivating cloud integrations...")
        deactivate_cloud(name, **params)

    # Cleanup
    if not keep_temp:
        try:
            shutil.rmtree(extract_path)
        except OSError:
            print_warning(f"Could not remove temp files: {extract_path}")

    print_success(f"Database '{name}' restore complete")


def _select_database(params: dict) -> str | None:
    """Interactive database selection.

    Returns:
        Selected database name, or None if aborted.
    """
    databases = list_databases(host=params["host"], port=params["port"], user=params["user"])
    if not databases:
        print_error("No databases found (or PostgreSQL not accessible)")
        return None

    print_info(f"Available databases ({len(databases)}):")
    for i, db_name in enumerate(databases, 1):
        console.print(f"  [bold]{i}[/bold]) {db_name}")

    choice = console.input("\nSelect database (number or name): ").strip()
    if not choice:
        return None

    # Try as number
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(databases):
            return databases[idx]
        print_error(f"Invalid number: {choice}")
        return None
    except ValueError:
        pass

    # Try as name
    if choice in databases:
        return choice

    print_error(f"Database not found: {choice}")
    return None


def _select_backup_type(version: str, db_name: str) -> str | None:
    """Interactive backup type selection.

    Returns:
        'sql' or 'zip', or None if aborted.
    """
    filestore_path = get_filestore_path(version, db_name)
    has_filestore = os.path.isdir(filestore_path)

    console.print("\nBackup type:")
    console.print("  [bold]1[/bold]) SQL — pg_dump only")
    if has_filestore:
        console.print("  [bold]2[/bold]) ZIP — SQL + filestore (Odoo standard format)")
    else:
        console.print("  [dim]  2) ZIP — SQL + filestore (no filestore found)[/dim]")

    choice = console.input("\nSelect type [1]: ").strip()
    if not choice or choice == "1":
        return "sql"
    if choice == "2":
        if not has_filestore:
            if not confirm("No filestore found. Create ZIP with SQL only?", default=True):
                return None
        return "zip"

    print_error(f"Invalid choice: {choice}")
    return None


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@db.command("backup")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("-t", "--type", "backup_type", type=click.Choice(["sql", "zip"]), help="Backup type")
@click.option("-o", "--output", "output_dir", type=click.Path(), default=".", help="Output directory (default: .)")
@click.pass_context
def db_backup(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    backup_type: str | None,
    output_dir: str,
) -> None:
    """Create a database backup (SQL dump or ZIP with filestore).

    Without options, interactively selects database and backup type.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    # Check PostgreSQL accessibility
    from odoodev.core.prerequisites import check_port

    if not check_port(params["host"], params["port"]):
        print_error(f"PostgreSQL not accessible on {params['host']}:{params['port']}")
        print_info("Start Docker services: odoodev docker up")
        raise SystemExit(1)

    # Select database
    if not name:
        name = _select_database(params)
        if not name:
            raise SystemExit(1)
    else:
        if not database_exists(name, host=params["host"], port=params["port"], user=params["user"]):
            print_error(f"Database '{name}' does not exist")
            raise SystemExit(1)

    # Select backup type
    if not backup_type:
        backup_type = _select_backup_type(version, name)
        if not backup_type:
            raise SystemExit(1)

    # Prepare output
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    date_suffix = datetime.now().strftime("%y%m%d")

    if backup_type == "sql":
        output_file = os.path.join(output_dir, f"{name}_{date_suffix}.sql")
        print_info(f"Creating SQL backup of '{name}'...")

        if not backup_database_sql(name, output_file, **params):
            print_error("Backup failed")
            raise SystemExit(1)

        size = _format_size(os.path.getsize(output_file))
        print_success(f"Backup created: {output_file} ({size})")

    else:
        # ZIP: dump SQL to temp, then create ZIP
        tmp_dir = tempfile.mkdtemp(prefix="odoodev_backup_")
        try:
            sql_path = os.path.join(tmp_dir, "dump.sql")
            print_info(f"Dumping database '{name}'...")

            if not backup_database_sql(name, sql_path, **params):
                print_error("Database dump failed")
                raise SystemExit(1)

            filestore_path = get_filestore_path(version, name)
            fs_dir = filestore_path if os.path.isdir(filestore_path) else None

            output_file = os.path.join(output_dir, f"{name}_{date_suffix}.zip")
            print_info("Creating ZIP backup...")

            if fs_dir:
                print_info(f"Including filestore: {fs_dir}")

            if not create_backup_zip(sql_path, output_file, fs_dir):
                print_error("ZIP creation failed")
                raise SystemExit(1)

            size = _format_size(os.path.getsize(output_file))
            print_success(f"Backup created: {output_file} ({size})")

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
