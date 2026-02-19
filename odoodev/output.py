"""Rich console output helpers for odoodev CLI."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
error_console = Console(stderr=True)


def print_success(message: str) -> None:
    """Print success message in green."""
    console.print(f"[green][OK][/green] {message}")


def print_error(message: str) -> None:
    """Print error message in red to stderr."""
    error_console.print(f"[red][ERROR][/red] {message}")


def print_warning(message: str) -> None:
    """Print warning message in yellow."""
    console.print(f"[yellow][WARN][/yellow] {message}")


def print_info(message: str) -> None:
    """Print info message in blue."""
    console.print(f"[blue][INFO][/blue] {message}")


def print_header(title: str, subtitle: str = "") -> None:
    """Print a styled header panel."""
    content = f"[bold]{title}[/bold]"
    if subtitle:
        content += f"\n{subtitle}"
    console.print(Panel(content, border_style="blue"))


def print_table(title: str, data: dict[str, str], title_style: str = "bold cyan") -> None:
    """Print a key-value table."""
    table = Table(title=title, title_style=title_style, show_header=False, border_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for key, value in data.items():
        table.add_row(key, str(value))
    console.print(table)


def print_version_table(versions: dict) -> None:
    """Print a table of available Odoo versions with their configuration."""
    table = Table(title="Available Odoo Versions", border_style="blue")
    table.add_column("Version", style="bold cyan", justify="center")
    table.add_column("Python", justify="center")
    table.add_column("PostgreSQL", justify="center")
    table.add_column("DB Port", justify="center")
    table.add_column("Odoo Port", justify="center")
    table.add_column("Base Path")

    for ver, cfg in sorted(versions.items()):
        table.add_row(
            f"v{ver}",
            cfg.python,
            cfg.postgres,
            str(cfg.ports.db),
            str(cfg.ports.odoo),
            cfg.paths.base,
        )
    console.print(table)


def confirm(message: str, default: bool = True) -> bool:
    """Interactive confirmation prompt."""
    suffix = " [Y/n] " if default else " [y/N] "
    response = console.input(f"{message}{suffix}").strip().lower()
    if not response:
        return default
    return response in ("y", "yes")
