"""odoodev db - Database operations (backup, restore, list, drop)."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import click
import questionary

from odoodev.cli import resolve_version
from odoodev.click_types import ExpandedPath
from odoodev.core.database import (
    DEFAULT_DEV_PASSWORD,
    anonymize_database,
    anonymize_users,
    backup_database_sql,
    cleanup_restore_temp,
    copy_database,
    copy_filestore,
    create_backup_zip,
    create_database,
    database_exists,
    deactivate_cronjobs,
    detect_backup_type,
    drop_database,
    extract_backup,
    format_size,
    get_active_connection_count,
    get_filestore_path,
    get_restore_temp_dir,
    list_databases,
    neutralize_bank_sync,
    rename_database,
    restore_database,
    run_neutralize,
    terminate_connections,
)
from odoodev.core.version_registry import get_version
from odoodev.output import (
    confirm,
    console,
    path_input,
    print_error,
    print_info,
    print_start_hint,
    print_success,
    print_warning,
    select,
    text_input,
)


def _validate_db_name(name: str) -> bool:
    """Validate a PostgreSQL database name.

    Valid names contain only letters, digits, and underscores,
    must not start with a digit, and must not be empty.
    """
    import re

    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name.strip()))


def _suggest_db_name(backup_file: str) -> str:
    """Suggest a database name from a backup filename.

    Strips date suffixes (e.g. _250305) and extensions.
    """
    import re

    name = os.path.basename(backup_file)
    # Remove extensions (.zip, .sql, .tar.gz, .7z, etc.)
    for ext in (".tar.gz", ".zip", ".7z", ".tgz", ".gz", ".sql", ".dump", ".tar"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    # Strip trailing date suffix like _YYMMDD or _YYYYMMDD
    name = re.sub(r"_\d{6,8}$", "", name)
    return name


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


def _print_migration_hint(version: str) -> None:
    """Print migration mode hint if version is involved in active migration."""
    try:
        from odoodev.core.migration_config import get_active_group

        group = get_active_group()
        if not group:
            return
        if group.to_version == version:
            print_warning(
                f"[MIGRATION] v{version} uses v{group.from_version}'s PostgreSQL "
                f"container (port {group.shared_db_port})"
            )
        elif group.from_version == version:
            print_info(f"[MIGRATION] v{version}'s PostgreSQL is shared with migration target v{group.to_version}")
    except Exception:  # noqa: S110
        pass


@click.group()
def db() -> None:
    """Database operations (backup, restore, list, drop)."""


@db.command("list")
@click.argument("version", required=False)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.pass_context
def db_list(ctx: click.Context, version: str | None, as_json: bool) -> None:
    """List all databases."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    if as_json:
        import json
        import sys

        databases = list_databases(host=params["host"], port=params["port"], user=params["user"])
        payload = {"version": version, "host": params["host"], "port": params["port"], "databases": databases}
        sys.stdout.write(json.dumps(payload) + "\n")
        return

    _print_migration_hint(version)

    databases = list_databases(host=params["host"], port=params["port"], user=params["user"])
    if databases:
        print_info(f"Databases on {params['host']}:{params['port']}:")
        for db_name in databases:
            console.print(f"  {db_name}")
    else:
        print_warning("No databases found (or PostgreSQL not accessible)")


