"""odoodev db update — ``odoo-bin -u`` across many databases.

After a repository sync every development database needs ``-u all`` before it
runs cleanly again. This command does that for a selection of databases in one
go, sequentially, with one progress bar and — per database — only the
warnings and errors Odoo logged. The full Odoo output goes to
``~/odoodev-logs/``. A clean ``-u all`` records the repository heads it ran
against, so ``--stale`` (and ``pull --update``) can later skip databases that
are already current.

The orchestration (``update_databases``) is shared with ``pull --update``; the
non-interactive core (``plan_stale``, ``execute_updates``) also serves the
``db.update`` playbook step.
"""

from __future__ import annotations

import contextlib
import functools
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from odoodev.cli import resolve_version
from odoodev.commands import db as db_cmd
from odoodev.core.module_update import (
    DEFAULT_TIMEOUT,
    IssueCallback,
    UpdateResult,
    collect_repo_heads,
    format_duration,
    load_update_state,
    record_update,
    run_module_update,
    save_update_state,
    stale_reason,
    update_state_path,
)
from odoodev.core.version_registry import get_version
from odoodev.output import confirm, console, print_error, print_info, print_success, print_warning

LOG_DIR = Path.home() / "odoodev-logs"

_LEVEL_STYLE = {
    "WARNING": ("[yellow]WARN [/yellow]", "yellow"),
    "ERROR": ("[red]ERROR[/red]", "red"),
    "CRITICAL": ("[bold red]CRIT [/bold red]", "bold red"),
}


# ---------------------------------------------------------------------------
# Non-interactive core (CLI, pull --update and the playbook step share it)
# ---------------------------------------------------------------------------


def resolve_invocation(version_cfg: Any, env_vars: dict[str, str]) -> dict[str, Any] | None:
    """venv/odoo-bin/conf for a one-shot run, or ``None`` when the env is not ready."""
    from odoodev.commands.start import resolve_odoo_invocation

    return resolve_odoo_invocation(version_cfg, env_vars)


def repo_heads(version_cfg: Any) -> dict[str, str]:
    """Current HEAD per repository from ``repos.yaml``; empty without one."""
    from odoodev.commands.repos import _find_repos_config, _load_repos_config

    config_path = _find_repos_config(version_cfg)
    if not config_path:
        return {}
    config = _load_repos_config(config_path)
    base_path = os.path.expanduser(config.get("paths", {}).get("base", version_cfg.paths.base_expanded))
    return collect_repo_heads(config, base_path, version_cfg)


def plan_stale(version_cfg: Any, databases: list[str]) -> tuple[dict[str, str | None], dict[str, Any], str, dict]:
    """Stale reason per database plus the loaded state, its path and the repo heads."""
    heads = repo_heads(version_cfg)
    state_path = update_state_path(version_cfg)
    state = load_update_state(state_path)
    reasons = {db: stale_reason(state, db, heads) for db in databases}
    return reasons, state, state_path, heads


