"""odoodev venv - Virtual environment management."""

from __future__ import annotations

import hashlib
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


def _hash_file(path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


@click.group()
def venv() -> None:
    """Manage Python virtual environments."""


@venv.command("setup")
@click.argument("version", required=False)
@click.option("--force", is_flag=True, help="Recreate even if venv exists")
@click.pass_context
def venv_setup(ctx: click.Context, version: str | None, force: bool) -> None:
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
            # Remove existing
            print_info("Removing existing venv...")
            subprocess.run(["rm", "-rf", venv_dir], check=True)

    # Create venv with UV
    python_version = version_cfg.python
    env_name = version_cfg.env_name
    print_info(f"Creating UV venv with Python {python_version}...")

    result = subprocess.run(
        ["uv", "venv", "--python", python_version, "--prompt", env_name, venv_dir],
        cwd=native_dir,
    )
    if result.returncode != 0:
        print_error("Failed to create virtual environment")
        raise SystemExit(1)

    # Install requirements if available
    if os.path.exists(requirements):
        print_info(f"Installing requirements from {requirements}...")
        result = subprocess.run(
            ["uv", "pip", "install", "-r", requirements],
            cwd=native_dir,
            env={**os.environ, "VIRTUAL_ENV": venv_dir},
        )
        if result.returncode != 0:
            print_error("Failed to install requirements")
            raise SystemExit(1)

        # Store requirements hash
        hash_file = os.path.join(venv_dir, ".requirements.sha256")
        with open(hash_file, "w") as f:
            f.write(_hash_file(requirements))
        print_success("Requirements installed and hash stored")
    else:
        print_warning(f"No requirements.txt found at {requirements}")

    print_success(f"Virtual environment created at {venv_dir}")


@venv.command("check")
@click.argument("version", required=False)
@click.pass_context
def venv_check(ctx: click.Context, version: str | None) -> None:
    """Check venv status and requirements freshness."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    venv_dir = _get_venv_dir(version_cfg)
    requirements = _get_requirements_path(version_cfg)

    if not os.path.exists(venv_dir):
        print_error(f"No venv found at {venv_dir}")
        print_info(f"Run: odoodev venv setup {version}")
        raise SystemExit(1)

    if os.path.islink(venv_dir):
        print_warning(".venv is a symlink — may cause issues with native development")

    # Check Python version
    python_bin = os.path.join(venv_dir, "bin", "python3")
    if os.path.exists(python_bin):
        result = subprocess.run([python_bin, "--version"], capture_output=True, text=True)
        print_info(f"Python: {result.stdout.strip()}")
    else:
        print_warning("Python binary not found in venv")

    # Check requirements hash
    if os.path.exists(requirements):
        hash_file = os.path.join(venv_dir, ".requirements.sha256")
        current_hash = _hash_file(requirements)
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
        print_error(f"No venv found at {venv_dir}")
        print_info(f"Run: odoodev venv setup {version}")
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