@db.command("drop")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def db_drop(ctx: click.Context, version: str | None, name: str | None, yes: bool) -> None:
    """Drop a database."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _print_migration_hint(version)

    if not name:
        name = _select_database(params)
        if not name:
            raise SystemExit(1)

    filestore_path = get_filestore_path(version, db_name=name)
    has_filestore = os.path.isdir(filestore_path)

    if not yes:
        print_warning("This will permanently delete:")
        print_warning(f"  Database: {name}")
        if has_filestore:
            print_warning(f"  Filestore: {filestore_path}")
        console.print()
        if not confirm("Proceed with deletion? This cannot be undone.", default=False):
            print_info("Aborted.")
            return

    if drop_database(name, host=params["host"], port=params["port"], user=params["user"]):
        print_success(f"Database '{name}' dropped")
    else:
        print_error(f"Failed to drop database '{name}'")
        raise SystemExit(1)

    # Remove filestore directory
    if has_filestore:
        try:
            shutil.rmtree(filestore_path)
            print_success(f"Filestore removed: {filestore_path}")
        except OSError as e:
            print_warning(f"Could not remove filestore: {e}")


def _resolve_copy_names(params: dict, src: str | None, dst: str | None) -> tuple[str, str]:
    """Resolve source/destination names, prompting interactively when omitted.

    Raises SystemExit on invalid input or missing source database.
    """
    if not src:
        src = _select_database(params)
        if not src:
            raise SystemExit(1)
    if not dst:
        dst = text_input("New database name:")
        if not dst:
            print_info("Aborted.")
            raise SystemExit(1)
    dst = dst.strip()

    if not _validate_db_name(dst):
        print_error(f"Invalid database name: '{dst}' (letters, digits, underscores; no leading digit)")
        raise SystemExit(1)
    if not database_exists(src, **params):
        print_error(f"Source database '{src}' does not exist")
        raise SystemExit(1)
    if database_exists(dst, **params):
        print_error(f"Destination database '{dst}' already exists")
        raise SystemExit(1)
    return src, dst


def _ensure_no_connections(name: str, params: dict, terminate: bool, yes: bool) -> None:
    """Abort (SystemExit) unless the database has no active connections.

    With ``terminate`` (or interactive consent), active sessions are killed
    via pg_terminate_backend first.
    """
    count = get_active_connection_count(name, **params)
    if count <= 0:
        return

    print_warning(f"Database '{name}' has {count} active connection(s) (e.g. a running Odoo server)")
    if not terminate and not yes:
        terminate = confirm("Terminate these connections?", default=False)
    if not terminate:
        print_info("Aborted. Stop the Odoo server or pass --terminate-connections.")
        raise SystemExit(1)
    if not terminate_connections(name, **params):
        print_error("Failed to terminate connections")
        raise SystemExit(1)
    print_success(f"Terminated {count} connection(s)")


@db.command("copy")
@click.argument("version", required=False)
@click.option("-s", "--src", help="Source database (interactive selection if omitted)")
@click.option("-d", "--dst", help="New database name (prompted if omitted)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--terminate-connections", "terminate", is_flag=True, help="Kill active connections on source first")
@click.pass_context
def db_copy(
    ctx: click.Context, version: str | None, src: str | None, dst: str | None, yes: bool, terminate: bool
) -> None:
    """Copy a database (incl. filestore) under a new name.

    \b
    Examples:
        odoodev db copy 18 -s v18_prod -d v18_test
        odoodev db copy 18 -s v18_prod -d v18_test --terminate-connections -y
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _print_migration_hint(version)

    src, dst = _resolve_copy_names(params, src, dst)
    _ensure_no_connections(src, params, terminate, yes)

    print_info(f"Copying database '{src}' → '{dst}'...")
    if not copy_database(src, dst, **params):
        print_error("Database copy failed (see log for details)")
        raise SystemExit(1)
    print_success(f"Database '{dst}' created from '{src}'")

    src_fs = get_filestore_path(version, db_name=src)
    if os.path.isdir(src_fs):
        dst_fs = get_filestore_path(version, db_name=dst)
        if copy_filestore(src_fs, dst_fs):
            print_success(f"Filestore copied: {dst_fs}")
        else:
            print_warning("Filestore copy failed — attachments may be missing (non-fatal)")


