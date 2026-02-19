"""odoodev repos - Repository management (clone/update/config generation)."""

from __future__ import annotations

import logging
import os

import click
import yaml

from odoodev.cli import resolve_version
from odoodev.core.git_ops import (
    clone_repo_fresh,
    get_module_paths,
    set_ssh_key,
    switch_branch_and_update,
    verify_all_repo_access,
)
from odoodev.core.odoo_config import create_odoo_config
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import print_error, print_info, print_success, print_warning

logger = logging.getLogger(__name__)


def _find_repos_config(version_cfg) -> str | None:
    """Find repos.yaml or repos-template.yaml for the version."""
    scripts_dir = os.path.join(version_cfg.paths.dev_dir, "scripts")
    for name in ("repos.yaml", "repos-template.yaml"):
        path = os.path.join(scripts_dir, name)
        if os.path.exists(path):
            return path
    return None


def _load_repos_config(config_path: str) -> dict:
    """Load repos YAML configuration."""
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Expand ~ in paths
    if "paths" in config:
        for key, value in config["paths"].items():
            if isinstance(value, str):
                config["paths"][key] = os.path.expanduser(value)

    return config


def _collect_all_repos(config: dict) -> list[dict]:
    """Collect all repository entries from config sections."""
    repos = []
    for section_key in ("addons", "additional", "special", "customers"):
        section_repos = config.get(section_key, [])
        if section_repos:
            for repo in section_repos:
                if not repo.get("commented", False):
                    repos.append(repo)
    return repos


def _process_repos(
    config: dict,
    base_path: str,
    branch: str,
    accessible_paths: set[str],
    init_mode: bool = False,
) -> tuple[dict[str, list[str]], dict[str, dict]]:
    """Process all repositories: clone/update and collect paths.

    Returns:
        Tuple of (all_paths, repo_metadata).
    """
    all_paths: dict[str, list[str]] = {}
    repo_metadata: dict[str, dict] = {}

    # Base addons
    if "base_addons" in config:
        all_paths["base"] = [os.path.expanduser(p) for p in config["base_addons"]]

    # Process each section
    for section_key in ("addons", "additional", "special", "customers"):
        section_repos = config.get(section_key, [])
        if not section_repos:
            continue

        for repo in section_repos:
            key = repo.get("key", repo.get("path", "unknown"))
            repo_path = repo.get("path", "")
            git_url = repo.get("git_url", "")
            section = repo.get("section", "Other")
            commented = repo.get("commented", False)
            suffix = repo.get("suffix", "")
            is_oca = "oca" in repo_path.lower()

            full_path = os.path.join(base_path, repo_path)

            repo_metadata[key] = {"section": section, "commented": commented}

            if commented:
                # Still collect paths for commented repos (shown as comments in config)
                if os.path.isdir(full_path):
                    paths = get_module_paths(full_path, is_oca)
                    if suffix:
                        paths = [f"{p}{suffix}" for p in paths]
                    all_paths[key] = paths
                continue

            # Check if accessible
            if repo_path in accessible_paths or not accessible_paths:
                if init_mode:
                    clone_repo_fresh(git_url, full_path, branch)
                    paths = get_module_paths(full_path, is_oca)
                elif os.path.isdir(full_path):
                    paths = switch_branch_and_update(full_path, git_url, branch, base_path, is_oca)
                else:
                    # Clone new
                    paths = switch_branch_and_update(full_path, git_url, branch, base_path, is_oca)
            elif os.path.isdir(full_path):
                # Not accessible but exists locally — use existing paths
                paths = get_module_paths(full_path, is_oca)
            else:
                print_warning(f"Skipping {key} — not accessible and not found locally")
                paths = []

            if suffix:
                paths = [f"{p}{suffix}" for p in paths]
            all_paths[key] = paths

    return all_paths, repo_metadata


@click.command()
@click.argument("version", required=False)
@click.option("-c", "--config", "config_path", type=click.Path(), help="Custom repos.yaml path")
@click.option("--init", "init_mode", is_flag=True, help="Fresh clone all repositories")
@click.option("--server-only", is_flag=True, help="Only process Odoo server")
@click.option("--config-only", is_flag=True, help="Only generate Odoo config (no git operations)")
@click.option("--skip-access-check", is_flag=True, help="Skip SSH access verification")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def repos(
    ctx: click.Context,
    version: str | None,
    config_path: str | None,
    init_mode: bool,
    server_only: bool,
    config_only: bool,
    skip_access_check: bool,
    verbose: bool,
) -> None:
    """Clone/update repositories and generate Odoo configuration.

    This command reads repos.yaml (or repos-template.yaml), processes
    all configured repositories, and generates the Odoo config file
    with proper addons_path.
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

    print_info(f"Odoo v{version} — Branch: {branch}")

    # Config-only mode: scan local repos and generate config
    if config_only:
        print_info("Config-only mode — scanning local repositories...")
        all_paths, repo_metadata = _process_repos(config, base_path, branch, set(), init_mode=False)
        _generate_config(config, version_cfg, all_paths, repo_metadata)
        return

    # Access verification
    accessible_paths: set[str] = set()
    if not skip_access_check:
        print_info("Checking repository access...")
        all_repos = _collect_all_repos(config)
        accessible, inaccessible = verify_all_repo_access(all_repos)
        accessible_paths = {r.get("path", "") for r in accessible}
        if inaccessible:
            print_warning(f"{len(inaccessible)} repositories inaccessible")
    else:
        print_info("Skipping access checks")

    # Process server
    server_config = config.get("server", {})
    server_path = os.path.join(base_path, server_config.get("path", version_cfg.paths.server_subdir))
    server_url = server_config.get("git_url", version_cfg.git.server_url)

    if init_mode or not os.path.isdir(server_path):
        print_info(f"Cloning Odoo server to {server_path}...")
        clone_repo_fresh(server_url, server_path, branch)
    else:
        print_info("Updating Odoo server...")
        from odoodev.core.git_ops import update_repo

        update_repo(server_path, branch)

    if server_only:
        print_success("Server updated. Done.")
        return

    # Process all repositories
    print_info("Processing repositories...")
    all_paths, repo_metadata = _process_repos(config, base_path, branch, accessible_paths, init_mode)

    # Generate config
    _generate_config(config, version_cfg, all_paths, repo_metadata)

    print_success(f"Odoo v{version} repositories processed successfully")


def _generate_config(config: dict, version_cfg, all_paths: dict, repo_metadata: dict) -> None:
    """Generate Odoo config file from template and collected paths."""
    paths = config.get("paths", {})
    template_path = paths.get("template")
    config_dir = paths.get("config_dir", version_cfg.paths.myconfs_dir)
    config_dir = os.path.expanduser(config_dir)

    if not template_path:
        # Fall back to template in conf dir
        template_path = os.path.join(
            version_cfg.paths.conf_dir, f"odoo{version_cfg.version}_template.conf"
        )

    template_path = os.path.expanduser(template_path)

    if not os.path.exists(template_path):
        print_warning(f"Config template not found: {template_path}")
        print_info("Odoo config generation skipped")
        return

    # Native mode config
    db_config = config.get("database", {}).get("native", {})
    db_host = db_config.get("host", "localhost")
    db_port = db_config.get("port", version_cfg.ports.db)

    output = create_odoo_config(
        template_path=template_path,
        config_dir=config_dir,
        all_paths=all_paths,
        repo_metadata=repo_metadata,
        config_mode="native",
        native_db_host=db_host,
        native_db_port=db_port,
    )

    if output:
        print_success(f"Config generated: {output}")
    else:
        print_error("Config generation failed")
