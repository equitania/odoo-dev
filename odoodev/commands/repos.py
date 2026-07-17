"""odoodev repos - Repository management (clone/update/config generation)."""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field

import click
import yaml

from odoodev.click_types import ExpandedPath
from odoodev.core.git_ops import (
    check_repo_access,
    clone_repo_with_progress,
    get_module_paths,
    set_ssh_key,
    switch_branch_and_update,
    update_repo,
    verify_all_repo_access,
)
from odoodev.core.odoo_config import create_odoo_config, resolve_config_paths
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import console, print_error, print_info, print_start_hint, print_success, print_warning

logger = logging.getLogger(__name__)

# Equitania convention: enterprise addon repos are named v16e, v17e, v18e, v19e, ...
_ENTERPRISE_PATH_RE = re.compile(r"^v\d+e$", re.IGNORECASE)


@dataclass
class RepoOpSummary:
    """Outcome of one _process_repos run — surfaced as a summary table.

    ``skipped`` holds repos intentionally excluded via ``use: false``;
    ``failed`` holds (key, error) pairs for clone/update failures that were
    previously swallowed silently.
    """

    cloned: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _find_repos_config(version_cfg) -> str | None:
    """Find repos.yaml or repos-template.yaml for the version.

    Searches native_dir first (preferred), then scripts/ for backwards
    compatibility.
    """
    native_dir = version_cfg.paths.native_dir
    scripts_dir = os.path.join(version_cfg.paths.dev_dir, "scripts")
    for search_dir in (native_dir, scripts_dir):
        for name in ("repos.yaml", "repos-template.yaml"):
            path = os.path.join(search_dir, name)
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
    """Collect all active repository entries from config sections."""
    return [r for r in _collect_all_repos_with_status(config) if r["use"]]


def _collect_all_repos_with_status(config: dict) -> list[dict]:
    """Collect all repository entries with their use/commented status resolved.

    Unlike _collect_all_repos, this includes repos with use=false,
    needed for the interactive selector to show all available repos.
    """
    repos = []
    for section_key in ("addons", "additional", "special", "customers"):
        section_repos = config.get(section_key, [])
        if section_repos:
            for repo in section_repos:
                if "use" in repo:
                    use = repo["use"]
                elif "commented" in repo:
                    use = not repo["commented"]
                else:
                    use = True
                repos.append({**repo, "use": use})
    return repos


def _is_enterprise_repo(meta: dict) -> bool:
    """Detect enterprise repos by section tag or Equitania path convention (vNNe)."""
    if meta.get("section") == "Enterprise":
        return True
    path = os.path.basename(str(meta.get("path", "")).rstrip("/"))
    return bool(_ENTERPRISE_PATH_RE.match(path))


def _prompt_enterprise_inclusion(
    repo_metadata: dict[str, dict],
) -> dict[str, dict]:
    """Ask whether enterprise repositories should be included in the config.

    Detects all enterprise repos that are currently set to use=true. An entry
    counts as enterprise if section == "Enterprise" or its path matches the
    Equitania convention vNNe (e.g. v16e, v17e, v18e, v19e). Prompts once,
    and on "no" sets their use flag to false in the returned metadata. The
    repos.yaml file is left untouched.

    Falls back silently if no enterprise repos are active or no TTY.
    """
    enterprise_keys = [
        key for key, meta in repo_metadata.items() if meta.get("use", True) and _is_enterprise_repo(meta)
    ]
    if not enterprise_keys:
        return repo_metadata
    if not sys.stdin.isatty():
        return repo_metadata

    from odoodev.output import confirm

    print_info(f"Enterprise repositories detected: {', '.join(enterprise_keys)}")
    if confirm("Include enterprise modules in the Odoo config?", default=True):
        return repo_metadata

    new_metadata = dict(repo_metadata)
    for key in enterprise_keys:
        new_metadata[key] = {**repo_metadata[key], "use": False}
    print_warning(f"Enterprise excluded for this config: {', '.join(enterprise_keys)}")
    return new_metadata


