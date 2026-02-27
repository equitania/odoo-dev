"""odoodev run - YAML-driven playbook automation for AI agents."""

from __future__ import annotations

import json
import sys

import click

from odoodev.cli import resolve_version
from odoodev.core.playbook import (
    PlaybookResult,
    PlaybookRunner,
    PlaybookValidationError,
    StepResult,
    build_playbook_from_steps,
    load_playbook,
)
from odoodev.output import console, print_error, print_info, print_success


def _emit_json(event: str, **data: object) -> None:
    """Emit a single NDJSON line to stdout."""
    payload = {"event": event, **data}
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def _print_step_result_text(result: StepResult) -> None:
    """Print a step result in human-readable Rich format."""
    duration = f"({result.duration_ms}ms)" if result.duration_ms > 0 else ""

    if result.status == "ok":
        console.print(f"  [green][OK][/green] {result.name} {duration}")
        if result.message and "[dry-run]" in result.message:
            console.print(f"       {result.message}")
    elif result.status == "error":
        console.print(f"  [red][ERROR][/red] {result.name}: {result.message} {duration}")
    elif result.status == "skipped":
        console.print(f"  [dim][SKIP][/dim] {result.name}: {result.message}")


def _print_step_result_json(result: StepResult) -> None:
    """Emit step result as NDJSON."""
    _emit_json(
        "step_done",
        name=result.name,
        command=result.command,
        status=result.status,
        message=result.message,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        details=result.details,
    )


def _print_playbook_result_text(result: PlaybookResult) -> None:
    """Print final playbook summary in Rich format."""
    ok_count = sum(1 for s in result.steps if s.status == "ok")
    error_count = sum(1 for s in result.steps if s.status == "error")
    skip_count = sum(1 for s in result.steps if s.status == "skipped")

    console.print()
    if result.status == "ok":
        print_success(
            f"Playbook '{result.playbook}' completed — "
            f"{ok_count} ok, {error_count} errors, {skip_count} skipped "
            f"({result.total_duration_ms}ms)"
        )
    else:
        print_error(
            f"Playbook '{result.playbook}' failed — "
            f"{ok_count} ok, {error_count} errors, {skip_count} skipped "
            f"({result.total_duration_ms}ms)"
        )


def _print_playbook_result_json(result: PlaybookResult) -> None:
    """Emit playbook summary as NDJSON."""
    ok_count = sum(1 for s in result.steps if s.status == "ok")
    error_count = sum(1 for s in result.steps if s.status == "error")

    _emit_json(
        "playbook_done",
        playbook=result.playbook,
        version=result.version,
        status=result.status,
        steps_ok=ok_count,
        steps_error=error_count,
        total_duration_ms=result.total_duration_ms,
    )


@click.command("run")
@click.argument("playbook", required=False, type=click.Path())
@click.option("--step", "-s", multiple=True, help="Inline step command (e.g. docker.up, pull)")
@click.option("--version", "-V", "version_override", help="Override playbook/auto-detected version")
@click.option(
    "--output", "-o", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format"
)
@click.option("--dry-run", is_flag=True, help="Show steps without executing")
@click.pass_context
def run(
    ctx: click.Context,
    playbook: str | None,
    step: tuple[str, ...],
    version_override: str | None,
    output_format: str,
    dry_run: bool,
) -> None:
    """Execute a playbook or inline steps for automated Odoo development.

    Two modes of operation:

    \b
    1. YAML playbook:  odoodev run playbook.yaml
    2. Inline steps:   odoodev run --step docker.up --step pull -V 18

    Use --output json for machine-readable NDJSON output (one JSON line per event).
    Use --dry-run to preview steps without executing them.
    """
    if not playbook and not step:
        print_error("Either a playbook file or --step options are required")
        print_info("Usage: odoodev run <playbook.yaml>  or  odoodev run --step docker.up --step pull -V 18")
        raise SystemExit(1)

    if playbook and step:
        print_error("Cannot use both a playbook file and --step options")
        raise SystemExit(1)

    is_json = output_format == "json"

    try:
        if playbook:
            # YAML playbook mode
            pb_config = load_playbook(playbook)
            playbook_name = playbook
        else:
            # Inline steps mode — need a version
            version = version_override
            if not version:
                version = resolve_version(ctx, None)
            pb_config = build_playbook_from_steps(list(step), version)
            playbook_name = "<inline>"

        # Resolve final version
        version_final = version_override or pb_config.version

        if not is_json:
            label = f"v{version_final}"
            if dry_run:
                label += " [DRY RUN]"
            print_info(f"Running playbook '{playbook_name}' for {label}")
            console.print()

        # Execute
        runner = PlaybookRunner()

        # Wrap execution with per-step output
        if is_json:
            _emit_json("playbook_start", playbook=playbook_name, version=version_final, dry_run=dry_run)

        result = runner.execute(
            pb_config,
            version_override=version_override,
            dry_run=dry_run,
            playbook_name=playbook_name,
        )

        # Output results
        for step_result in result.steps:
            if is_json:
                _print_step_result_json(step_result)
            else:
                _print_step_result_text(step_result)

        if is_json:
            _print_playbook_result_json(result)
        else:
            _print_playbook_result_text(result)

        if result.status == "error":
            raise SystemExit(1)

    except PlaybookValidationError as exc:
        if is_json:
            _emit_json("error", message=str(exc))
        else:
            print_error(f"Playbook validation error: {exc}")
        raise SystemExit(1) from None

    except FileNotFoundError as exc:
        if is_json:
            _emit_json("error", message=str(exc))
        else:
            print_error(str(exc))
        raise SystemExit(1) from None
