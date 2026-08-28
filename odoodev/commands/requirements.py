"""Requirements base/overlay management commands."""

from __future__ import annotations

import click

from odoodev.core.requirements_sync import SyncOutcome, sync_version
from odoodev.core.version_registry import available_versions, get_version
from odoodev.output import print_error, print_info, print_success, print_warning


@click.group()
def requirements() -> None:
    """Manage base requirements and the machine-local overlay."""


def _print_sync_outcome(outcome: SyncOutcome) -> None:
    """Report one version's sync result, including merge warnings."""
    if outcome.blocked_reason:
        print_error(f"v{outcome.version}: {outcome.blocked_reason}")
        return

    if outcome.result is not None:
        for _base_req, local_req in outcome.result.replaced:
            print_info(f"v{outcome.version}: overlay pins {local_req.name}{local_req.specifier}")
        for warning in outcome.result.warnings:
            print_warning(f"v{outcome.version}: {warning}")

    if outcome.written:
        print_success(f"v{outcome.version}: {outcome.path} regenerated")
    else:
        print_info(f"v{outcome.version}: already current")


@requirements.command("sync")
@click.argument("version", required=False)
@click.option("--all", "all_versions", is_flag=True, help="Sync every configured version")
@click.option("--check", is_flag=True, help="Write nothing; exit 1 if the file is stale")
@click.pass_context
def requirements_sync(ctx: click.Context, version: str | None, all_versions: bool, check: bool) -> None:
    """Regenerate requirements.txt from the baseline plus the local overlay."""
    from odoodev.cli import resolve_version

    targets = available_versions() if all_versions else [resolve_version(ctx, version)]

    failed = False
    for target in targets:
        try:
            outcome = sync_version(target, get_version(target), check_only=check)
        except FileNotFoundError as exc:
            print_error(f"v{target}: bundled baseline not found: {exc}")
            failed = True
            continue
        _print_sync_outcome(outcome)
        if outcome.blocked_reason or (check and outcome.stale):
            failed = True

    if failed:
        raise SystemExit(1)


@requirements.command("diff")
@click.argument("version", required=False)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.pass_context
def requirements_diff(ctx: click.Context, version: str | None, as_json: bool) -> None:
    """Show baseline vs. overlay vs. installed packages. Writes nothing."""
    import json
    import sys

    from rich.console import Console
    from rich.table import Table

    from odoodev.cli import resolve_version
    from odoodev.core.requirements_sync import three_way_report

    target = resolve_version(ctx, version)
    rows = three_way_report(target, get_version(target))

    if as_json:
        payload = {
            "version": target,
            "rows": [
                {
                    "name": row.name,
                    "base": row.base,
                    "local": row.local,
                    "installed": row.installed,
                    "status": row.status,
                }
                for row in rows
            ],
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        return

    table = Table(title=f"Requirements v{target}")
    for column in ("Package", "Base", "Local", "Installed", "Status"):
        table.add_column(column)
    for row in rows:
        if row.status == "ok":
            continue
        table.add_row(row.name, row.base, row.local, row.installed, row.status)
    Console().print(table)