@db.command("rename")
@click.argument("version", required=False)
@click.option("-s", "--src", help="Database to rename (interactive selection if omitted)")
@click.option("-d", "--dst", help="New database name (prompted if omitted)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--terminate-connections", "terminate", is_flag=True, help="Kill active connections first")
@click.pass_context
def db_rename(
    ctx: click.Context, version: str | None, src: str | None, dst: str | None, yes: bool, terminate: bool
) -> None:
    """Rename a database (incl. filestore directory).

    \b
    Example:
        odoodev db rename 18 -s v18_old -d v18_new
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _print_migration_hint(version)

    src, dst = _resolve_copy_names(params, src, dst)
    _ensure_no_connections(src, params, terminate, yes)

    if not rename_database(src, dst, **params):
        print_error("Database rename failed (see log for details)")
        raise SystemExit(1)
    print_success(f"Database '{src}' renamed to '{dst}'")

    src_fs = get_filestore_path(version, db_name=src)
    if os.path.isdir(src_fs):
        dst_fs = get_filestore_path(version, db_name=dst)
        try:
            shutil.move(src_fs, dst_fs)
            print_success(f"Filestore moved: {dst_fs}")
        except OSError as e:
            print_warning(f"Could not move filestore: {e} (non-fatal)")


@db.command("restore")
@click.argument("version", required=False)
@click.option("-n", "--name", help="New database name (prompted if omitted)")
@click.option("-z", "--backup-file", type=ExpandedPath(), help="Backup file path (prompted if omitted)")
@click.option("--drop/--no-drop", default=True, help="Drop existing database first")
@click.option("--deactivate-cron/--no-deactivate-cron", default=True, help="Deactivate cron jobs after restore")
@click.option(
    "--neutralize/--no-neutralize",
    default=True,
    help="Run native 'odoo-bin neutralize' after restore — on by default",
)
@click.option(
    "--anonymize/--no-anonymize",
    default=True,
    help="Anonymize personal data after restore (GDPR) — on by default",
)
@click.option(
    "--anonymize-users/--no-anonymize-users",
    "anon_users",
    default=False,
    help="Also anonymize res_users logins/passwords (off by default — keeps logins testable)",
)
@click.option(
    "--user-password",
    default=DEFAULT_DEV_PASSWORD,
    show_default=True,
    help="Dev password set on anonymized users (only with --anonymize-users)",
)
@click.option("--keep-temp", is_flag=True, help="Keep extracted temp files")
@click.pass_context
def db_restore(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    backup_file: str | None,
    drop: bool,
    deactivate_cron: bool,
    neutralize: bool,
    anonymize: bool,
    anon_users: bool,
    user_password: str,
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
    _print_migration_hint(version)

    if not backup_file:
        backup_file = path_input("Backup file:")
        if not backup_file or not os.path.exists(backup_file):
            print_error(f"File not found: {backup_file}")
            raise SystemExit(1)

    if not name:
        name = text_input("Database name:", default=_suggest_db_name(backup_file))
        if not name.strip():
            raise SystemExit(1)

    if not _validate_db_name(name):
        print_error(f"Invalid database name: '{name}' (only letters, digits, underscores allowed)")
        raise SystemExit(1)

    backup_file = os.path.abspath(backup_file)
    print_info(f"Restoring database '{name}' from {os.path.basename(backup_file)}")

    # Drop existing
    if drop:
        if not drop_database(name, **params):
            print_error(f"Failed to drop existing database '{name}'")
            raise SystemExit(1)

    # Extract backup — choose temp dir with enough space
    extract_path = get_restore_temp_dir(backup_file)
    print_info(f"Extracting backup to {extract_path}...")
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
        if not deactivate_cronjobs(name, **params):
            print_warning("Cron/mail deactivation failed — some tables may be missing (non-fatal)")

    if neutralize:
        from odoodev.commands.start import resolve_odoo_invocation

        inv = resolve_odoo_invocation(version_cfg, env_vars)
        if inv is None:
            print_warning(
                "Neutralize skipped — venv/odoo-bin/odoo_*.conf not ready "
                f"(run 'odoodev db neutralize {version} -n {name}' after setup)"
            )
        else:
            print_info("Neutralizing database (odoo-bin neutralize)...")
            ok, msg = run_neutralize(name, **inv)
            if ok:
                print_success("Database neutralized")
            else:
                print_warning(f"Neutralize failed (non-fatal): {msg.strip()}")

        # Disable bank synchronisation (not covered by odoo-bin neutralize). Pure
        # psql, so it runs even when native neutralize was skipped above.
        print_info("Disabling bank synchronisation...")
        if not neutralize_bank_sync(name, **params):
            print_warning("Bank-sync neutralization partially failed — some tables may be missing (non-fatal)")

    if anonymize:
        print_info("Anonymizing personal data (GDPR)...")
        if anonymize_database(name, **params):
            print_success("Personal data anonymized")
        else:
            print_warning("Anonymization partially failed — some tables may be missing (non-fatal)")

        if anon_users:
            print_info("Anonymizing res_users (logins + dev password)...")
            if anonymize_users(name, dev_password=user_password, **params):
                print_success(f"User logins anonymized (login: user<id>, password: {user_password})")
            else:
                print_warning("User anonymization failed (table issue) — non-fatal")

    # Cleanup
    if not keep_temp:
        cleanup_restore_temp(extract_path)

    print_success(f"Database '{name}' restore complete")

    console.print()
    print_start_hint(version, name)


@db.command("neutralize")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("--stdout", "to_stdout", is_flag=True, help="Print neutralization SQL instead of applying it")
@click.pass_context
def db_neutralize(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    to_stdout: bool,
) -> None:
    """Neutralize a database via Odoo's native 'odoo-bin neutralize'.

    Disables crons, mail servers, payment providers, IAP, webhooks and more by
    running each installed module's data/neutralize.sql. Requires a ready dev
    environment (venv, server checkout, generated odoo_*.conf).
    """
    from odoodev.commands.start import resolve_odoo_invocation

    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    if not name:
        name = _select_database(params)
        if not name:
            raise SystemExit(1)

    if not _validate_db_name(name):
        print_error(f"Invalid database name: '{name}'")
        raise SystemExit(1)

    inv = resolve_odoo_invocation(version_cfg, env_vars)
    if inv is None:
        print_error(
            "Cannot neutralize — venv, odoo-bin or odoo_*.conf not found. Run 'odoodev init' / 'odoodev repos' first."
        )
        raise SystemExit(1)

    extra = ["--stdout"] if to_stdout else None
    print_info(f"Neutralizing database '{name}' (odoo-bin neutralize)...")
    ok, output = run_neutralize(name, **inv, extra=extra)
    if not ok:
        print_error(f"Neutralization failed: {output.strip()}")
        raise SystemExit(1)

    if to_stdout:
        console.print(output)
    else:
        print_success(f"Database '{name}' neutralized")
        print_info("Disabling bank synchronisation...")
        if not neutralize_bank_sync(name, **params):
            print_warning("Bank-sync neutralization partially failed — some tables may be missing (non-fatal)")


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
    try:
        return select("Select database:", choices=databases)
    except SystemExit:
        return None


def _select_backup_type(version: str, db_name: str) -> str | None:
    """Interactive backup type selection.

    Returns:
        'sql' or 'zip', or None if aborted.
    """
    filestore_path = get_filestore_path(version, db_name)
    has_filestore = os.path.isdir(filestore_path)

    choices = [
        questionary.Choice("SQL — pg_dump only", value="sql"),
    ]
    if has_filestore:
        choices.append(questionary.Choice("ZIP — SQL + filestore", value="zip"))
    else:
        choices.append(questionary.Choice("ZIP — SQL only (no filestore found)", value="zip"))

    try:
        return select("Backup type:", choices=choices)
    except SystemExit:
        return None


@db.command("backup")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("-t", "--type", "backup_type", type=click.Choice(["sql", "zip"]), help="Backup type")
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=ExpandedPath(),
    default=None,
    help="Output directory (default: ~/Downloads)",
)
@click.pass_context
def db_backup(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    backup_type: str | None,
    output_dir: str | None,
) -> None:
    """Create a database backup (SQL dump or ZIP with filestore).

    Without options, interactively selects database and backup type.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _print_migration_hint(version)

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

    # Prepare output (default to the user's Downloads folder, same convention
    # as the TUI module-CSV export)
    output_dir = os.path.abspath(output_dir or str(Path.home() / "Downloads"))
    os.makedirs(output_dir, exist_ok=True)
    date_suffix = datetime.now().strftime("%y%m%d")

    if backup_type == "sql":
        output_file = os.path.join(output_dir, f"{name}_{date_suffix}.sql")
        print_info(f"Creating SQL backup of '{name}'...")

        if not backup_database_sql(name, output_file, **params):
            print_error("Backup failed")
            raise SystemExit(1)

        size = format_size(os.path.getsize(output_file))
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

            size = format_size(os.path.getsize(output_file))
            print_success(f"Backup created: {output_file} ({size})")

        finally:
            try:
                shutil.rmtree(tmp_dir)
            except OSError as e:
                print_warning(f"Could not remove temp directory: {e}")
