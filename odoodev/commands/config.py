"""odoodev config - Global configuration and version listing."""

from __future__ import annotations

import click

from odoodev.core.environment import detect_arch, detect_docker_platform, detect_os, detect_shell, detect_user
from odoodev.core.version_registry import load_versions
from odoodev.output import print_header, print_table, print_version_table


@click.group()
def config() -> None:
    """Global configuration and available versions."""


@config.command("versions")
def config_versions() -> None:
    """List all available Odoo versions with their configuration."""
    versions = load_versions()
    print_version_table(versions)


@config.command("show")
def config_show() -> None:
    """Show current platform, global config, and environment information."""
    from odoodev.core.global_config import config_exists, get_config_path, load_global_config

    print_header("odoodev Environment", "Platform & configuration details")

    info = {
        "OS": detect_os(),
        "Architecture": detect_arch(),
        "Docker Platform": detect_docker_platform(),
        "Shell": detect_shell(),
        "User": detect_user(),
    }
    print_table("Platform", info)

    # Global configuration
    global_cfg = load_global_config()
    config_info = {
        "Config File": str(get_config_path()),
        "Status": "Custom" if config_exists() else "Defaults (no config file)",
        "Base Directory": global_cfg.base_dir,
        "Active Versions": ", ".join(f"v{v}" for v in global_cfg.active_versions),
        "DB User": global_cfg.database.user,
    }
    print_table("Global Configuration", config_info)

    versions = load_versions()
    print_version_table(versions)
