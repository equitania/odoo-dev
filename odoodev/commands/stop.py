"""odoodev stop - Stop Odoo server and Docker services."""

from __future__ import annotations

import subprocess

import click

from odoodev.cli import resolve_version
from odoodev.core.process_manager import find_odoo_process, stop_process
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import print_error, print_info, print_success, print_warning


@click.command()
@click.argument("version", required=False)
@click.option("--keep-docker", is_flag=True, help="Keep Docker services running (PostgreSQL, Mailpit)")
@click.option("--force", is_flag=True, help="Force kill without graceful shutdown")
@click.pass_context
def stop(ctx: click.Context, version: str | None, keep_docker: bool, force: bool) -> None:
    """Stop Odoo server and Docker services for the given version."""
    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)

    odoo_port = version_cfg.ports.odoo
    native_dir = version_cfg.paths.native_dir

    # --- Stop Odoo process ---
    pids = find_odoo_process(odoo_port)
    if not pids:
        print_warning(f"No Odoo process found on port {odoo_port} (v{version})")
    else:
        stopped_all = True
        for pid in pids:
            print_info(f"Stopping Odoo process PID {pid} on port {odoo_port}...")
            ok = stop_process(pid, timeout=5, force=force)
            if ok:
                print_success(f"Odoo process {pid} stopped")
            else:
                print_error(f"Failed to stop process {pid}")
                stopped_all = False

        if not stopped_all:
            raise SystemExit(1)

    # --- Stop Docker services ---
    if keep_docker:
        print_info("Keeping Docker services running (--keep-docker)")
    else:
        print_info(f"Stopping Docker services for v{version}...")
        result = subprocess.run(
            ["docker", "compose", "down"],
            cwd=native_dir,
        )
        if result.returncode == 0:
            print_success(f"Docker services for v{version} stopped")
        else:
            print_warning("docker compose down returned a non-zero exit code")
