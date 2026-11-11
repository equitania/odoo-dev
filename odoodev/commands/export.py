"""odoodev export - Export data from an Odoo database.

The ``export modules`` subcommand produces the Releasemanager-compatible
module CSV. By default it reads the modules through ``odoo-bin shell`` as
superuser (no Odoo login, server need not run) — the same path as the TUI's
``x`` export dialog. The XML-RPC path (``core/xmlrpc_client.py``) remains for
an Odoo that is not this machine's checkout: it is used when a login or host
is given explicitly, or when no local ``odoo-bin`` environment exists.
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
    """Export data from an Odoo database.

    Reads through 'odoo-bin shell' as superuser by default — no Odoo login,
    and the server need not be running. Pass --via-rpc (or --user, --password,
    --host, --port) to talk XML-RPC to a running instance instead; its
    credentials come from --user/--password, the environment
    (ODOODEV_ODOO_USER / ODOODEV_ODOO_PASSWORD), or the stored config
    ('odoodev config set odoo_login.username / odoo_login.password').

    \b
    Examples:
        odoodev export modules 18                      # interactive DB picker
        odoodev export modules 18 -d v18_exam --scope installed
        odoodev export modules 18 -d v18_exam --json   # machine-readable (GUI)
        odoodev export modules 18 -d v18_exam --host erp.example.com --port 443  # remote, XML-RPC

    Full documentation: usage/export.md or 'odoodev capability-card'.
    """


@export.command("modules")
@click.argument("version", required=False)
@click.option("-d", "--database", default=None, help="Target Odoo database (interactive picker when omitted)")
@click.option("--user", default=None, help=f"Odoo login for XML-RPC (fallback: ${ENV_USER}, stored config, admin)")
@click.option(
    "--password", default=None, help=f"Odoo password for XML-RPC (fallback: ${ENV_PASSWORD}, stored config, admin)"
)
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
@click.option(
    "--via-shell",
    is_flag=True,
    help="Force 'odoo-bin shell' (the default path; fails instead of falling back to XML-RPC)",
)
@click.option(
    "--via-rpc",
    is_flag=True,
    help="Use XML-RPC against a RUNNING Odoo with an Odoo login (implied by --user, --password, --host, --port)",
)
@click.option("--host", default=None, help="Odoo XML-RPC host (default: localhost) — selects the XML-RPC path")
@click.option(
    "--port",
    type=int,
    default=None,
    help="Odoo HTTP port (default: the version's effective ODOO_PORT) — selects the XML-RPC path",
)
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
    via_shell: bool,
    via_rpc: bool,
    host: str | None,
    port: int | None,
    as_json: bool,
    yes: bool,
) -> None:
    """Export the module list as Releasemanager-compatible CSV.

    Reads the modules through 'odoo-bin shell' as superuser: no Odoo login is
    needed and the server need not be running. Same path as the TUI export
    ('x' key), so results are identical.
    Default output: ~/Downloads/modules_<db>_<scope>_<timestamp>.csv
    (header: .id,name,installed_version,display_name).

    \b
    Examples:
        odoodev export modules 18 -d v18_exam
        odoodev export modules 18 -d v18_exam --scope no-enterprise
        odoodev export modules 18 -d v18_exam --cleanup --update-list
        odoodev export modules 18 -d v18_exam --output /tmp/modules.csv
        odoodev export modules 18 -d v18_exam --json    # for GUIs/agents
        odoodev export modules 18 -d v18_exam --via-rpc --user admin  # XML-RPC

    \b
    XML-RPC instead of the shell (needs a RUNNING Odoo and an Odoo login):
    selected by --via-rpc or by any of --user, --password, --host, --port, and
    used automatically when this machine has no odoo-bin environment for the
    version. --via-shell forces the shell and never falls back.

    \b
    Credential precedence (XML-RPC only):
        1. --user / --password
        2. $ODOODEV_ODOO_USER / $ODOODEV_ODOO_PASSWORD
        3. odoodev config set odoo_login.username / odoo_login.password
        4. admin/admin (dev default)

    With --json a single-line result object is printed:
    {"version", "database", "scope", "path", "count", "updated", "cleaned"} —
    an empty module list is a soft outcome (count 0, path null, exit 0).
    """
    import datetime
    import json

    from odoodev.cli import resolve_version
    from odoodev.core.module_export import EXPORT_SCOPES, build_export_path, write_modules_csv
    from odoodev.core.odoo_config import effective_ports
    from odoodev.core.version_registry import get_version

    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    ports = effective_ports(version_cfg)

    odoo_port = port or ports["odoo"]
    non_interactive = yes or as_json
    database = _resolve_database(database, ports["db"], non_interactive)
    scope_key = _SCOPE_MAP[scope]
    installed_only, exclude_enterprise = EXPORT_SCOPES[scope_key]

    rpc_requested = via_rpc or any(value is not None for value in (user, password, host, port))
    if via_shell and via_rpc:
        raise click.UsageError("--via-shell and --via-rpc exclude each other")

    inv = None
    if via_shell or not rpc_requested:
        from odoodev.commands.db import _load_env_vars
        from odoodev.commands.start import resolve_odoo_invocation

        inv = resolve_odoo_invocation(version_cfg, _load_env_vars(version_cfg))
        if inv is None and via_shell:
            print_error(f"odoo-bin shell not available for v{version} (venv, odoo-bin or generated config missing)")
            print_info(f"Set up the environment first: odoodev init {version}")
            raise SystemExit(1)
        if inv is None and not as_json:
            print_info(f"No odoo-bin environment for v{version} on this machine — using XML-RPC with the Odoo login")

    if inv is not None:
        records, cleaned, updated = _list_modules_via_shell(
            inv, database, installed_only, exclude_enterprise, cleanup, update_list, as_json
        )
    else:
        records, cleaned, updated = _list_modules_via_xmlrpc(
            version,
            host or "localhost",
            odoo_port,
            database,
            user,
            password,
            installed_only,
            exclude_enterprise,
            cleanup,
            update_list,
            as_json,
        )

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


def _list_modules_via_xmlrpc(
    version: str,
    host: str,
    odoo_port: int,
    database: str,
    user: str | None,
    password: str | None,
    installed_only: bool,
    exclude_enterprise: bool,
    cleanup: bool,
    update_list: bool,
    as_json: bool,
) -> tuple[list[dict[str, object]], int | None, int | None]:
    """Fetch the module list from a running instance; returns (records, cleaned, updated)."""
    from odoodev.core.xmlrpc_client import OdooXmlRpcClient

    user, password = _resolve_login(user, password)
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
        print_info("No usable Odoo login? Without --via-rpc/--user/--host the export needs none (odoo-bin shell)")
        raise SystemExit(1) from e

    return records, cleaned, updated


def _list_modules_via_shell(
    inv: dict,
    database: str,
    installed_only: bool,
    exclude_enterprise: bool,
    cleanup: bool,
    update_list: bool,
    as_json: bool,
) -> tuple[list[dict[str, object]], int | None, int | None]:
    """Fetch the module list via ``odoo-bin shell`` (superuser, no login); returns (records, cleaned, updated)."""
    from odoodev.core.database import run_module_export_shell

    if not as_json:
        print_info(f"Reading modules via odoo-bin shell (db: {database})...")
    try:
        result = run_module_export_shell(
            database,
            installed_only=installed_only,
            exclude_enterprise=exclude_enterprise,
            do_cleanup=cleanup,
            do_update=update_list,
            **inv,
        )
    except RuntimeError as e:
        print_error(f"Module export failed: {e}")
        raise SystemExit(1) from e
    cleaned = result["cleaned"]
    updated = result["updated"]
    if not as_json:
        if cleaned is not None:
            print_success(f"{cleaned} module records removed")
        if updated is not None:
            print_success(f"{updated} modules added to the catalog")
    records = result["records"]
    return (
        records if isinstance(records, list) else [],
        cleaned if isinstance(cleaned, int) else None,
        updated if isinstance(updated, int) else None,
    )
