"""Prerequisite checks for Odoo native development."""

from __future__ import annotations

import os
import socket
import subprocess

from odoodev.core.environment import command_exists, detect_os, find_executable
from odoodev.output import print_error, print_info, print_success, print_warning


def check_uv() -> bool:
    """Check if UV package manager is installed."""
    if command_exists("uv"):
        print_success("UV package manager found")
        return True
    print_error("UV package manager not found")
    print_info("Install: curl -LsSf https://astral.sh/uv/install.sh | sh")
    return False


def check_docker() -> bool:
    """Check if Docker is installed and running."""
    if not command_exists("docker"):
        print_error("Docker not found")
        return False

    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print_warning("Docker is installed but not running")
        return False

    print_success("Docker is available and running")
    return True


def check_docker_compose() -> bool:
    """Check if docker compose (v2) is available."""
    result = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print_success(f"Docker Compose: {result.stdout.strip()}")
        return True
    print_error("docker compose not available (Docker Compose V2 required)")
    return False


def check_wkhtmltopdf() -> str | None:
    """Check if wkhtmltopdf is installed and return its path.

    Returns:
        Path to wkhtmltopdf binary, or None if not found.
    """
    extra_paths = []
    if detect_os() == "macos":
        extra_paths = [
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]
    else:
        extra_paths = [
            "/usr/local/bin",
            "/usr/bin",
        ]

    path = find_executable("wkhtmltopdf", extra_paths)
    if path:
        print_success(f"wkhtmltopdf found: {path}")
        return path

    print_warning("wkhtmltopdf not found")
    print_info("Install: Download 'patched qt' version → https://wkhtmltopdf.org/downloads.html")
    if detect_os() == "macos":
        print_info("Note: 'brew install wkhtmltopdf' lacks patched Qt — Odoo PDF rendering may not work")
    else:
        print_info("Note: 'apt-get install wkhtmltopdf' lacks patched Qt — Odoo PDF rendering may not work")
    return None


def check_pg_tools() -> str | None:
    """Check if PostgreSQL client tools (pg_dump, psql) are available.

    Returns:
        Path to pg_dump, or None if not found.
    """
    extra_paths = []
    if detect_os() == "macos":
        extra_paths = [
            "/opt/homebrew/opt/libpq/bin",
            "/usr/local/opt/libpq/bin",
            "/opt/homebrew/opt/postgresql@16/bin",
        ]

    path = find_executable("pg_dump", extra_paths)
    if path:
        # Also verify psql is available
        psql_dir = os.path.dirname(path)
        psql_path = os.path.join(psql_dir, "psql")
        if os.path.exists(psql_path):
            print_success(f"PostgreSQL tools found: {psql_dir}")
            return path

    print_warning("PostgreSQL client tools (pg_dump/psql) not found")
    if detect_os() == "macos":
        print_info("Install: brew install libpq && brew link libpq --force")
    else:
        print_info("Install: sudo apt-get install -y postgresql-client")
    return None


def check_port(host: str, port: int) -> bool:
    """Check if a TCP port is accessible.

    Args:
        host: Hostname to check
        port: Port number to check

    Returns:
        True if port is accessible, False otherwise.
    """
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def check_postgres_port(port: int, host: str = "localhost") -> bool:
    """Check if PostgreSQL is accessible on the given port."""
    if check_port(host, port):
        print_success(f"PostgreSQL accessible on {host}:{port}")
        return True
    print_warning(f"PostgreSQL not accessible on {host}:{port}")
    return False


def check_python_packages(venv_python: str, packages: list[str] | None = None) -> list[str]:
    """Check which critical Python packages are missing.

    Args:
        venv_python: Path to Python binary in venv
        packages: List of package names to check. Defaults to critical Odoo packages.

    Returns:
        List of missing package names.
    """
    if packages is None:
        packages = ["babel", "psycopg2", "lxml", "PIL", "werkzeug", "dateutil"]

    # Map import names to package names for display
    import_map = {
        "PIL": "Pillow",
        "dateutil": "python-dateutil",
    }

    missing = []
    for pkg in packages:
        import_name = pkg
        result = subprocess.run(
            [venv_python, "-c", f"import {import_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            display_name = import_map.get(pkg, pkg)
            missing.append(display_name)

    if missing:
        print_warning(f"Missing packages: {', '.join(missing)}")
    else:
        print_success("All critical Python packages installed")

    return missing


def run_all_checks(db_port: int, venv_dir: str | None = None) -> dict[str, bool]:
    """Run all prerequisite checks.

    Args:
        db_port: PostgreSQL port to check
        venv_dir: Optional venv directory to check Python packages

    Returns:
        Dictionary of check names to pass/fail status.
    """
    results = {
        "uv": check_uv(),
        "docker": check_docker(),
        "docker_compose": check_docker_compose(),
        "wkhtmltopdf": check_wkhtmltopdf() is not None,
        "pg_tools": check_pg_tools() is not None,
        "postgres": check_postgres_port(db_port),
    }

    if venv_dir:
        python_bin = os.path.join(venv_dir, "bin", "python3")
        if os.path.exists(python_bin):
            missing = check_python_packages(python_bin)
            results["python_packages"] = len(missing) == 0

    return results
