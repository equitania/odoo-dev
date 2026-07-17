"""odoodev export - Export data from a running Odoo instance via XML-RPC.

The ``export modules`` subcommand produces the Releasemanager-compatible
module CSV. It shares its core (``core/xmlrpc_client.py`` +
``core/module_export.py``) with the TUI's ``x`` export dialog, so the GUI
can shell out to this command instead of reimplementing the RPC logic.
"""

from __future__ import annotations

import os
import sys

import click

from odoodev.click_types import ExpandedPath
from odoodev.output import print_error, print_info, print_success, print_warning

# CLI scope value → EXPORT_SCOPES key (core/module_export.py)
_SCOPE_MAP = {
    "all": "all",
    "no-enterprise": "all_no_enterprise",
    "installed": "installed",
}

ENV_USER = "ODOODEV_ODOO_USER"
ENV_PASSWORD = "ODOODEV_ODOO_PASSWORD"  # noqa: S105 — env var name, not a secret


def _resolve_login(user: str | None, password: str | None) -> tuple[str, str]:
    """Resolve the Odoo login: CLI flags > env vars > global config > admin/admin."""
    from odoodev.core.global_config import get_odoo_login_credentials

    user = user or os.environ.get(ENV_USER)
    password = password or os.environ.get(ENV_PASSWORD)
    if user and password:
        return user, password
    stored_user, stored_password = get_odoo_login_credentials()
    return user or stored_user, password or stored_password


def _resolve_database(database: str | None, db_port: int, non_interactive: bool) -> str:
    """Resolve the target database, interactively when possible.

    Raises:
        click.UsageError: When no database is given and prompting is not possible.
    """
    if database:
        return database
    if non_interactive or not sys.stdin.isatty():
        raise click.UsageError("--database is required in non-interactive mode (--yes/--json)")

    from odoodev.core.database import list_databases
    from odoodev.output import select

    try:
        databases = list_databases(port=db_port)
    except Exception:
        databases = []
    if not databases:
        raise click.UsageError(f"No databases found on port {db_port} — pass --database explicitly")
    return select("Target database:", choices=databases)


@click.group()
def export() -> None:
    """Export data from a running Odoo instance."""


@export.command("modules")
@click.argument("version", required=False)
@click.option("-d", "--database", default=None, help="Target Odoo database (interactive picker when omitted)")
@click.option("--user", default=None, help=f"Odoo login (fallback: ${ENV_USER}, stored config, admin)")
@click.option("--password", default=None, help=f"Odoo password (fallback: ${ENV_PASSWORD}, stored config, admin)")
@click.option(
    "--scope",
    type=click.Choice(sorted(_SCOPE_MAP)),
    default="all",
    show_default=True,
    help="Module scope: all, all without Enterprise, or installed only",
)
@click.option("--update-list", is_flag=True, help="Run 'Update Apps List' before exporting")
@click.option("--cleanup", is_flag=True, help="Remove non-installed module records before exporting")
@click.option(
    "--output",
    "output_path",
    type=ExpandedPath(),
    default=None,
    help="CSV output path (default: ~/Downloads/modules_<db>_<scope>_<timestamp>.csv)",
)
@click.option("--host", default="localhost", show_default=True, help="Odoo XML-RPC host")
@click.option("--port", type=int, default=None, help="Odoo HTTP port (default: the version's effective ODOO_PORT)")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON result on stdout (implies --yes)")
@click.option("--yes", "-y", is_flag=True, help="Non-interactive — never prompt")
@click.pass_context
def export_modules(
    ctx: click.Context,
    version: str | None,
    database: str | None,
    user: str | None,
    password: str | None,
    scope: str,
    update_list: bool,
    cleanup: bool,
    output_path: str | None,
    host: str,
    port: int | None,
    as_json: bool,
    yes: bool,
) -> None:
    """Export the module list as Releasemanager-compatible CSV.

    Talks XML-RPC to a RUNNING Odoo instance (start it first). Shares its
    logic with the TUI export ('x' key), so results are identical.
    """
    import datetime
    import json

    from odoodev.cli import resolve_version
    from odoodev.core.module_export import EXPORT_SCOPES, build_export_path, write_modules_csv
    from odoodev.core.odoo_config import effective_ports
    from odoodev.core.version_registry import get_version
    from odoodev.core.xmlrpc_client import OdooXmlRpcClient

    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    ports = effective_ports(version_cfg)

    odoo_port = port or ports["odoo"]
    non_interactive = yes or as_json
    database = _resolve_database(database, ports["db"], non_interactive)
    user, password = _resolve_login(user, password)

    scope_key = _SCOPE_MAP[scope]
    installed_only, exclude_enterprise = EXPORT_SCOPES[scope_key]

    updated: int | None = None
    cleaned: int | None = None
    try:
        client = OdooXmlRpcClient(host=host, port=odoo_port, database=database, username=user, password=password)
        if not as_json:
            print_info(f"Connecting to Odoo at {host}:{odoo_port} (db: {database})...")
        # Cleanup first, then update — so the catalog reflects the current system.
        if cleanup:
            if not as_json:
                print_info("Removing non-installed module records...")
            cleaned = client.cleanup_uninstalled_modules()
            if not as_json:
                print_success(f"{cleaned} module records removed")
        if update_list:
            if not as_json:
                print_info("Updating apps list...")
            updated = client.update_module_list()
            if not as_json:
                print_success(f"{updated} modules added to the catalog")
        if not as_json:
            print_info("Fetching module list...")
        records = client.list_modules(installed_only=installed_only, exclude_enterprise=exclude_enterprise)
    except (ConnectionError, ValueError, OSError) as e:
        print_error(f"Module export failed: {e}")
        print_info(f"Is Odoo v{version} running? Start it with: odoodev start {version}")
        raise SystemExit(1) from e

    result: dict = {
        "version": version,
        "database": database,
        "scope": scope,
        "path": None,
        "count": len(records),
        "updated": updated,
        "cleaned": cleaned,
    }

    if not records:
        # A valid outcome, not a failure — the GUI shows "0 modules".
        if as_json:
            sys.stdout.write(json.dumps(result) + "\n")
        else:
            print_warning("No modules to export.")
        return

    from pathlib import Path

    path = Path(output_path) if output_path else build_export_path(database, scope_key, datetime.datetime.now())
    try:
        write_modules_csv(records, path)
    except OSError as e:
        print_error(f"Cannot write CSV: {e}")
        raise SystemExit(1) from e

    result["path"] = str(path)
    if as_json:
        sys.stdout.write(json.dumps(result) + "\n")
    else:
        print_success(f"{len(records)} modules exported: {path}")
