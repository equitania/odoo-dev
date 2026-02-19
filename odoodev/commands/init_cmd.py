"""odoodev init - Initialize a new Odoo development environment."""

from __future__ import annotations

import os

import click

from odoodev.cli import resolve_version
from odoodev.core.docker_compose import render_compose
from odoodev.core.environment import detect_docker_platform, detect_user
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import confirm, print_info, print_success, print_warning


@click.command()
@click.argument("version", required=False)
@click.option("--non-interactive", is_flag=True, help="Use all defaults without prompting")
@click.option("--skip-repos", is_flag=True, help="Skip repository cloning")
@click.option("--skip-docker", is_flag=True, help="Skip Docker service startup")
@click.pass_context
def init(
    ctx: click.Context,
    version: str | None,
    non_interactive: bool,
    skip_repos: bool,
    skip_docker: bool,
) -> None:
    """Initialize a new Odoo development environment.

    Creates directory structure, .env file, docker-compose.yml,
    virtual environment, and optionally clones repositories.

    Example: odoodev init 18
    """
    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)

    print_info(f"Initializing Odoo v{version} native development environment")

    # Step 1: Create directories
    dirs_to_create = [
        version_cfg.paths.base_expanded,
        version_cfg.paths.dev_dir,
        version_cfg.paths.native_dir,
        version_cfg.paths.myconfs_dir,
    ]

    for d in dirs_to_create:
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
            print_info(f"Created: {d}")

    native_dir = version_cfg.paths.native_dir

    # Step 2: Create .env
    env_file = os.path.join(native_dir, ".env")
    if os.path.exists(env_file):
        print_info(f".env already exists at {env_file}")
    else:
        print_info("Creating .env file...")
        ctx.invoke(
            _get_env_setup_cmd(),
            version=version,
            non_interactive=non_interactive,
        )

    # Step 3: Create docker-compose.yml
    compose_file = os.path.join(native_dir, "docker-compose.yml")
    if os.path.exists(compose_file):
        print_info(f"docker-compose.yml already exists at {compose_file}")
    else:
        print_info("Creating docker-compose.yml...")
        user = detect_user()
        docker_platform = detect_docker_platform()
        content = render_compose(version_cfg, user, docker_platform)
        with open(compose_file, "w", encoding="utf-8") as f:
            f.write(content)
        print_success(f"docker-compose.yml created at {compose_file}")

    # Step 4: Start Docker services
    if not skip_docker:
        if non_interactive or confirm("Start Docker services (PostgreSQL)?"):
            print_info("Starting Docker services...")
            import subprocess

            result = subprocess.run(["docker", "compose", "up", "-d"], cwd=native_dir)
            if result.returncode == 0:
                print_success("Docker services started")
            else:
                print_warning("Docker services failed to start — continue manually")

    # Step 5: Create virtual environment
    venv_dir = os.path.join(native_dir, ".venv")
    if os.path.exists(venv_dir):
        print_info(f"Virtual environment already exists at {venv_dir}")
    else:
        if non_interactive or confirm("Create virtual environment?"):
            print_info("Creating virtual environment...")
            ctx.invoke(
                _get_venv_setup_cmd(),
                version=version,
                force=False,
            )

    # Step 6: Clone repositories
    if not skip_repos:
        if non_interactive or confirm("Clone/update repositories?"):
            print_info("Cloning repositories...")
            ctx.invoke(
                _get_repos_cmd(),
                version=version,
                init_mode=True,
            )

    print_success(f"Odoo v{version} environment initialized at {native_dir}")
    print_info(f"Next: odoodev start {version}")


def _get_env_setup_cmd():
    """Lazy import to avoid circular imports."""
    from odoodev.commands.env import env_setup

    return env_setup


def _get_venv_setup_cmd():
    """Lazy import to avoid circular imports."""
    from odoodev.commands.venv import venv_setup

    return venv_setup


def _get_repos_cmd():
    """Lazy import to avoid circular imports."""
    from odoodev.commands.repos import repos

    return repos
