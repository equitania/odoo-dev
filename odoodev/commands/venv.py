"""odoodev venv - Virtual environment management."""

from __future__ import annotations

import os
import subprocess

import click

from odoodev.cli import resolve_version
from odoodev.core.environment import detect_shell
from odoodev.core.version_registry import get_version
from odoodev.output import confirm, print_error, print_info, print_success, print_warning


def _get_venv_dir(version_cfg) -> str:
    """Get the .venv directory path for the version."""
    return os.path.join(version_cfg.paths.native_dir, ".venv")


def _get_requirements_path(version_cfg) -> str:
    """Get the requirements.txt path for the version."""
    return os.path.join(version_cfg.paths.native_dir, "requirements.txt")


@click.group()
def venv() -> None:
    """Manage Python virtual environments."""


@venv.command("remove")
@click.argument("version", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def venv_remove(ctx: click.Context, version: str | None, yes: bool) -> None:
    """Remove the virtual environment for a version."""
    import shutil

    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    venv_dir = _get_venv_dir(version_cfg)

    if not os.path.exists(venv_dir) and not os.path.islink(venv_dir):
        print_warning(f"No venv found at {venv_dir}")
        return

    if not yes:
        print_warning(f"This will permanently delete the venv at {venv_dir}")
        if not confirm("Proceed?", default=False):
            print_info("Aborted.")
            return

    try:
        if os.path.islink(venv_dir):
            os.remove(venv_dir)
        else:
            shutil.rmtree(venv_dir)
        print_success(f"Venv removed: {venv_dir}")
        print_info(f"Recreate with: odoodev venv setup {version}")
    except OSError as e:
        print_error(f"Failed to remove venv: {e}")
        raise SystemExit(1) from e


@venv.command("setup")
@click.argument("version", required=False)
@click.option("--force", is_flag=True, help="Recreate even if venv exists")
@click.option("--python-version", "python_ver", default=None, hidden=True, help="Full Python version override")
@click.pass_context
def venv_setup(ctx: click.Context, version: str | None, force: bool, python_ver: str | None) -> None:
    """Create virtual environment with UV and install requirements."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    venv_dir = _get_venv_dir(version_cfg)
    native_dir = version_cfg.paths.native_dir
    requirements = _get_requirements_path(version_cfg)

    if os.path.exists(venv_dir):
        if os.path.islink(venv_dir):
            print_warning(f".venv is a symlink at {venv_dir} — removing for native setup")
            os.remove(venv_dir)
        elif not force:
            if not confirm(f".venv already exists at {venv_dir}. Recreate?", default=False):
                print_info("Keeping existing venv.")
                return

    # Use explicit patch version if provided, otherwise major.minor from config
    python_version = python_ver or version_cfg.python
    env_name = version_cfg.env_name
    print_info(f"Creating UV venv with Python {python_version}...")

    cmd = ["uv", "venv", "--python", python_version, "--prompt", env_name]
    if os.path.exists(venv_dir):
        cmd.append("--clear")
    cmd.append(venv_dir)

    result = subprocess.run(cmd, cwd=native_dir)
    if result.returncode != 0:
        print_error("Failed to create virtual environment")
        raise SystemExit(1)

    # Odoo 16/17 need setuptools (pkg_resources) — not bundled in Python 3.12+
    try:
        ver_int = int(version)
    except (ValueError, TypeError):
        ver_int = 0
    if ver_int in (16, 17):
        from odoodev.core.venv_manager import ensure_setuptools

        print_info("Installing setuptools (required for Odoo v16/v17)...")
        if ensure_setuptools(venv_dir):
            print_success("setuptools installed")
        else:
            print_warning("Failed to install setuptools — pkg_resources may be missing")

    # Install requirements if available
    if os.path.exists(requirements):
        from odoodev.core.venv_manager import install_requirements, store_requirements_hash

        print_info(f"Installing requirements from {requirements}...")
        if not install_requirements(venv_dir, requirements, capture=False, cwd=native_dir):
            print_error("Failed to install requirements")
            raise SystemExit(1)

        store_requirements_hash(venv_dir, requirements)
        print_success("Requirements installed and hash stored")
    else:
        print_warning(f"No requirements.txt found at {requirements}")

    print_success(f"Virtual environment created at {venv_dir}")


@venv.command("check")
@click.argument("version", required=False)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output (non-interactive)")
@click.pass_context
def venv_check(ctx: click.Context, version: str | None, as_json: bool) -> None:
    """Check venv status and requirements freshness."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    venv_dir = _get_venv_dir(version_cfg)
    requirements = _get_requirements_path(version_cfg)

    if as_json:
        import json
        import sys

        from odoodev.core.venv_manager import check_venv_python_matches, get_full_python_version, hash_requirements

        exists = os.path.isdir(venv_dir)
        python_bin = os.path.join(venv_dir, "bin", "python3")
        requirements_current: bool | None = None
        if exists and os.path.exists(requirements):
            hash_file = os.path.join(venv_dir, ".requirements.sha256")
            if os.path.exists(hash_file):
                with open(hash_file) as f:
                    requirements_current = f.read().strip() == hash_requirements(requirements)
        payload = {
            "version": version,
            "venv_dir": venv_dir,
            "exists": exists,
            "is_symlink": os.path.islink(venv_dir),
            "python_version": get_full_python_version(venv_dir) if exists else None,
            "python_matches": (
                check_venv_python_matches(venv_dir, version_cfg.python)
                if exists and os.path.exists(python_bin)
                else None
            ),
            "requirements_current": requirements_current,
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        raise SystemExit(0 if exists else 1)

    if not os.path.exists(venv_dir):
        print_warning(f"No venv found at {venv_dir}")
        if confirm(f"Create venv for v{version} now?"):
            ctx.invoke(venv_setup, version=version, force=False)
            if not os.path.exists(venv_dir):
                print_error("Failed to create virtual environment")
                raise SystemExit(1)
        else:
            raise SystemExit(1)

    if os.path.islink(venv_dir):
        print_warning(".venv is a symlink — may cause issues with native development")

    # Check Python version and validate against configuration
    python_bin = os.path.join(venv_dir, "bin", "python3")
    if os.path.exists(python_bin):
        result = subprocess.run([python_bin, "--version"], capture_output=True, text=True)
        print_info(f"Python: {result.stdout.strip()}")

        from odoodev.core.venv_manager import check_venv_python_matches

        if not check_venv_python_matches(venv_dir, version_cfg.python):
            print_warning(f"Python version mismatch! Expected {version_cfg.python}")
            print_info(f"Run: odoodev venv setup {version} --force")
    else:
        print_warning("Python binary not found in venv")

    # Check if a newer patch version is available on the system
    from odoodev.core.venv_manager import get_full_python_version, get_system_python_version

    venv_full = get_full_python_version(venv_dir)
    system_full = get_system_python_version(version_cfg.python)
    if venv_full and system_full and venv_full != system_full:
        print_warning(f"Newer Python available: venv has {venv_full}, system has {system_full}")
        if confirm(f"Recreate venv with Python {system_full}?", default=False):
            ctx.invoke(venv_setup, version=version, force=True, python_ver=system_full)

    # Check requirements hash
    if os.path.exists(requirements):
        from odoodev.core.venv_manager import hash_requirements

        hash_file = os.path.join(venv_dir, ".requirements.sha256")
        current_hash = hash_requirements(requirements)
        if os.path.exists(hash_file):
            with open(hash_file) as f:
                stored_hash = f.read().strip()
            if current_hash == stored_hash:
                print_success("requirements.txt is up to date")
            else:
                print_warning("requirements.txt has changed since last install")
                print_info(f"Run: odoodev venv setup {version} --force")
        else:
            print_warning("No requirements hash stored — cannot check freshness")

    print_success(f"Venv exists at {venv_dir}")


@venv.command("activate")
@click.argument("version", required=False)
@click.pass_context
def venv_activate(ctx: click.Context, version: str | None) -> None:
    """Print the venv activation command for current shell."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    venv_dir = _get_venv_dir(version_cfg)

    if not os.path.exists(venv_dir):
        print_warning(f"No venv found at {venv_dir}")
        if confirm(f"Create venv for v{version} now?"):
            ctx.invoke(venv_setup, version=version, force=False)
            if not os.path.exists(venv_dir):
                print_error("Failed to create virtual environment")
                raise SystemExit(1)
        else:
            raise SystemExit(1)

    shell = detect_shell()
    if shell == "fish":
        click.echo(f"source {venv_dir}/bin/activate.fish")
    else:
        click.echo(f"source {venv_dir}/bin/activate")


@venv.command("path")
@click.argument("version", required=False)
@click.pass_context
def venv_path(ctx: click.Context, version: str | None) -> None:
    """Print the venv directory path."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    click.echo(_get_venv_dir(version_cfg))
