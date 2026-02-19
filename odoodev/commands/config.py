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
    """Show current platform and environment information."""
    print_header("odoodev Environment", "Platform & configuration details")

    info = {
        "OS": detect_os(),
        "Architecture": detect_arch(),
        "Docker Platform": detect_docker_platform(),
        "Shell": detect_shell(),
        "User": detect_user(),
    }
    print_table("Platform", info)

    versions = load_versions()
    print_version_table(versions)