def log_path_for(version: str, db_name: str, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return str(LOG_DIR / f"update_v{version}_{db_name}_{stamp}.log")


def execute_updates(
    version: str,
    invocation: dict[str, Any],
    targets: list[str],
    modules: str,
    heads: dict[str, str],
    state: dict[str, Any],
    state_path: str,
    timeout: int = DEFAULT_TIMEOUT,
    stop_on_error: bool = False,
    on_issue: Callable[[str, str, str], None] | None = None,
    on_result: Callable[[UpdateResult], None] | None = None,
    on_start: Callable[[str, int, int, str], None] | None = None,
) -> list[UpdateResult]:
    """Run ``-u <modules>`` on every target in order; record clean ``all`` runs.

    ``on_start(db, index, total, log_path)`` fires before each database (index
    1-based), ``on_issue(db, level, text)`` receives the forwarded
    warnings/errors, ``on_result`` every finished database. The state file is
    saved after each clean run so an aborted batch keeps what it achieved.
    """
    results: list[UpdateResult] = []
    total = len(targets)
    for index, db_name in enumerate(targets, start=1):
        log_path = log_path_for(version, db_name)
        if on_start is not None:
            on_start(db_name, index, total, log_path)
        per_db_issue: IssueCallback | None = None
        if on_issue is not None:
            per_db_issue = functools.partial(on_issue, db_name)
        result = run_module_update(
            db_name,
            modules,
            invocation,
            log_path,
            version=version,
            on_issue=per_db_issue,
            timeout=timeout,
        )
        results.append(result)
        if result.clean and modules == "all":
            record_update(state, db_name, heads, modules="all")
            save_update_state(state_path, state)
        if on_result:
            on_result(result)
        if stop_on_error and not result.ok:
            break
    return results


# ---------------------------------------------------------------------------
# Console rendering
# ---------------------------------------------------------------------------


def _print_issue(out: Any, level: str, text: str) -> None:
    if level == "RAW":
        out.print(f"        [dim]{escape(text)}[/dim]")
        return
    tag, style = _LEVEL_STYLE.get(level, ("[red]ERROR[/red]", "red"))
    out.print(f"  {tag} [{style}]{escape(text)}[/{style}]")


def _print_result_line(out: Any, result: UpdateResult) -> None:
    took = format_duration(result.duration_s)
    if result.ok and result.errors == 0:
        extra = f", {result.warnings} warning(s)" if result.warnings else ""
        out.print(f"  [green]✓[/green] [bold]{escape(result.db_name)}[/bold] — {took}{extra}")
    elif result.ok:
        out.print(
            f"  [yellow]![/yellow] [bold]{escape(result.db_name)}[/bold] — {took}, exit 0 but "
            f"{result.errors} error(s) logged: {escape(result.last_error or '')}"
        )
    else:
        out.print(
            f"  [red]✗[/red] [bold]{escape(result.db_name)}[/bold] — FAILED after {took}: "
            f"{escape(result.last_error or f'exit code {result.exit_code}')}"
        )


def print_summary(results: list[UpdateResult], modules: str) -> None:
    table = Table(title=f"Update summary — -u {modules}", border_style="blue")
    table.add_column("Database", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Duration", justify="right")
    table.add_column("Warnings", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Log")
    for r in results:
        if r.ok and r.errors == 0:
            status = "[green]OK[/green]"
        elif r.ok:
            status = "[yellow]OK (errors logged)[/yellow]"
        elif r.timed_out:
            status = "[red]TIMEOUT[/red]"
        else:
            status = "[red]FAILED[/red]"
        table.add_row(
            escape(r.db_name),
            status,
            format_duration(r.duration_s),
            str(r.warnings),
            str(r.errors),
            escape(r.log_path),
        )
    console.print()
    console.print(table)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def update_databases(
    version: str,
    names: tuple[str, ...] = (),
    multi: bool = False,
    select_all: bool = False,
    name_filter: str | None = None,
    stale: bool = False,
    modules: str = "all",
    stop_on_error: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    dry_run: bool = False,
    as_json: bool = False,
    yes: bool = False,
) -> int:
    """Interactive orchestration behind ``db update`` and ``pull --update``.

    Returns the process exit code (0 = every database updated cleanly or
    nothing to do, 1 = at least one failure or a preflight problem, 130 =
    interrupted). With ``as_json`` stdout carries exactly one JSON line; every
    human-readable message goes to stderr.
    """
    if not as_json:
        return _update_databases(
            version, names, multi, select_all, name_filter, stale, modules, stop_on_error, timeout, dry_run, False,
            yes, json_out=sys.stdout,
        )  # fmt: skip
    json_out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        return _update_databases(
            version, names, multi, select_all, name_filter, stale, modules, stop_on_error, timeout, dry_run, True,
            True, json_out=json_out,
        )  # fmt: skip


def _update_databases(
    version: str,
    names: tuple[str, ...],
    multi: bool,
    select_all: bool,
    name_filter: str | None,
    stale: bool,
    modules: str,
    stop_on_error: bool,
    timeout: int,
    dry_run: bool,
    as_json: bool,
    yes: bool,
    json_out: Any,
) -> int:
    if sum([bool(names), multi, select_all]) > 1:
        print_error("Choose only one selection mode: -n/--name, -m/--multi, or --all")
        return 1
    if name_filter and names:
        print_error("--filter cannot be combined with explicit -n/--name")
        return 1
    if not modules.strip():
        print_error("-u/--modules must not be empty")
        return 1
    if as_json and (multi or not (names or select_all or stale)):
        # A prompt would block a GUI/agent (and write to stdout) — refuse up front.
        print_error("--json needs an explicit selection: -n/--name, --all or --stale (no -m, no interactive select)")
        return 1

    # Looked up through the module so tests (and conftest's PG-precheck stub)
    # can patch them in one place.
    version_cfg = get_version(version)
    env_vars = db_cmd._load_env_vars(version_cfg)
    params = db_cmd._get_db_params(version_cfg, env_vars)
    db_cmd._ensure_pg_reachable(version, params)

    invocation = resolve_invocation(version_cfg, env_vars)
    if invocation is None:
        print_error("Development environment not ready — need .venv, odoo-bin and a generated odoo_*.conf")
        print_info(f"Run: odoodev venv setup {version}  /  odoodev repos {version}")
        return 1

    # --stale without another mode means: consider every database — and having
    # none at all is "nothing to do", not an error (pull --update on a fresh
    # version). An explicit --all without databases still fails like db drop.
    implicit_all = stale and not (names or multi or select_all)
    if implicit_all:
        select_all = True
    server_running = _odoo_port_busy(version_cfg, env_vars)

    if implicit_all and not db_cmd._candidate_databases(params, name_filter):
        targets: list[str] = []
    else:
        targets = db_cmd._resolve_multi_targets(params, names, multi, select_all, name_filter, verb="update")
    reasons, state, state_path, heads = plan_stale(version_cfg, targets)
    skipped_current: list[str] = []
    if stale:
        skipped_current = [db for db in targets if reasons[db] is None]
        targets = [db for db in targets if reasons[db] is not None]

    if not targets:
        if stale and skipped_current:
            print_success(f"All {len(skipped_current)} database(s) are up to date — nothing to update.")
        else:
            print_info("No databases selected — nothing to update.")
        if as_json:
            _emit_json(json_out, version, modules, [], skipped_current, server_running)
        return 0

    if not as_json:
        _print_plan(targets, reasons, skipped_current, modules)
    if server_running:
        print_warning("An Odoo server is running on this version — restart it after the update.")
    if dry_run:
        print_info("Dry run — nothing executed.")
        if as_json:
            _emit_json(json_out, version, modules, [], skipped_current, server_running, planned=targets)
        return 0
    if not yes and not confirm(f"Update {len(targets)} database(s) with -u {modules} now?", default=True):
        print_info("Aborted.")
        return 0

    try:
        if as_json:
            results = execute_updates(
                version, invocation, targets, modules, heads, state, state_path, timeout, stop_on_error
            )
        else:
            results = _run_with_progress(
                version, invocation, targets, modules, heads, state, state_path, timeout, stop_on_error
            )
    except KeyboardInterrupt:
        print_warning("Interrupted — the running odoo-bin was stopped; that database is not marked current.")
        return 130

    if as_json:
        _emit_json(json_out, version, modules, results, skipped_current, server_running)
        return 0 if all(r.ok for r in results) else 1

    print_summary(results, modules)
    failed = [r for r in results if not r.ok]
    if failed:
        print_error(f"{len(failed)}/{len(results)} database(s) failed — see the log column above")
        return 1
    with_errors = [r for r in results if r.errors]
    if with_errors:
        print_warning(f"{len(with_errors)} database(s) finished with errors in the log and were not marked current")
    else:
        print_success(f"{len(results)} database(s) updated")
    return 0


def _run_with_progress(
    version: str,
    invocation: dict[str, Any],
    targets: list[str],
    modules: str,
    heads: dict[str, str],
    state: dict[str, Any],
    state_path: str,
    timeout: int,
    stop_on_error: bool,
) -> list[UpdateResult]:
    columns = (
        TextColumn("[bold blue]{task.fields[label]}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    with Progress(*columns, console=console) as progress:
        task = progress.add_task("update", total=len(targets), label="starting…")

        def on_issue(db: str, level: str, text: str) -> None:
            _print_issue(progress.console, level, text)

        def on_result(result: UpdateResult) -> None:
            _print_result_line(progress.console, result)
            progress.advance(task)
            done = progress.tasks[task].completed
            if done < len(targets):
                progress.update(task, label=f"Updating {targets[int(done)]} (-u {modules})")
            else:
                progress.update(task, label="done")

        progress.update(task, label=f"Updating {targets[0]} (-u {modules})")
        return execute_updates(
            version,
            invocation,
            targets,
            modules,
            heads,
            state,
            state_path,
            timeout,
            stop_on_error,
            on_issue=on_issue,
            on_result=on_result,
        )


def _print_plan(targets: list[str], reasons: dict[str, str | None], skipped: list[str], modules: str) -> None:
    print_info(f"Databases to update with -u {modules}:")
    for db in targets:
        reason = reasons.get(db)
        suffix = f"  [dim]({escape(reason)})[/dim]" if reason else "  [dim](current — forced)[/dim]"
        console.print(f"  {escape(db)}{suffix}")
    if skipped:
        console.print(f"  [dim]{len(skipped)} up to date, skipped: {escape(', '.join(skipped))}[/dim]")
    console.print()


def _odoo_port_busy(version_cfg: Any, env_vars: dict[str, str]) -> bool:
    from odoodev.core.prerequisites import check_port

    raw = (env_vars.get("ODOO_PORT") or "").strip()
    port = int(raw) if raw.isdigit() else version_cfg.ports.odoo
    return check_port("127.0.0.1", port)


def _emit_json(
    out: Any,
    version: str,
    modules: str,
    results: list[UpdateResult],
    skipped_current: list[str],
    server_running: bool,
    planned: list[str] | None = None,
) -> None:
    import json

    payload: dict[str, Any] = {
        "version": version,
        "modules": modules,
        "results": [r.to_dict() for r in results],
        "skipped_current": skipped_current,
        "server_running": server_running,
    }
    if planned is not None:
        payload["planned"] = planned
    out.write(json.dumps(payload) + "\n")


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command("update")
@click.argument("version", required=False)
@click.option("-n", "--name", "names", multiple=True, help="Database name (repeatable; interactive if omitted)")
@click.option("-m", "--multi", is_flag=True, help="Interactive multi-select (checkbox) of databases")
@click.option("--all", "select_all", is_flag=True, help="Update ALL databases (narrow with --filter)")
@click.option("--filter", "name_filter", default=None, help="Only offer/target databases whose name contains TEXT")
@click.option("--stale", is_flag=True, help="Only databases whose repos changed since their last clean -u all")
@click.option("-u", "--modules", default="all", show_default=True, help="Modules to update (comma-separated or all)")
@click.option("--stop-on-error", is_flag=True, help="Abort the batch after the first failed database")
@click.option("--timeout", default=DEFAULT_TIMEOUT, show_default=True, help="Seconds per database before giving up")
@click.option("--dry-run", is_flag=True, help="Show the databases that would be updated, run nothing")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable result (implies --yes, no progress output)")
@click.option("-y", "--yes", is_flag=True, help="Skip the confirmation prompt")
@click.pass_context
def db_update(
    ctx: click.Context,
    version: str | None,
    names: tuple[str, ...],
    multi: bool,
    select_all: bool,
    name_filter: str | None,
    stale: bool,
    modules: str,
    stop_on_error: bool,
    timeout: int,
    dry_run: bool,
    as_json: bool,
    yes: bool,
) -> None:
    """Run odoo-bin -u on one or many databases (sequentially).

    Selection works like `db drop`: single interactive select by default,
    `-m/--multi` opens a checkbox, `--all` targets every database, `-n` is
    repeatable and `--filter TEXT` narrows the candidates. `--stale` keeps
    only databases whose repositories changed since their last clean `-u all`
    (a database never updated this way always counts as stale).

    Progress is shown per database; only WARNING/ERROR lines from Odoo are
    echoed, the complete output goes to ~/odoodev-logs/. A database exits
    cleanly (exit 0, no ERROR logged) before it is marked current.
    """
    version = resolve_version(ctx, version)
    rc = update_databases(
        version,
        names=names,
        multi=multi,
        select_all=select_all,
        name_filter=name_filter,
        stale=stale,
        modules=modules,
        stop_on_error=stop_on_error,
        timeout=timeout,
        dry_run=dry_run,
        as_json=as_json,
        yes=yes,
    )
    if rc:
        raise SystemExit(rc)


def stale_markers(version_cfg: Any, databases: list[str]) -> dict[str, str] | None:
    """Stale reasons for ``db list``; ``None`` when no state file exists yet.

    Kept cheap on purpose: without a state file nothing was ever recorded, so
    every marker would read "never updated" — that is noise, not information.
    """
    native_dir = getattr(getattr(version_cfg, "paths", None), "native_dir", None)
    if not native_dir or not os.path.exists(update_state_path(version_cfg)):
        return None
    reasons, _state, _path, _heads = plan_stale(version_cfg, databases)
    return {db: reason for db, reason in reasons.items() if reason}


__all__ = [
    "db_update",
    "execute_updates",
    "plan_stale",
    "print_summary",
    "resolve_invocation",
    "stale_markers",
    "update_databases",
]
