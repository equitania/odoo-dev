"""Requirements base/overlay management commands."""

from __future__ import annotations

import click

from odoodev.core.requirements_sync import SyncOutcome, sync_version
from odoodev.core.version_registry import available_versions, get_version
from odoodev.output import print_error, print_info, print_success, print_warning, select


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


@requirements.command("adopt")
@click.argument("version", required=False)
@click.option("--yes", "-y", is_flag=True, help="Take the baseline for every conflict without prompting")
@click.option(
    "--keep-local",
    is_flag=True,
    help="Keep every local pin instead, overriding the baseline (no prompting)",
)
@click.pass_context
def requirements_adopt(ctx: click.Context, version: str | None, yes: bool, keep_local: bool) -> None:
    """Migrate a hand-maintained requirements.txt into baseline + overlay.

    Packages the baseline does not know always move to the overlay. For a package
    both files carry, the baseline wins by default: a hand-maintained file
    predates the baseline, so its version is the older state rather than a local
    decision, and keeping it would revert the baseline's security bumps wholesale.
    Use --keep-local when the local pin really is deliberate.
    """
    import os

    from odoodev.cli import resolve_version
    from odoodev.core.requirements_merge import Requirement, is_generated
    from odoodev.core.requirements_sync import (
        adopt_candidates,
        adopt_passthrough_lines,
        backup_existing,
        backup_overlay,
        generated_path,
        overlay_has_content,
        overlay_path,
        sync_version,
        write_overlay,
    )

    target = resolve_version(ctx, version)
    cfg = get_version(target)
    current = generated_path(cfg)

    if not os.path.exists(current):
        print_error(f"No requirements.txt at {current} — nothing to adopt. Run 'odoodev requirements sync'.")
        raise SystemExit(1)

    # The durable "already adopted" signal: unlike requirements.txt's generated
    # header, requirements.local.txt cannot silently revert (a git pull in the
    # shared vXX-dev repo, or a colleague on an older odoodev, only ever
    # touches the generated file). Checked first and unconditionally, so it
    # can never be bypassed by requirements.txt losing its header.
    if overlay_has_content(cfg):
        print_error(
            f"v{target}: {overlay_path(cfg)} already has entries — this environment has already adopted. "
            f"Edit it directly, or run 'odoodev requirements sync' to regenerate requirements.txt from it."
        )
        raise SystemExit(1)

    with open(current, encoding="utf-8") as handle:
        if is_generated(handle.read()):
            print_error(
                f"v{target}: requirements.txt is already generated and the overlay is empty — nothing to "
                f"adopt. Run 'odoodev requirements sync' if you need to refresh it."
            )
            raise SystemExit(1)

    keep: list[Requirement] = []
    for candidate in adopt_candidates(target, cfg):
        if candidate.base is None:
            print_info(f"local only, moved to overlay: {candidate.existing.to_line()}")
            keep.append(candidate.existing)
            continue
        if keep_local:
            print_warning(
                f"kept local, overrides baseline {candidate.base.name}{candidate.base.specifier}: "
                f"{candidate.existing.to_line()}"
            )
            keep.append(candidate.existing)
            continue
        if yes:
            print_info(
                f"baseline wins: {candidate.base.name}{candidate.base.specifier} "
                f"(local {candidate.existing.specifier} dropped)"
            )
            continue
        choice = select(
            f"{candidate.existing.name}: baseline {candidate.base.specifier} vs. local {candidate.existing.specifier}",
            ["keep local", "take baseline"],
        )
        if choice == "keep local":
            keep.append(candidate.existing)

    passthrough = adopt_passthrough_lines(cfg)
    for raw in passthrough:
        print_info(f"passthrough line, moved to overlay: {raw}")

    backup = backup_existing(cfg)
    if backup:
        print_info(f"Previous file kept at {backup}")

    overlay_backup = backup_overlay(cfg)
    if overlay_backup:
        print_info(f"Previous overlay kept at {overlay_backup}")

    overlay = write_overlay(cfg, keep, passthrough)
    print_success(f"Overlay written: {overlay} ({len(keep) + len(passthrough)} entries)")

    outcome = sync_version(target, cfg)
    _print_sync_outcome(outcome)


@requirements.command("prune")
@click.argument("version", required=False)
@click.option("--dry-run", is_flag=True, help="Show what would be removed; write nothing")
@click.option("--yes", "-y", is_flag=True, help="Remove without asking")
@click.pass_context
def requirements_prune(ctx: click.Context, version: str | None, dry_run: bool, yes: bool) -> None:
    """Drop overlay entries the baseline already covers.

    Removed are pins identical to the baseline, pins holding a baseline bump back,
    and entries that drop the baseline's extras — the residue every environment
    migrated before 0.65.0 carries. A deliberately newer pin and any package the
    baseline does not know are kept, and so are passthrough lines.
    """
    from odoodev.cli import resolve_version
    from odoodev.core.requirements_sync import (
        PRE_PRUNE_SUFFIX,
        backup_overlay,
        prune_candidates,
        sync_version,
        write_overlay,
    )
    from odoodev.output import confirm

    target = resolve_version(ctx, version)
    cfg = get_version(target)
    report = prune_candidates(target, cfg)

    if not report.removable:
        print_success(f"v{target}: nothing to prune — every overlay entry says something the baseline does not")
        return

    for candidate in report.removable:
        print_info(f"{candidate.reason}: {candidate.entry.to_line()}  (baseline: {candidate.base.to_line()})")

    if dry_run:
        print_info(f"v{target}: dry run — {len(report.removable)} entries would be removed, nothing written")
        return

    if not yes and not confirm(f"Remove these {len(report.removable)} entries from the overlay?", default=False):
        print_warning(f"v{target}: aborted — overlay unchanged")
        return

    backup = backup_overlay(cfg, suffix=PRE_PRUNE_SUFFIX)
    if backup:
        print_info(f"Previous overlay kept at {backup}")

    write_overlay(cfg, list(report.kept), list(report.passthrough))
    print_success(f"v{target}: {len(report.removable)} entries removed, {len(report.kept)} kept")
    _print_sync_outcome(sync_version(target, cfg))
