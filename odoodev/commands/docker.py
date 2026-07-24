"""odoodev docker - Local container service management for native development.

Despite the name, this group controls the configured container runtime — Docker
(via docker-compose) or Apple Container (via `container run`). The runtime
defaults to the global config and can be overridden per call with ``--runtime``.
"""

from __future__ import annotations

import os

import click

from odoodev.cli import resolve_version
from odoodev.core.container_backend import (
    RUNTIME_APPLE,
    RUNTIME_DOCKER,
    build_dev_spec,
    diagnose_runtime,
    get_backend,
    read_env_file,
    resolve_runtime,
)
from odoodev.core.version_registry import get_version
from odoodev.output import print_error, print_info, print_success, print_warning

_runtime_option = click.option(
    "--runtime",
    type=click.Choice(["docker", "apple"]),
    default=None,
    help="Container runtime (overrides config). docker | apple",
)


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


def _has_compose_file(version_cfg) -> bool:
    """True if a docker-compose.yml exists for the version (Docker runtime only)."""
    return os.path.exists(os.path.join(version_cfg.paths.native_dir, "docker-compose.yml"))


@click.group()
def docker() -> None:
    """Manage local container services (PostgreSQL) for the configured runtime."""


@docker.command("up")
@click.argument("version", required=False)
@click.option("-d", "--detach", is_flag=True, default=True, help="Run in background (default)")
@_runtime_option
@click.pass_context
def docker_up(ctx: click.Context, version: str | None, detach: bool, runtime: str | None) -> None:
    """Start the local PostgreSQL service."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    rt = resolve_runtime(runtime)

    is_target, source_version = _check_migration_redirect(version)
    if is_target and source_version:
        print_warning(
            f"[MIGRATION] v{version} shares v{source_version}'s PostgreSQL container. Using v{source_version}."
        )
        version = source_version
        version_cfg = get_version(version)

    backend = get_backend(rt)
    if rt == RUNTIME_DOCKER and not _has_compose_file(version_cfg):
        print_error(f"No docker-compose.yml found in {version_cfg.paths.native_dir}")
        print_info(f"Run: odoodev init {version}")
        raise SystemExit(1)

    print_info(f"Starting PostgreSQL for v{version} via {backend.name}...")
    env = read_env_file(version_cfg.paths.native_dir)
    if backend.service_up(version_cfg, env) != 0:
        print_error(f"Failed to start PostgreSQL via {backend.name}")
        raise SystemExit(1)

    from odoodev.core.migration_config import resolve_db_port
    from odoodev.core.prerequisites import wait_for_postgres_ready

    db_port = resolve_db_port(version, version_cfg.ports.db, env)
    if not wait_for_postgres_ready("localhost", db_port, timeout=60):
        print_error(f"PostgreSQL for v{version} did not become ready on port {db_port} within 60s")
        raise SystemExit(1)
    print_success(f"PostgreSQL for v{version} started ({backend.name})")


@docker.command("down")
@click.argument("version", required=False)
@_runtime_option
@click.pass_context
def docker_down(ctx: click.Context, version: str | None, runtime: str | None) -> None:
    """Stop the local PostgreSQL service (persistent data is kept)."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    rt = resolve_runtime(runtime)

    # Warn if this is a source container shared with a migration target.
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

    backend = get_backend(rt)
    print_info(f"Stopping PostgreSQL for v{version} via {backend.name}...")
    env = read_env_file(version_cfg.paths.native_dir)
    if backend.service_down(version_cfg, env) == 0:
        print_success(f"PostgreSQL for v{version} stopped ({backend.name})")
    else:
        print_error(f"Failed to stop PostgreSQL via {backend.name}")
        raise SystemExit(1)


@docker.command("status")
@click.argument("version", required=False)
@_runtime_option
@click.pass_context
def docker_status(ctx: click.Context, version: str | None, runtime: str | None) -> None:
    """Show the local PostgreSQL service status."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    rt = resolve_runtime(runtime)

    if rt == RUNTIME_DOCKER and not _has_compose_file(version_cfg):
        print_warning(f"No docker-compose.yml found in {version_cfg.paths.native_dir}")
        return

    # Status must not mutate state (no API-server auto-start) — report a
    # non-ready runtime with its concrete remedy instead of a raw CLI error.
    diag = diagnose_runtime(version=version, runtime=rt)
    if not diag.ready:
        if diag.problem:
            print_warning(diag.problem)
        for hint in diag.hints:
            print_info(hint)
        raise SystemExit(1)

    backend = get_backend(rt)
    env = read_env_file(version_cfg.paths.native_dir)
    # Apple Container's `container ls -a` lists ALL containers unfiltered — name
    # the one this version expects so the output is interpretable.
    if rt == RUNTIME_APPLE:
        print_info(f"Expected dev PostgreSQL container: {build_dev_spec(version_cfg, env).container_name}")
    backend.service_status(version_cfg, env)


@docker.command("logs")
@click.argument("version", required=False)
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
@click.option("-n", "--tail", type=int, default=100, help="Number of lines to show")
@_runtime_option
@click.pass_context
def docker_logs(ctx: click.Context, version: str | None, follow: bool, tail: int, runtime: str | None) -> None:
    """View the local PostgreSQL service logs."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    rt = resolve_runtime(runtime)

    backend = get_backend(rt)
    env = read_env_file(version_cfg.paths.native_dir)
    backend.service_logs(version_cfg, env, follow=follow, tail=tail)
