"""odoodev config - Global configuration and version listing."""

from __future__ import annotations

import dataclasses
import os
import subprocess

import click

from odoodev.core.environment import detect_arch, detect_docker_platform, detect_os, detect_shell, detect_user
from odoodev.core.version_registry import available_versions, load_versions
from odoodev.output import print_header, print_info, print_success, print_table, print_version_table, print_warning

_SETTABLE_KEYS = ("base_dir", "language", "db.user", "db.password", "active_versions", "container_runtime")


def _parse_and_validate(key: str, raw_value: str) -> str | list[str]:
    """Parse and validate a raw CLI value for a settable config key.

    Raises:
        click.UsageError: On unknown keys or invalid values.
    """
    if key == "language":
        from odoodev.i18n import SUPPORTED

        if raw_value not in SUPPORTED:
            raise click.UsageError(f"Unsupported language '{raw_value}'. Supported: {', '.join(SUPPORTED)}")
        return raw_value
    if key == "active_versions":
        requested = [v.strip() for v in raw_value.split(",") if v.strip()]
        known = set(available_versions())
        unknown = [v for v in requested if v not in known]
        if not requested or unknown:
            raise click.UsageError(
                f"Invalid versions: {', '.join(unknown) or '(empty)'}. Known: {', '.join(sorted(known))}"
            )
        return requested
    if key == "container_runtime":
        from odoodev.core.container_backend import RUNTIME_APPLE, VALID_RUNTIMES, apple_runtime_supported

        if raw_value not in VALID_RUNTIMES:
            raise click.UsageError(f"Invalid container_runtime '{raw_value}'. Valid: {', '.join(VALID_RUNTIMES)}")
        if raw_value == RUNTIME_APPLE and not apple_runtime_supported():
            print_warning(
                "Apple Container is only supported on macOS; this setting has no effect on this machine "
                "until it is used on one."
            )
        return raw_value
    if key in ("base_dir", "db.user", "db.password"):
        if not raw_value.strip():
            raise click.UsageError(f"Value for '{key}' must not be empty")
        if key == "db.password" and ("\n" in raw_value or "\r" in raw_value):
            raise click.UsageError("Password must not contain newlines")
        return raw_value
    raise click.UsageError(f"Unknown key '{key}'. Valid keys: {', '.join(_SETTABLE_KEYS)}")


@click.group()
def config() -> None:
    """Global configuration and available versions."""


@config.command("versions")
@click.option("--plain", is_flag=True, help="Plain output (one version per line, for scripts)")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
def config_versions(plain: bool, as_json: bool) -> None:
    """List all available Odoo versions with their configuration."""
    if plain and as_json:
        raise click.UsageError("--plain and --json are mutually exclusive")
    if plain:
        for v in available_versions():
            click.echo(v)
        return
    versions = load_versions()
    if as_json:
        import json
        import sys

        payload = {
            v: {
                "python": cfg.python,
                "postgres": cfg.postgres,
                "ports": {
                    "db": cfg.ports.db,
                    "odoo": cfg.ports.odoo,
                    "gevent": cfg.ports.gevent,
                    "mailpit": cfg.ports.mailpit,
                },
                "base": cfg.paths.base,
            }
            for v, cfg in versions.items()
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        return
    print_version_table(versions)


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a global configuration value.

    \b
    Keys:
        base_dir         Base directory for all version trees (e.g. ~/gitbase)
        language         CLI language (en, de)
        db.user          PostgreSQL user
        db.password      PostgreSQL password
        active_versions  Comma-separated list, e.g. 16,17,18,19
        container_runtime  Container runtime for PostgreSQL (docker, apple)
    """
    from odoodev.core.global_config import load_global_config, save_global_config

    parsed = _parse_and_validate(key, value)
    cfg = load_global_config()

    if key == "base_dir":
        updated = dataclasses.replace(cfg, base_dir=str(parsed))
    elif key == "language":
        updated = dataclasses.replace(cfg, cli=dataclasses.replace(cfg.cli, language=str(parsed)))
    elif key == "db.user":
        updated = dataclasses.replace(cfg, database=dataclasses.replace(cfg.database, user=str(parsed)))
    elif key == "db.password":
        updated = dataclasses.replace(cfg, database=dataclasses.replace(cfg.database, password=str(parsed)))
    elif key == "container_runtime":
        updated = dataclasses.replace(cfg, container_runtime=str(parsed))
    else:  # active_versions — _parse_and_validate already rejected unknown keys
        updated = dataclasses.replace(cfg, active_versions=list(parsed))

    path = save_global_config(updated)

    display = "********" if key == "db.password" else parsed
    print_success(f"Set {key} = {display}")
    print_info(f"Config file: {path}")


@config.command("edit")
def config_edit() -> None:
    """Open the global config file in $EDITOR (creates defaults if missing)."""
    from odoodev.core.global_config import config_exists, get_config_path, load_global_config, save_global_config

    config_path = get_config_path()
    if not config_exists():
        save_global_config(load_global_config())
        print_info(f"Created default config at {config_path}")

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    result = subprocess.run([editor, str(config_path)])  # noqa: S603 — editor from user environment
    if result.returncode != 0:
        print_warning(f"Editor exited with code {result.returncode}")


@config.command("show")
def config_show() -> None:
    """Show current platform, global config, and environment information."""
    from odoodev.core.global_config import config_exists, get_config_path, load_global_config

    print_header("odoodev Environment", "Platform & configuration details")

    info = {
        "OS": detect_os(),
        "Architecture": detect_arch(),
        "Docker Platform": detect_docker_platform(),
        "Shell": detect_shell(),
        "User": detect_user(),
    }
    print_table("Platform", info)

    # Global configuration
    global_cfg = load_global_config()
    config_info = {
        "Config File": str(get_config_path()),
        "Status": "Custom" if config_exists() else "Defaults (no config file)",
        "Base Directory": global_cfg.base_dir,
        "Active Versions": ", ".join(f"v{v}" for v in global_cfg.active_versions),
        "DB User": global_cfg.database.user,
        "Container Runtime": global_cfg.container_runtime,
    }
    print_table("Global Configuration", config_info)

    versions = load_versions()
    print_version_table(versions)
