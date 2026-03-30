"""Prerequisite checks for Odoo native development."""

from __future__ import annotations

import os
import socket
import subprocess
import sys

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
        print_info("macOS: Download the .pkg installer from https://wkhtmltopdf.org/downloads.html")
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


def check_node() -> str | None:
    """Check if Node.js is installed and return its path.

    Returns:
        Path to node binary, or None if not found.
    """
    extra_paths = []
    os_name = detect_os()
    if os_name == "macos":
        extra_paths = [
            "/opt/homebrew/bin",
            "/usr/local/bin",
        ]
    else:
        extra_paths = [
            "/usr/local/bin",
            "/usr/bin",
        ]

    path = find_executable("node", extra_paths)
    if not path:
        print_warning("Node.js not found")
        if os_name == "macos":
            print_info("Install: brew install node@20")
        else:
            print_info("Install: sudo apt-get install -y nodejs npm")
        return None

    # Parse version
    result = subprocess.run(
        [path, "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        version_str = result.stdout.strip().lstrip("v")
        try:
            major = int(version_str.split(".")[0])
            if major < 20:
                print_warning(f"Node.js {version_str} found — version 20+ recommended")
            else:
                print_success(f"Node.js {version_str} found: {path}")
        except (ValueError, IndexError):
            print_warning(f"Node.js found but could not parse version: {result.stdout.strip()}")

    # Check npm
    if not command_exists("npm"):
        print_warning("npm not found — required for Node.js package management")
        if os_name == "macos":
            print_info("Install: brew install node@20 (includes npm)")
        else:
            print_info("Install: sudo apt-get install -y npm")

    return path


def check_node_packages() -> list[str]:
    """Check which required Node.js packages are missing globally.

    Returns:
        List of missing package names.
    """
    missing = []

    if not command_exists("npm"):
        missing = ["rtlcss", "less", "less-plugin-clean-css"]
        print_warning(f"npm not available — cannot verify Node.js packages: {', '.join(missing)}")
        return missing

    # rtlcss and lessc have their own binaries
    if not command_exists("rtlcss"):
        missing.append("rtlcss")
    if not command_exists("lessc"):
        missing.append("less")

    # less-plugin-clean-css has no binary — check via npm list
    result = subprocess.run(
        ["npm", "list", "-g", "--depth=0"],
        capture_output=True,
        text=True,
    )
    if "less-plugin-clean-css" not in result.stdout:
        missing.append("less-plugin-clean-css")

    if missing:
        print_warning(f"Missing Node.js packages: {', '.join(missing)}")
        print_info("Install: npm install -g rtlcss less less-plugin-clean-css")
    else:
        print_success("All required Node.js packages installed")

    return missing


# macOS Homebrew formulae → description
MACOS_LIBS: dict[str, str] = {
    "openldap": "libldap (python-ldap)",
    "libxml2": "libxml2 (lxml)",
    "libxslt": "libxslt (lxml)",
    "jpeg": "libjpeg (Pillow)",
    "cairo": "cairo (reportlab)",
    "fontconfig": "fontconfig (wkhtmltopdf)",
}

# Linux Debian/Ubuntu packages → description
LINUX_LIBS: dict[str, str] = {
    # Build tools (C compiler, Python headers)
    "python3-dev": "python3-dev (C extension headers)",
    "build-essential": "build-essential (gcc/g++/make)",
    "pkg-config": "pkg-config (library discovery)",
    # Crypto / SSL
    "libssl-dev": "libssl-dev (cryptography/ssl)",
    "libffi-dev": "libffi-dev (cffi/cryptography)",
    # XML / XSLT
    "libxml2-dev": "libxml2-dev (lxml)",
    "libxslt1-dev": "libxslt-dev (lxml)",
    # Image processing (Pillow)
    "libjpeg-dev": "libjpeg-dev (Pillow)",
    "libpng-dev": "libpng-dev (Pillow)",
    "libfreetype6-dev": "libfreetype6-dev (Pillow)",
    # Graphics / PDF
    "libcairo2-dev": "libcairo2-dev (reportlab/cairosvg)",
    # Database
    "libpq-dev": "libpq-dev (psycopg2)",
    # LDAP
    "libldap2-dev": "libldap-dev (python-ldap)",
    "libsasl2-dev": "libsasl2-dev (python-ldap)",
    # Printing
    "libcups2-dev": "libcups2-dev (pycups)",
    # Fonts
    "fontconfig": "fontconfig (wkhtmltopdf)",
    "fonts-dejavu-core": "fonts-dejavu-core",
    "fonts-noto-core": "fonts-noto-core",
}


def check_system_libs() -> list[str]:
    """Check which system libraries needed for Odoo compilation are missing.

    Returns:
        List of missing library descriptions.
    """
    missing = []
    os_name = detect_os()

    if os_name == "macos":
        if not command_exists("brew"):
            print_info("Homebrew not found — skipping system library checks")
            return missing

        for formula, description in MACOS_LIBS.items():
            result = subprocess.run(
                ["brew", "--prefix", formula],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                missing.append(description)

        if missing:
            formulae = " ".join(MACOS_LIBS.keys())
            print_warning(f"Missing system libraries: {', '.join(missing)}")
            print_info(f"Install: brew install {formulae}")
        else:
            print_success("All required system libraries installed")

    else:
        if not command_exists("dpkg"):
            print_info("dpkg not found — skipping system library checks (non-Debian system?)")
            return missing

        for package, description in LINUX_LIBS.items():
            result = subprocess.run(
                ["dpkg", "-l", package],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or "ii" not in result.stdout:
                missing.append(description)

        if missing:
            packages = " ".join(LINUX_LIBS.keys())
            print_warning(f"Missing system libraries: {', '.join(missing)}")
            print_info(f"Install: sudo apt-get install -y {packages}")
        else:
            print_success("All required system libraries installed")

    return missing


def _resolve_symlink_chain(path: str) -> tuple[str, list[str]]:
    """Follow a symlink chain and return the final target and intermediate links.

    Args:
        path: Starting path to resolve

    Returns:
        Tuple of (final_target, list_of_intermediate_links)
    """
    chain: list[str] = [path]
    current = path
    seen: set[str] = set()
    while os.path.islink(current):
        if current in seen:
            break  # circular symlink
        seen.add(current)
        target = os.readlink(current)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(current), target)
        target = os.path.normpath(target)
        chain.append(target)
        current = target
    return current, chain


def check_interpreter_health() -> bool:
    """Check if the current Python interpreter's symlink chain is intact.

    Detects broken UV tool environments where Python versions have been
    removed by 'uv python' updates. Warns early before the environment
    becomes completely unusable.

    Returns:
        True if interpreter is healthy, False if broken links detected.
    """
    python_path = sys.executable
    if not python_path:
        return True  # cannot determine, assume OK

    final_target, chain = _resolve_symlink_chain(python_path)

    if not os.path.exists(final_target):
        print_error(f"Python interpreter broken: {final_target} does not exist")
        print_info("Symlink chain:")
        for i, link in enumerate(chain):
            exists = os.path.exists(link)
            marker = "[OK]" if exists else "[BROKEN]"
            prefix = "  " + ("→ " if i > 0 else "  ")
            print_info(f"{prefix}{marker} {link}")
        print_info("Fix: uv tool upgrade --all")
        return False

    # Also check the venv-style python → python3 chain in UV tool dirs
    tool_dir = os.path.dirname(python_path)
    if "uv/tools" in tool_dir:
        python_link = os.path.join(tool_dir, "python")
        if os.path.islink(python_link):
            final, _ = _resolve_symlink_chain(python_link)
            if not os.path.exists(final):
                print_warning(f"UV tool Python link degraded: {python_link} → {final}")
                print_info("Fix: uv tool upgrade --all")
                return False

    return True


def check_venv_interpreter(venv_dir: str) -> bool:
    """Check if a venv's Python interpreter symlink chain is intact.

    Detects broken venvs where the underlying Python installation was removed
    or updated by UV.

    Args:
        venv_dir: Path to the virtual environment directory

    Returns:
        True if venv interpreter is healthy, False if broken.
    """
    python_bin = os.path.join(venv_dir, "bin", "python3")
    if not os.path.exists(python_bin) and not os.path.islink(python_bin):
        return False  # no python at all

    final_target, chain = _resolve_symlink_chain(python_bin)

    if not os.path.exists(final_target):
        print_error(f"Venv interpreter broken: {python_bin}")
        print_info("Symlink chain:")
        for i, link in enumerate(chain):
            exists = os.path.exists(link)
            marker = "[OK]" if exists else "[BROKEN]"
            prefix = "  " + ("→ " if i > 0 else "  ")
            print_info(f"{prefix}{marker} {link}")
        return False

    return True


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

    results["node"] = check_node() is not None
    results["node_packages"] = len(check_node_packages()) == 0
    results["system_libs"] = len(check_system_libs()) == 0

    if venv_dir:
        python_bin = os.path.join(venv_dir, "bin", "python3")
        if os.path.exists(python_bin):
            missing = check_python_packages(python_bin)
            results["python_packages"] = len(missing) == 0

    return results