def _interactive_addon_selector(
    config: dict,
    repo_metadata: dict[str, dict],
) -> dict[str, dict]:
    """Show interactive checkbox to select active addons for config generation.

    Groups repos by section with questionary.Separator headers.
    Pre-selects repos based on use flag in repo_metadata.

    Args:
        config: Full repos.yaml config dict.
        repo_metadata: Current {repo_key: {section, use}} metadata.

    Returns:
        New repo_metadata dict with updated use flags based on user selection.
    """
    import questionary

    from odoodev.output import checkbox_with_separators

    all_repos = _collect_all_repos_with_status(config)

    # Group by section, preserving encounter order
    seen_sections: list[str] = []
    by_section: dict[str, list[dict]] = {}
    for repo in all_repos:
        section = repo.get("section", "Other")
        if section not in by_section:
            by_section[section] = []
            seen_sections.append(section)
        by_section[section].append(repo)

    # Build choices list with separators
    choices: list[questionary.Choice | questionary.Separator] = []
    for section in seen_sections:
        choices.append(questionary.Separator(f"── {section} ──"))
        for repo in by_section[section]:
            key = repo.get("key", repo.get("path", "unknown"))
            meta = repo_metadata.get(key, {})
            use = meta.get("use", repo.get("use", True))
            label = f"{key} ({repo.get('path', '')})"
            choices.append(questionary.Choice(title=label, value=key, checked=use))

    selected_keys = checkbox_with_separators(
        "Select addons for Odoo config:",
        choices=choices,
        instruction="(↑/↓ navigate, SPACE toggle, ENTER confirm)",
    )

    # Build new metadata with updated use flags
    new_metadata = {}
    for key, meta in repo_metadata.items():
        new_metadata[key] = {**meta, "use": key in selected_keys}

    _print_selection_summary(repo_metadata, new_metadata)

    return new_metadata


def _print_selection_summary(
    original: dict[str, dict],
    updated: dict[str, dict],
) -> None:
    """Print a summary of what changed vs. repos.yaml defaults."""
    enabled = []
    disabled = []
    for key in updated:
        orig_use = original.get(key, {}).get("use", True)
        new_use = updated[key].get("use", True)
        if orig_use != new_use:
            if new_use:
                enabled.append(key)
            else:
                disabled.append(key)

    if not enabled and not disabled:
        print_info("No changes from repos.yaml defaults.")
        return

    if enabled:
        print_success(f"Enabled: {', '.join(enabled)}")
    if disabled:
        print_warning(f"Disabled: {', '.join(disabled)}")


def _process_repos(
    config: dict,
    base_path: str,
    branch: str,
    accessible_paths: set[str],
    *,
    skip_git: bool = False,
) -> tuple[dict[str, list[str]], dict[str, dict], RepoOpSummary]:
    """Process all repositories: clone/update and collect paths.

    Args:
        skip_git: If True, only collect local paths without any git operations.
            Used by the pull command which already performed git ops separately.

    Returns:
        Tuple of (all_paths, repo_metadata, summary).
    """
    all_paths: dict[str, list[str]] = {}
    repo_metadata: dict[str, dict] = {}
    summary = RepoOpSummary()

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
            # Support legacy "commented" field (inverted logic)
            if "use" in repo:
                use = repo["use"]
            elif "commented" in repo:
                use = not repo["commented"]
            else:
                use = True
            suffix = repo.get("suffix", "")
            is_oca = "oca" in repo_path.lower()

            full_path = os.path.join(base_path, repo_path)

            repo_metadata[key] = {"section": section, "use": use, "path": repo_path}

            if not use:
                # Still collect paths for unused repos (shown as comments in config)
                summary.skipped.append(key)
                if os.path.isdir(full_path):
                    paths = get_module_paths(full_path, is_oca)
                    if suffix:
                        paths = [f"{p}{suffix}" for p in paths]
                    all_paths[key] = paths
                continue

            if skip_git:
                # Caller already performed git operations — just collect local paths
                if os.path.isdir(full_path):
                    paths = get_module_paths(full_path, is_oca)
                else:
                    paths = []
            else:
                # Always attempt clone/update — the batch SSH access check is
                # diagnostic only. Blocking on it silently skipped brand-new
                # repos.yaml entries whose access probe failed transiently.
                if accessible_paths and repo_path not in accessible_paths:
                    print_warning(f"{key}: SSH access check failed — attempting anyway")
                existed_before = os.path.isdir(full_path)
                paths, error = switch_branch_and_update(full_path, git_url, branch, base_path, is_oca)
                if error:
                    print_error(f"{key}: {error}")
                    summary.failed.append((key, error))
                elif existed_before:
                    summary.updated.append(key)
                else:
                    print_success(f"{key}: cloned to {full_path}")
                    summary.cloned.append(key)

            if suffix:
                paths = [f"{p}{suffix}" for p in paths]
            all_paths[key] = paths

    return all_paths, repo_metadata, summary


