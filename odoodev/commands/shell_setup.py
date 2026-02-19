"""odoodev shell-setup - Install shell wrapper functions."""

from __future__ import annotations

import click

from odoodev.core.environment import detect_shell
from odoodev.core.shell_integration import install_shell_function
from odoodev.output import print_info, print_success


@click.command("shell-setup")
@click.option(
    "--shell",
    type=click.Choice(["fish", "bash", "zsh", "auto"]),
    default="auto",
    help="Shell type (auto-detect by default)",
)
def shell_setup(shell: str) -> None:
    """Install odoodev shell wrapper function.

    Installs the `odoodev-activate` function into your shell config.
    For Fish: creates ~/.config/fish/conf.d/odoodev.fish
    For Bash/Zsh: appends to .bashrc/.zshrc

    Usage after install:
        odoodev-activate 18   # Activate venv + cd to env dir
    """
    if shell == "auto":
        shell = detect_shell()

    print_info(f"Installing shell integration for {shell}...")
    config_path = install_shell_function(shell)
    print_success(f"Shell function installed: {config_path}")

    print_info("Restart your shell or run:")
    if shell == "fish":
        click.echo(f"  source {config_path}")
    else:
        click.echo(f"  source {config_path}")

    print_info("Then use: odoodev-activate <version>")
