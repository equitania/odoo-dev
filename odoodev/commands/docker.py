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


def _check_migration_redirect(version: str) -> tuple[bool, str | None]:
    """Check if the version is a migration target and should redirect to source.

    Returns:
        Tuple of (is_target, source_version).
    """
    try:
        from odoodev.core.migration_config import get_active_group

        group = get_active_group()
        if group and group.to_version == version:
            return True, group.from_version
    except Exception:  # noqa: S110 — intentional safety guard
        pass
    return False, None


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

    is_target, source_version = _check_migration_redirect(version)
    if is_target:
        print_warning(
            f"[MIGRATION] v{version} shares v{source_version}'s PostgreSQL container. "
            f"Use: odoodev docker up {source_version}"
        )
        source_cfg = get_version(source_version)
        compose_dir = _get_compose_dir(source_cfg)
        if not os.path.exists(os.path.join(compose_dir, "docker-compose.yml")):
            print_error(f"No docker-compose.yml found in {compose_dir}")
            raise SystemExit(1)
        version = source_version

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

    # Warn if this is a source container used by a migration target
    try:
        from odoodev.core.migration_config import get_active_group

        group = get_active_group()
        if group and group.from_version == version:
            print_warning(
                f"[MIGRATION] v{version}'s PostgreSQL container is shared with "
                f"v{group.to_version} (active migration: {group.name}). "
                f"Stopping it will disconnect v{group.to_version}."
            )
    except Exception:  # noqa: S110 — intentional safety guard
        pass

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