@click.command()
@click.argument("version", required=False)
@click.option("-c", "--config", "config_path", type=ExpandedPath(), help="Custom repos.yaml path")
@click.option("--init", "init_mode", is_flag=True, help="Fresh clone all repositories")
@click.option("--server-only", is_flag=True, help="Only process Odoo server")
@click.option("--config-only", is_flag=True, help="Only generate Odoo config (no git operations)")
@click.option("--skip-access-check", is_flag=True, help="Skip SSH access verification")
@click.option("--select", "select_addons", is_flag=True, help="Interactive addon selector before config generation")
@click.option(
    "--no-enterprise-prompt",
    is_flag=True,
    help="Skip the interactive enterprise inclusion prompt",
)
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
    select_addons: bool,
    no_enterprise_prompt: bool,
    verbose: bool,
) -> None:
    """Clone/update repositories and generate Odoo configuration.

    This command reads repos.yaml (or repos-template.yaml), processes
    all configured repositories, and generates the Odoo config file
    with proper addons_path.
    """
    from odoodev.cli import resolve_version  # Lazy import to avoid circular dependency

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)

    # Find repos config
    if not config_path:
        config_path = _find_repos_config(version_cfg)
        if not config_path:
            print_warning(f"No repos.yaml found for v{version}")
            print_info("Expected locations:")
            print_info(f"  {version_cfg.paths.native_dir}/repos.yaml")
            print_info(f"  {os.path.join(version_cfg.paths.dev_dir, 'scripts')}/repos.yaml")
            from odoodev.core.example_templates import copy_example_templates

            copied, _ = copy_example_templates(version, version_cfg)
            if "repos.yaml" in copied:
                print_success(f"Example repos.yaml created: {copied['repos.yaml']}")
                print_info("Customize it for your project, then run this command again.")
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
        # skip_git=True — this mode is documented as "no git operations".
        all_paths, repo_metadata, _summary = _process_repos(config, base_path, branch, set(), skip_git=True)
        if select_addons:
            if sys.stdin.isatty():
                repo_metadata = _interactive_addon_selector(config, repo_metadata)
            else:
                print_warning("--select requires an interactive terminal, skipping selector")
        elif not no_enterprise_prompt:
            repo_metadata = _prompt_enterprise_inclusion(repo_metadata)
        _generate_config(config, version_cfg, all_paths, repo_metadata)
        return

    # Access verification
    accessible_paths: set[str] = set()
    if not skip_access_check:
        all_repos = _collect_all_repos(config)
        if all_repos:
            print_info("Checking repository access...")
            accessible, inaccessible = verify_all_repo_access(all_repos)
            accessible_paths = {r.get("path", "") for r in accessible}
            if inaccessible:
                print_warning(f"{len(inaccessible)} repositories inaccessible:")
                for repo in inaccessible:
                    repo_key = repo.get("key", repo.get("path", "unknown"))
                    print_warning(f"  - {repo_key} ({repo.get('git_url', '')})")
        else:
            print_info("No custom repositories configured — skipping access check")
    else:
        print_info("Skipping access checks")

    # Process server
    server_config = config.get("server", {})
    server_path = os.path.join(base_path, server_config.get("path", version_cfg.paths.server_subdir))
    server_url = server_config.get("git_url", version_cfg.git.server_url)

    if os.path.isdir(server_path):
        if init_mode:
            print_info(f"Odoo server already exists at {server_path} — updating...")
        else:
            print_info("Updating Odoo server...")
        update_repo(server_path, branch)
    else:
        # Pre-check server access before cloning
        if not skip_access_check:
            print_info(f"Checking server access: {server_url}")
            if not check_repo_access(server_url, timeout=15):
                print_error(f"Cannot access server repository: {server_url}")
                print_info("Check your network, SSH keys, or git URL in repos.yaml")
                raise SystemExit(1)
        print_info(f"Cloning Odoo server to {server_path}...")
        clone_repo_with_progress(server_url, server_path, branch)

    if server_only:
        print_success("Server updated. Done.")
        return

    # Process all repositories
    print_info("Processing repositories...")
    all_paths, repo_metadata, summary = _process_repos(config, base_path, branch, accessible_paths)

    # Interactive addon selector
    if select_addons:
        if sys.stdin.isatty():
            repo_metadata = _interactive_addon_selector(config, repo_metadata)
        else:
            print_warning("--select requires an interactive terminal, skipping selector")
    elif not no_enterprise_prompt:
        repo_metadata = _prompt_enterprise_inclusion(repo_metadata)

    # Generate config — best-effort even with failed repos, so a partial
    # environment stays usable; the exit code below still signals the failure.
    _generate_config(config, version_cfg, all_paths, repo_metadata)

    _print_repo_summary(summary)

    if summary.failed:
        print_error(f"Odoo v{version}: {len(summary.failed)} repositories failed — see errors above")
        raise SystemExit(1)

    print_success(f"Odoo v{version} repositories processed successfully")

    # Code/config changed → remind the user to (re)start Odoo and update modules.
    console.print()
    print_start_hint(version)


