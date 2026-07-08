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
    check_restore_space,
    cleanup_restore_temp,
    copy_database,
    copy_filestore,
    create_backup_tar_zst,
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
    move_filestore,
    neutralize_bank_sync,
    parse_module_names,
    purge_transactional_data,
    rename_database,
    resolve_purge_tables,
    restore_database,
    run_neutralize,
    run_recompute,
    run_uninstall_modules,
    terminate_connections,
    wipe_database,
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
    # Remove extensions (.zip, .sql, .tar.zst, .tar.gz, .7z, etc.)
    # Longer compound suffixes must come first so the right one strips.
    for ext in (".tar.zst", ".tar.gz", ".zip", ".7z", ".tgz", ".gz", ".sql", ".dump", ".tar"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    # Strip trailing date suffix like _YYMMDD or _YYYYMMDD
    name = re.sub(r"_\d{6,8}$", "", name)
    return name


def _get_db_params(version_cfg, env_vars: dict[str, str] | None = None) -> dict:
    """Get database connection parameters.

    Port resolution goes through ``resolve_db_port`` so an active migration's
    shared port wins over the target version's stale .env DB_PORT.
    """
    from odoodev.core.migration_config import resolve_db_port

    if env_vars is None:
        env_vars = {}
    return {
        "host": env_vars.get("PGHOST", "localhost"),
        "port": resolve_db_port(version_cfg.version, version_cfg.ports.db, env_vars),
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


def _ensure_pg_reachable(version: str, params: dict) -> None:
    """Fail fast with an actionable message if PostgreSQL cannot be used at all.

    Two independent things must hold: the port must be reachable (container or
    daemon running) and *some* way to run psql/pg_dump must exist — host client
    tools or the container exec fallback. Never lets a bare
    FileNotFoundError traceback surface to the user.
    """
    from odoodev.core.prerequisites import check_pg_exec_available, check_port

    if not check_port(params["host"], params["port"]):
        print_error(f"PostgreSQL not accessible on {params['host']}:{params['port']}")
        print_info(f"Start Docker services: odoodev docker up {version}")
        raise SystemExit(1)

    if not check_pg_exec_available(params["port"]):
        print_error("No PostgreSQL client tools found on this host, and no matching database container detected.")
        print_info(
            "Option 1: install client tools — "
            "sudo apt-get install -y postgresql-client (Linux) / brew install libpq (macOS)"
        )
        print_info(f"Option 2: start the database container — odoodev docker up {version}")
        raise SystemExit(1)


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
    _ensure_pg_reachable(version, params)

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
    _ensure_pg_reachable(version, params)

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
    _ensure_pg_reachable(version, params)

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
    _ensure_pg_reachable(version, params)

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
@click.option(
    "--sanitize",
    is_flag=True,
    help="Enable all post-restore processing at once (deactivate-cron + neutralize + anonymize + wipe); "
    "explicit --no-* flags win over --sanitize",
)
@click.option(
    "--deactivate-cron/--no-deactivate-cron",
    default=None,
    help="Deactivate cron jobs and mail servers after restore — OFF by default",
)
@click.option(
    "--neutralize/--no-neutralize",
    default=None,
    help="Run native 'odoo-bin neutralize' after restore — OFF by default",
)
@click.option(
    "--anonymize/--no-anonymize",
    default=None,
    help="Anonymize personal data with Faker after restore (GDPR) — OFF by default",
)
@click.option(
    "--wipe/--no-wipe",
    default=None,
    help="Delete/blank message and attachment content (mail_message, ir_attachment, linkage tables) — OFF by default",
)
@click.option(
    "--purge-transactions/--no-purge-transactions",
    "purge_transactions",
    default=None,
    help="Delete all movement data (stock/sale/purchase/account/mrp/pos), zero stock; keep products, "
    "pricelists, partners — OFF by default, NOT included in --sanitize",
)
@click.option(
    "--recompute/--no-recompute",
    default=None,
    help="Recompute stored computed fields (complete_name, ...) after anonymize so overviews show "
    "anonymized data — auto-runs when --anonymize ran",
)
@click.option(
    "--anonymize-users/--no-anonymize-users",
    "anon_users",
    default=False,
    help="Anonymize res_users logins/passwords — OFF by default, NOT included in --sanitize",
)
@click.option(
    "--user-password",
    default=DEFAULT_DEV_PASSWORD,
    show_default=True,
    help="Dev password set on anonymized users (only with --anonymize-users)",
)
@click.option(
    "--uninstall-modules",
    "uninstall_modules_raw",
    default=None,
    help="Comma-separated technical module names to uninstall before the sanitize steps run "
    "(prompted when omitted, interactive, and a sanitize step is enabled)",
)
@click.option("-y", "--yes", "yes_flag", is_flag=True, help="Skip confirmation prompts")
@click.option("--keep-temp", is_flag=True, help="Keep extracted temp files (filestore is copied, not moved)")
@click.option(
    "--check-space/--no-check-space",
    default=True,
    help="Check free disk space before extracting the backup — on by default",
)
@click.option(
    "--delete-backup",
    is_flag=True,
    help="Delete the original backup file after a successful restore (no prompt)",
)
@click.option(
    "--keep-backup",
    is_flag=True,
    help="Never delete or ask about the original backup file (for scripts)",
)
@click.pass_context
def db_restore(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    backup_file: str | None,
    drop: bool,
    sanitize: bool,
    deactivate_cron: bool | None,
    neutralize: bool | None,
    anonymize: bool | None,
    wipe: bool | None,
    purge_transactions: bool | None,
    recompute: bool | None,
    anon_users: bool,
    user_password: str,
    uninstall_modules_raw: str | None,
    yes_flag: bool,
    keep_temp: bool,
    check_space: bool,
    delete_backup: bool,
    keep_backup: bool,
) -> None:
    """Restore a database from backup file.

    Supports ZIP, 7z, tar, tar.zst, gz, and SQL formats.
    Automatically detects backup structure and handles filestore.

    By default the restored database is left completely untouched. All
    post-restore processing (cron deactivation, neutralize, anonymize, wipe)
    is opt-in — enable individually or all at once with --sanitize.
    --purge-transactions (movement-data reset) is a separate opt-in, NOT in
    --sanitize.
    """
    # Resolve tri-state toggles: explicit flag > --sanitize > off.
    deactivate_cron = deactivate_cron if deactivate_cron is not None else sanitize
    neutralize = neutralize if neutralize is not None else sanitize
    anonymize = anonymize if anonymize is not None else sanitize
    wipe = wipe if wipe is not None else sanitize
    # Purge is deliberately NOT part of --sanitize (destructive, specific use case).
    purge_transactions = bool(purge_transactions)
    # Recompute auto-runs after anonymize unless explicitly disabled.
    recompute = recompute if recompute is not None else anonymize
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _print_migration_hint(version)
    _ensure_pg_reachable(version, params)

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

    # Modules to uninstall before sanitizing (some modules break the sanitize
    # steps). Asked up front so all interactive questions precede the
    # destructive work.
    uninstall_modules = parse_module_names(uninstall_modules_raw)
    if uninstall_modules_raw is None and not yes_flag and any((deactivate_cron, neutralize, anonymize, wipe)):
        answer = text_input(
            "Modules to uninstall before sanitizing (comma-separated technical names, Enter to skip):",
            default="",
        )
        uninstall_modules = parse_module_names(answer)

    backup_file = os.path.abspath(backup_file)
    print_info(f"Restoring database '{name}' from {os.path.basename(backup_file)}")

    # Drop existing
    if drop:
        if not drop_database(name, **params):
            print_error(f"Failed to drop existing database '{name}'")
            raise SystemExit(1)

    # Extract backup — choose temp dir with enough space
    extract_path = get_restore_temp_dir(backup_file)

    # Disk-space pre-check — warn early instead of failing mid-copy
    if check_space:
        filestore_dest = get_filestore_path(version, name)
        enough, space_msg, _ = check_restore_space(backup_file, extract_path, filestore_dest)
        if not enough:
            print_warning(space_msg)
            if not confirm("Continue anyway?", default=False):
                print_info("Aborted.")
                cleanup_restore_temp(extract_path)
                raise SystemExit(0)

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

    # Transfer filestore. Default: move (rename on same filesystem = no double
    # storage). With --keep-temp we copy instead, so the extracted temp dir
    # stays intact for debugging.
    if filestore_src and os.path.isdir(filestore_src):
        filestore_dest = get_filestore_path(version, name)
        if keep_temp:
            print_info(f"Copying filestore to {filestore_dest}...")
            ok_fs = copy_filestore(filestore_src, filestore_dest)
        else:
            print_info(f"Moving filestore to {filestore_dest}...")
            ok_fs = move_filestore(filestore_src, filestore_dest)
        if ok_fs:
            print_success("Filestore transferred")
        else:
            print_warning("Filestore transfer failed — attachments may be missing")

    # Uninstall conflicting modules BEFORE any sanitize step runs.
    if uninstall_modules:
        from odoodev.commands.start import resolve_odoo_invocation

        inv = resolve_odoo_invocation(version_cfg, env_vars)
        if inv is None:
            print_warning(
                "Module uninstall skipped — venv/odoo-bin/odoo_*.conf not ready "
                f"(run 'odoodev db uninstall {version} -n {name} -m {','.join(uninstall_modules)}' after setup)"
            )
        else:
            print_info(f"Uninstalling module(s): {', '.join(uninstall_modules)}...")
            ok, msg = run_uninstall_modules(name, uninstall_modules, **inv)
            if ok:
                _print_uninstall_markers(msg)
                print_success("Module uninstall complete")
            else:
                print_warning(f"Module uninstall failed (non-fatal): {msg.strip()}")
                if not yes_flag and any((deactivate_cron, neutralize, anonymize, wipe)):
                    # These modules may break the sanitize steps — give the
                    # operator a chance to bail before touching the DB further.
                    if not confirm("Continue with the sanitize pipeline despite the uninstall failure?", default=False):
                        print_info("Aborted.")
                        raise SystemExit(1)

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

    if wipe:
        print_info("Wiping message/attachment content...")
        if wipe_database(name, **params):
            print_success("Message and attachment content wiped")
        else:
            print_warning("Wipe partially failed — some tables may be missing (non-fatal)")

    if purge_transactions:
        print_info("Purging transactional data (keeping products, pricelists, partners)...")
        ok, msg = purge_transactional_data(name, **params)
        if ok:
            print_success(f"Transactional data purged — {msg}")
        else:
            print_warning(f"Purge skipped — {msg}")

    if anon_users:
        print_info("Anonymizing res_users (logins + dev password)...")
        if anonymize_users(name, dev_password=user_password, **params):
            print_success(f"User logins anonymized (login: user<id>, password: {user_password})")
        else:
            print_warning("User anonymization failed (table issue) — non-fatal")

    # Recompute stored computed fields after in-place SQL edits (anonymize), so
    # overviews (kanban/list) show the anonymized data instead of stale display names.
    if recompute and anonymize:
        from odoodev.commands.start import resolve_odoo_invocation

        inv = resolve_odoo_invocation(version_cfg, env_vars)
        if inv is None:
            print_warning(
                "Recompute skipped — venv/odoo-bin/odoo_*.conf not ready; stored computed fields "
                f"(e.g. complete_name) may be stale (run 'odoodev db recompute {version} -n {name}' after setup)"
            )
        else:
            print_info("Recomputing stored computed fields (odoo-bin shell)...")
            ok, msg = run_recompute(name, **inv)
            if ok:
                print_success("Stored computed fields recomputed")
            else:
                print_warning(f"Recompute failed (non-fatal): {msg.strip()}")

    if not any((deactivate_cron, neutralize, anonymize, wipe, purge_transactions, anon_users)):
        print_info(
            "Database left untouched — no post-restore processing selected "
            "(use --sanitize, --purge-transactions, or --deactivate-cron/--neutralize/--anonymize/--wipe)"
        )

    # Cleanup
    if not keep_temp:
        cleanup_restore_temp(extract_path)

    print_success(f"Database '{name}' restore complete")

    # Optionally remove the original backup. Never automatic: a restore can be
    # imperfect and the backup may still be needed. Precedence:
    # --delete-backup (delete, no prompt) > --keep-backup (never) > interactive.
    if delete_backup:
        do_delete = True
    elif keep_backup:
        do_delete = False
    else:
        do_delete = confirm(
            f"Delete original backup file '{os.path.basename(backup_file)}'?",
            default=False,
        )
    if do_delete:
        try:
            os.remove(backup_file)
            print_success("Original backup deleted")
        except OSError as e:
            print_warning(f"Could not delete backup: {e}")

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
    _ensure_pg_reachable(version, params)

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


def _print_uninstall_markers(output: str) -> None:
    """Pretty-print the ``odoodev-uninstall: ...`` marker lines from the shell output."""
    for line in output.strip().splitlines():
        if line.startswith("odoodev-uninstall: "):
            console.print(f"  {line.removeprefix('odoodev-uninstall: ')}")


@db.command("uninstall")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("-m", "--modules", "modules_raw", default=None, help="Comma-separated technical module names")
@click.option("-y", "--yes", is_flag=True, help="Skip the confirmation prompt")
@click.pass_context
def db_uninstall(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    modules_raw: str | None,
    yes: bool,
) -> None:
    """Uninstall modules via 'odoo-bin shell' (button_immediate_uninstall).

    Only modules currently installed are targeted; names that don't exist or
    aren't installed are reported, not treated as errors. Useful when a module
    conflicts with the sanitize steps after a restore. Requires a ready dev
    environment (venv, server checkout, generated odoo_*.conf).
    """
    from odoodev.commands.start import resolve_odoo_invocation

    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _ensure_pg_reachable(version, params)

    if modules_raw is None:
        modules_raw = text_input("Modules to uninstall (comma-separated technical names):", default="")
    modules = parse_module_names(modules_raw)
    if not modules:
        print_error("No module names given")
        raise SystemExit(1)

    if not name:
        name = _select_database(params)
        if not name:
            raise SystemExit(1)

    if not _validate_db_name(name):
        print_error(f"Invalid database name: '{name}'")
        raise SystemExit(1)

    if not yes:
        print_warning(f"This will uninstall {len(modules)} module(s) from '{name}': {', '.join(modules)}")
        if not confirm("Proceed? Module data will be dropped by Odoo.", default=False):
            print_info("Aborted.")
            return

    inv = resolve_odoo_invocation(version_cfg, env_vars)
    if inv is None:
        print_error(
            "Cannot uninstall — venv, odoo-bin or odoo_*.conf not found. Run 'odoodev init' / 'odoodev repos' first."
        )
        raise SystemExit(1)

    print_info(f"Uninstalling module(s) in '{name}': {', '.join(modules)}...")
    ok, output = run_uninstall_modules(name, modules, **inv)
    if not ok:
        print_error(f"Module uninstall failed: {output.strip()}")
        raise SystemExit(1)
    _print_uninstall_markers(output)
    print_success(f"Module uninstall complete in '{name}'")


@db.command("users")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (picker shown inside the TUI if omitted)")
@click.pass_context
def db_users(
    ctx: click.Context,
    version: str | None,
    name: str | None,
) -> None:
    """Interactive TUI for user management: password reset + 2FA disable.

    Browse the users of a restored database, set a new password (stored as an
    Odoo-compatible pbkdf2_sha512 hash) and disable TOTP two-factor
    authentication — handy after restoring a production backup for development.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _ensure_pg_reachable(version, params)

    if name and not _validate_db_name(name):
        print_error(f"Invalid database name: '{name}'")
        raise SystemExit(1)

    from odoodev.tui.users_app import UsersTuiApp

    app = UsersTuiApp(db_name=name or "", host=params["host"], port=params["port"], user=params["user"])
    app.run()


@db.command("purge")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("--dry-run", is_flag=True, help="List the tables that would be emptied, delete nothing")
@click.option("-y", "--yes", is_flag=True, help="Skip the confirmation prompt")
@click.pass_context
def db_purge(
    ctx: click.Context,
    version: str | None,
    name: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Delete all transactional/movement data, keeping products, pricelists, partners.

    Empties stock moves/quants (zeroing on-hand stock), sale/purchase orders,
    accounting moves/payments, MRP and POS data via TRUNCATE ... CASCADE. Products,
    pricelists, partners, users and config are kept — ideal for a clean stress-test
    database. Combine with a restore + '--anonymize' to also anonymize the partners.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _ensure_pg_reachable(version, params)

    if not name:
        name = _select_database(params)
        if not name:
            raise SystemExit(1)

    if not _validate_db_name(name):
        print_error(f"Invalid database name: '{name}'")
        raise SystemExit(1)

    tables = resolve_purge_tables(name, **params)
    if not tables:
        print_warning("No transactional tables found — no movement-data modules installed. Nothing to purge.")
        return

    if dry_run:
        print_info(f"Tables that would be emptied on '{name}' ({len(tables)}):")
        for table in tables:
            console.print(f"  {table}")
        print_info("Dry run — nothing deleted. Cascade also empties their child/linkage tables.")
        return

    if not yes:
        print_warning(f"This will permanently delete ALL transactional data in '{name}':")
        print_warning(f"  {len(tables)} root tables (stock, sale, purchase, account, mrp, pos) + cascade")
        print_warning("  Products, pricelists, partners, users and config are KEPT.")
        console.print()
        if not confirm("Proceed with purge? This cannot be undone.", default=False):
            print_info("Aborted.")
            return

    print_info(f"Purging transactional data in '{name}'...")
    ok, msg = purge_transactional_data(name, **params)
    if ok:
        print_success(f"Transactional data purged — {msg}")
    else:
        print_error(msg)
        raise SystemExit(1)


@db.command("recompute")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.pass_context
def db_recompute(
    ctx: click.Context,
    version: str | None,
    name: str | None,
) -> None:
    """Recompute stored computed fields via 'odoo-bin shell'.

    Fixes stale stored computed fields (complete_name and the display names that
    read it) after raw-SQL edits such as anonymization, so kanban/list overviews
    show the current data. Requires a ready dev environment (venv, server, conf).
    """
    from odoodev.commands.start import resolve_odoo_invocation

    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _ensure_pg_reachable(version, params)

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
            "Cannot recompute — venv, odoo-bin or odoo_*.conf not found. Run 'odoodev init' / 'odoodev repos' first."
        )
        raise SystemExit(1)

    print_info(f"Recomputing stored computed fields in '{name}' (odoo-bin shell)...")
    ok, output = run_recompute(name, **inv)
    if not ok:
        print_error(f"Recompute failed: {output.strip()}")
        raise SystemExit(1)
    print_success(f"Stored computed fields recomputed in '{name}'")


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
        'sql', 'zip' or 'tar.zst', or None if aborted.
    """
    filestore_path = get_filestore_path(version, db_name)
    has_filestore = os.path.isdir(filestore_path)

    choices = [
        questionary.Choice("SQL — pg_dump only", value="sql"),
    ]
    if has_filestore:
        choices.append(questionary.Choice("ZIP — SQL + filestore", value="zip"))
        choices.append(questionary.Choice("TAR.ZST — SQL + filestore (zstd stream)", value="tar.zst"))
    else:
        choices.append(questionary.Choice("ZIP — SQL only (no filestore found)", value="zip"))
        choices.append(questionary.Choice("TAR.ZST — SQL only (no filestore found)", value="tar.zst"))

    try:
        return select("Backup type:", choices=choices)
    except SystemExit:
        return None


@db.command("backup")
@click.argument("version", required=False)
@click.option("-n", "--name", help="Database name (interactive selection if omitted)")
@click.option("-t", "--type", "backup_type", type=click.Choice(["sql", "zip", "tar.zst"]), help="Backup type")
@click.option(
    "-l",
    "--level",
    type=click.IntRange(1, 22),
    default=5,
    show_default=True,
    help="zstd compression level (tar.zst only): 1=fastest .. 19/22=smallest",
)
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
    level: int,
    output_dir: str | None,
) -> None:
    """Create a database backup (SQL dump, ZIP or tar.zst with filestore).

    Without options, interactively selects database and backup type.
    The tar.zst type (TAR + Zstandard) matches the server stream-backup format
    and is well suited to large databases with a big filestore.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)
    _print_migration_hint(version)
    _ensure_pg_reachable(version, params)

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

    # tar.zst needs the zstd CLI — fail early before dumping anything
    if backup_type == "tar.zst" and not shutil.which("zstd"):
        print_error("zstd not found — required to create .tar.zst backups")
        print_info("macOS: brew install zstd")
        print_info("Linux/Debian: apt install zstd")
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
        # ZIP / tar.zst: dump SQL to temp, then bundle with the filestore
        is_tar_zst = backup_type == "tar.zst"
        extension = "tar.zst" if is_tar_zst else "zip"
        label = "tar.zst" if is_tar_zst else "ZIP"
        tmp_dir = tempfile.mkdtemp(prefix="odoodev_backup_")
        try:
            sql_path = os.path.join(tmp_dir, "dump.sql")
            print_info(f"Dumping database '{name}'...")

            if not backup_database_sql(name, sql_path, **params):
                print_error("Database dump failed")
                raise SystemExit(1)

            filestore_path = get_filestore_path(version, name)
            fs_dir = filestore_path if os.path.isdir(filestore_path) else None

            output_file = os.path.join(output_dir, f"{name}_{date_suffix}.{extension}")
            print_info(f"Creating {label} backup...")

            if fs_dir:
                print_info(f"Including filestore: {fs_dir}")

            if is_tar_zst:
                created = create_backup_tar_zst(sql_path, output_file, fs_dir, level=level)
            else:
                created = create_backup_zip(sql_path, output_file, fs_dir)

            if not created:
                print_error(f"{label} creation failed")
                raise SystemExit(1)

            size = format_size(os.path.getsize(output_file))
            print_success(f"Backup created: {output_file} ({size})")

        finally:
            try:
                shutil.rmtree(tmp_dir)
            except OSError as e:
                print_warning(f"Could not remove temp directory: {e}")
