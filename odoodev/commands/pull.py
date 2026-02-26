"""odoodev pull - Quick git pull across all configured repositories."""

from __future__ import annotations

import logging
import os

import click

from odoodev.cli import resolve_version
from odoodev.commands.repos import _collect_all_repos, _find_repos_config, _load_repos_config
from odoodev.core.git_ops import set_ssh_key, update_repo
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import console, print_error, print_info, print_success, print_warning

logger = logging.getLogger(__name__)


@click.command()
@click.argument("version", required=False)
@click.option("-c", "--config", "config_path", type=click.Path(), help="Custom repos.yaml path")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def pull(ctx: click.Context, version: str | None, config_path: str | None, verbose: bool) -> None:
    """Pull (update) all existing repositories.

    Unlike 'repos', this only runs git pull on repositories that
    already exist locally. No cloning, no SSH access check, no
    config regeneration.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)

    # Find repos config
    if not config_path:
        config_path = _find_repos_config(version_cfg)
        if not config_path:
            print_error(f"No repos.yaml found for v{version}")
            raise SystemExit(1)

    config = _load_repos_config(config_path)
    branch = config.get("branch", "develop")
    base_path = config.get("paths", {}).get("base", version_cfg.paths.base_expanded)
    base_path = os.path.expanduser(base_path)

    # SSH key
    ssh_key = config.get("ssh_key")
    if ssh_key:
        set_ssh_key(ssh_key)

    print_info(f"Pulling v{version} repositories — Branch: {branch}")

    updated: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    # Server repo
    server_config = config.get("server", {})
    server_path = os.path.join(base_path, server_config.get("path", version_cfg.paths.server_subdir))
    server_name = f"server ({os.path.basename(server_path)})"

    if os.path.isdir(server_path):
        if update_repo(server_path, branch):
            updated.append(server_name)
        else:
            failed.append(server_name)
    else:
        skipped.append(server_name)

    # Addon repos
    all_repos = _collect_all_repos(config)
    for repo in all_repos:
        key = repo.get("key", repo.get("path", "unknown"))
        repo_path = repo.get("path", "")
        full_path = os.path.join(base_path, repo_path)

        if os.path.isdir(full_path):
            if update_repo(full_path, branch):
                updated.append(key)
            else:
                failed.append(key)
        else:
            skipped.append(key)

    # Summary table
    from rich.table import Table

    table = Table(title=f"Pull Summary — v{version}", border_style="blue")
    table.add_column("Status", style="bold", justify="center")
    table.add_column("Count", justify="center")
    table.add_column("Repositories")

    if updated:
        table.add_row("[green]Updated[/green]", str(len(updated)), ", ".join(updated))
    if skipped:
        table.add_row("[yellow]Skipped[/yellow]", str(len(skipped)), ", ".join(skipped))
    if failed:
        table.add_row("[red]Failed[/red]", str(len(failed)), ", ".join(failed))

    console.print(table)

    total = len(updated) + len(skipped) + len(failed)
    if failed:
        print_warning(f"{len(failed)}/{total} repositories failed")
        raise SystemExit(1)
    elif updated:
        print_success(f"{len(updated)}/{total} repositories updated")
    else:
        print_info("No repositories to update (all skipped)")
