"""odoodev docker - Docker service management for native development."""

from __future__ import annotations

import os
import subprocess

import click

from odoodev.cli import resolve_version
from odoodev.core.version_registry import get_version
from odoodev.output import print_error, print_info, print_success, print_warning


def _get_compose_dir(version_cfg) -> str:
    """Get the directory containing docker-compose.yml for the version."""
    return version_cfg.paths.native_dir


def _run_compose(compose_dir: str, args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run docker compose command in the given directory."""
    cmd = ["docker", "compose"] + args
    return subprocess.run(
        cmd,
        cwd=compose_dir,
        capture_output=capture,
        text=True,
    )


@click.group()
def docker() -> None:
    """Manage Docker services (PostgreSQL, Mailpit)."""


@docker.command("up")
@click.argument("version", required=False)
@click.option("-d", "--detach", is_flag=True, default=True, help="Run in background (default)")
@click.pass_context
def docker_up(ctx: click.Context, version: str | None, detach: bool) -> None:
    """Start Docker services."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    compose_dir = _get_compose_dir(version_cfg)

    if not os.path.exists(os.path.join(compose_dir, "docker-compose.yml")):
        print_error(f"No docker-compose.yml found in {compose_dir}")
        print_info(f"Run: odoodev init {version}")
        raise SystemExit(1)

    print_info(f"Starting Docker services for v{version}...")
    args = ["up"]
    if detach:
        args.append("-d")
    result = _run_compose(compose_dir, args)
    if result.returncode == 0:
        print_success(f"Docker services for v{version} started")
    else:
        print_error("Failed to start Docker services")
        raise SystemExit(result.returncode)


@docker.command("down")
@click.argument("version", required=False)
@click.pass_context
def docker_down(ctx: click.Context, version: str | None) -> None:
    """Stop Docker services."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    compose_dir = _get_compose_dir(version_cfg)

    print_info(f"Stopping Docker services for v{version}...")
    result = _run_compose(compose_dir, ["down"])
    if result.returncode == 0:
        print_success(f"Docker services for v{version} stopped")
    else:
        print_error("Failed to stop Docker services")
        raise SystemExit(result.returncode)


@docker.command("status")
@click.argument("version", required=False)
@click.pass_context
def docker_status(ctx: click.Context, version: str | None) -> None:
    """Show Docker service status."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    compose_dir = _get_compose_dir(version_cfg)

    if not os.path.exists(os.path.join(compose_dir, "docker-compose.yml")):
        print_warning(f"No docker-compose.yml found in {compose_dir}")
        return

    _run_compose(compose_dir, ["ps"])


@docker.command("logs")
@click.argument("version", required=False)
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
@click.option("-n", "--tail", type=int, default=100, help="Number of lines to show")
@click.pass_context
def docker_logs(ctx: click.Context, version: str | None, follow: bool, tail: int) -> None:
    """View Docker service logs."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    compose_dir = _get_compose_dir(version_cfg)

    args = ["logs", f"--tail={tail}"]
    if follow:
        args.append("-f")
    _run_compose(compose_dir, args)
