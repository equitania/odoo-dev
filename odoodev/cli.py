"""Main CLI entry point for odoodev."""

from __future__ import annotations

import click

from odoodev import __version__
from odoodev.core.version_registry import available_versions, detect_version_from_cwd


class VersionType(click.ParamType):
    """Custom Click parameter type for Odoo version with auto-detection."""

    name = "version"

    def convert(self, value, param, ctx):
        if value is not None:
            return str(value)
        return value


def resolve_version(ctx: click.Context, version: str | None) -> str:
    """Resolve version from argument or auto-detection.

    Args:
        ctx: Click context
        version: Explicit version or None for auto-detection

    Returns:
        Resolved version string

    Raises:
        click.UsageError: If version cannot be resolved
    """
    if version:
        return version

    detected = detect_version_from_cwd()
    if detected:
        return detected

    available = ", ".join(available_versions())
    raise click.UsageError(
        f"No version specified and auto-detection failed.\n"
        f"Available versions: {available}\n"
        f"Either specify a version or run from within a version directory (~/gitbase/vXX/...)"
    )


@click.group()
@click.version_option(version=__version__, prog_name="odoodev")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Unified CLI for native Odoo development environment management.

    Manages Odoo development environments across versions (v16-v19).
    Supports auto-detection of version from current working directory.
    """
    ctx.ensure_object(dict)

    # First-run hint when no config exists
    if ctx.invoked_subcommand != "setup":
        from odoodev.core.global_config import config_exists

        if not config_exists():
            from odoodev.output import print_info

            print_info("No configuration found. Tip: run 'odoodev setup' (using defaults)")


# Register command groups
from odoodev.commands.config import config  # noqa: E402
from odoodev.commands.db import db  # noqa: E402
from odoodev.commands.docker import docker  # noqa: E402
from odoodev.commands.env import env  # noqa: E402
from odoodev.commands.init_cmd import init  # noqa: E402
from odoodev.commands.pull import pull  # noqa: E402
from odoodev.commands.repos import repos  # noqa: E402
from odoodev.commands.setup_cmd import setup  # noqa: E402
from odoodev.commands.shell_setup import shell_setup  # noqa: E402
from odoodev.commands.start import start  # noqa: E402
from odoodev.commands.stop import stop  # noqa: E402
from odoodev.commands.venv import venv  # noqa: E402

cli.add_command(init)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(pull)
cli.add_command(repos)
cli.add_command(db)
cli.add_command(env)
cli.add_command(venv)
cli.add_command(docker)
cli.add_command(config)
cli.add_command(setup)
cli.add_command(shell_setup)
