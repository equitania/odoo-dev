"""odoodev doctor - Environment health checks."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import click

from odoodev import __version__
from odoodev.cli import resolve_version
from odoodev.core.prerequisites import run_all_checks
from odoodev.core.version_registry import get_version
from odoodev.output import console, print_header, print_info

PYPI_PACKAGE = "odoodev-equitania"
PYPI_TIMEOUT = 2.0

# Checks that fail the doctor run (exit code 1). Everything else is a soft warning.
HARD_CHECKS = frozenset({"uv", "docker", "docker_compose", "pg_tools", "postgres", "python_packages"})

# Short remediation hint per check, shown in the summary table on failure.
HINTS = {
    "uv": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    "docker": "Install/start Docker Desktop or Docker Engine",
    "docker_compose": "Install the Docker Compose v2 plugin",
    "wkhtmltopdf": "patched-Qt: macOS .pkg from wkhtmltopdf.org / Linux .deb from github.com/wkhtmltopdf/packaging",
    "pg_tools": "brew install libpq  /  apt install postgresql-client",
    "postgres": "odoodev docker up <version>",
    "node": "brew install node@20  /  NodeSource setup_20.x",
    "node_packages": "sudo npm install -g rtlcss less less-plugin-clean-css",
    "system_libs": "See install hint above",
    "7zip": "needed for .7z restore — macOS: brew install 7zip / Linux: apt install 7zip (or p7zip-full)",
    "zstd": "needed for .tar.zst (stream) restore — macOS: brew install zstd / Linux: apt install zstd",
    "python_packages": "odoodev venv setup <version> --force",
}


def _check_pypi_freshness() -> tuple[str | None, str | None]:
    """Fetch the latest released version from PyPI.

    Returns:
        (latest_version, error_message) — error_message is set when the
        lookup failed (offline, timeout); latest_version is None then.
    """
    url = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"
    try:
        with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT) as response:  # noqa: S310 — fixed https URL
            data = json.load(response)
        return data["info"]["version"], None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        return None, str(e)


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted version into a comparable int tuple (non-numeric parts → 0)."""
    parts = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _pypi_status_row(latest: str | None, error: str | None) -> tuple[str, str]:
    """Build (status, note) for the PyPI freshness row."""
    if latest is None:
        return "[yellow]~[/yellow]", f"PyPI check skipped ({'offline' if error else 'unknown'})"
    if _version_tuple(latest) > _version_tuple(__version__):
        return "[yellow]~[/yellow]", f"Update available: {latest} (installed: {__version__})"
    return "[green]✓[/green]", f"Up to date ({__version__})"


def _render_summary_table(results: dict[str, bool], pypi_row: tuple[str, str]) -> None:
    """Print the compact Rich summary table after the detailed check output."""
    from rich.table import Table

    table = Table(title="odoodev doctor — Summary")
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Notes")

    for name, ok in results.items():
        if ok:
            status = "[green]✓[/green]"
            note = ""
        elif name in HARD_CHECKS:
            status = "[red]✗[/red]"
            note = HINTS.get(name, "")
        else:
            status = "[yellow]~[/yellow]"
            note = HINTS.get(name, "")
        table.add_row(name, status, note)

    table.add_row("pypi", pypi_row[0], pypi_row[1])
    console.print(table)


@click.command("doctor")
@click.argument("version", required=False)
@click.pass_context
def doctor(ctx: click.Context, version: str | None) -> None:
    """Check the development environment health.

    Runs all prerequisite checks (uv, Docker, PostgreSQL tools, Node.js,
    system libraries) plus a PyPI freshness check for odoodev itself.
    With a VERSION, also probes the version's PostgreSQL port and venv
    packages. Exits with code 1 when a hard requirement is missing.

    \b
    Examples:
        odoodev doctor          # general checks (version auto-detected if possible)
        odoodev doctor 18       # include v18 PostgreSQL port + venv packages
    """
    version_cfg = None
    try:
        version = resolve_version(ctx, version)
        version_cfg = get_version(version)
    except click.UsageError:
        print_info("No version detected — skipping PostgreSQL port and venv checks")

    print_header("odoodev doctor", f"v{version}" if version_cfg else "general checks")

    if version_cfg:
        venv_dir = os.path.join(version_cfg.paths.native_dir, ".venv")
        results = run_all_checks(version_cfg.ports.db, venv_dir)
    else:
        results = run_all_checks(db_port=0)
        results.pop("postgres", None)

    pypi_row = _pypi_status_row(*_check_pypi_freshness())

    console.print()
    _render_summary_table(results, pypi_row)

    failed_hard = [name for name in HARD_CHECKS if name in results and not results[name]]
    if failed_hard:
        console.print()
        print_info(f"Hard checks failed: {', '.join(sorted(failed_hard))}")
        raise SystemExit(1)