def _print_repo_summary(summary: RepoOpSummary) -> None:
    """Print a cloned/updated/skipped/failed summary table (mirrors pull)."""
    from rich.table import Table

    table = Table(title="Repository Summary", title_style="bold cyan")
    table.add_column("Result", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Repositories")

    def _join(keys: list[str]) -> str:
        return ", ".join(keys) if keys else "—"

    table.add_row("Cloned", str(len(summary.cloned)), _join(summary.cloned))
    table.add_row("Updated", str(len(summary.updated)), _join(summary.updated))
    table.add_row("Skipped (use: false)", str(len(summary.skipped)), _join(summary.skipped))
    failed_keys = [key for key, _ in summary.failed]
    table.add_row("Failed", str(len(summary.failed)), _join(failed_keys), style="red" if failed_keys else None)
    console.print(table)

    for key, error in summary.failed:
        print_error(f"{key}: {error}")


def _parse_env_file(env_path: str) -> dict[str, str]:
    """Parse key=value pairs from a .env file.

    Strips surrounding single or double quotes from values so that
    ``DB_PORT="16432"`` and ``DB_PORT=16432`` are equivalent.
    """
    result = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                result[key.strip()] = value
    return result


def _generate_config(config: dict, version_cfg, all_paths: dict, repo_metadata: dict) -> None:
    """Generate Odoo config file from template and collected paths."""
    from odoodev.core.global_config import load_global_config

    template_path, config_dir = resolve_config_paths(version_cfg, config)

    if not os.path.exists(template_path):
        print_warning(f"Config template not found: {template_path}")
        print_info("Odoo config generation skipped")
        return

    # Native mode config
    db_config = config.get("database", {}).get("native", {})
    db_host = db_config.get("host", "localhost")
    db_port = db_config.get("port", version_cfg.ports.db)
    http_port = version_cfg.ports.odoo
    gevent_port = version_cfg.ports.gevent

    # Load global config for database credentials (fallback)
    global_cfg = load_global_config()
    db_user = global_cfg.database.user
    db_password = global_cfg.database.password

    # Prefer .env values if available (version-specific override)
    env_path = os.path.join(os.path.expanduser(version_cfg.paths.native_dir), ".env")
    if os.path.exists(env_path):
        env_vars = _parse_env_file(env_path)
        if "PGUSER" in env_vars:
            db_user = env_vars["PGUSER"]
        if "PGPASSWORD" in env_vars:
            db_password = env_vars["PGPASSWORD"]
        if "DB_PORT" in env_vars:
            try:
                db_port = int(env_vars["DB_PORT"])
            except ValueError:
                print_warning(f"Invalid DB_PORT in .env: {env_vars['DB_PORT']!r}, falling back to {db_port}")
        if "ODOO_PORT" in env_vars:
            try:
                http_port = int(env_vars["ODOO_PORT"])
            except ValueError:
                print_warning(f"Invalid ODOO_PORT in .env: {env_vars['ODOO_PORT']!r}, falling back to {http_port}")
        if "GEVENT_PORT" in env_vars:
            try:
                gevent_port = int(env_vars["GEVENT_PORT"])
            except ValueError:
                print_warning(
                    f"Invalid GEVENT_PORT in .env: {env_vars['GEVENT_PORT']!r}, falling back to {gevent_port}"
                )

    # Active migration: the shared source port must win over repos.yaml/.env values,
    # otherwise a regenerated target config points at the wrong PostgreSQL.
    from odoodev.core.migration_config import migration_target_port

    shared_port = migration_target_port(version_cfg.version)
    if shared_port is not None and db_port != shared_port:
        print_info(f"[MIGRATION] Config uses shared DB port {shared_port} (instead of {db_port})")
        db_port = shared_port

    output = create_odoo_config(
        template_path=template_path,
        config_dir=config_dir,
        all_paths=all_paths,
        repo_metadata=repo_metadata,
        config_mode="native",
        native_db_host=db_host,
        native_db_port=db_port,
        db_user=db_user,
        db_password=db_password,
        admin_passwd=db_password,
        http_port=http_port,
        gevent_port=gevent_port,
    )

    if output:
        print_success(f"Config generated: {output}")
    else:
        print_error("Config generation failed")
