"""odoodev env - Environment (.env) file management."""

from __future__ import annotations

import os

import click
from dotenv import dotenv_values
from jinja2 import Environment, PackageLoader

from odoodev.cli import resolve_version
from odoodev.core.environment import detect_docker_platform, detect_os, detect_user
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import confirm, print_error, print_info, print_success, print_table, print_warning


def _get_template_env() -> Environment:
    """Get Jinja2 environment for templates."""
    return Environment(
        loader=PackageLoader("odoodev", "templates"),
        keep_trailing_newline=True,
    )


def _render_env_template(version_cfg, user: str, platform_os: str, docker_platform: str) -> str:
    """Render .env template with version-specific values."""
    from odoodev.core.global_config import load_global_config

    jinja_env = _get_template_env()
    template = jinja_env.get_template("env.template.j2")
    global_cfg = load_global_config()
    return template.render(
        version=version_cfg.version,
        env_name=version_cfg.env_name,
        platform=platform_os,
        dev_user=user,
        docker_platform=docker_platform,
        db_port=version_cfg.ports.db,
        odoo_port=version_cfg.ports.odoo,
        gevent_port=version_cfg.ports.gevent,
        mailpit_port=version_cfg.ports.mailpit,
        smtp_port=version_cfg.ports.smtp,
        postgres_version=version_cfg.postgres,
        db_user=global_cfg.database.user,
        db_password=global_cfg.database.password,
    )


@click.group()
def env() -> None:
    """Manage .env environment files."""


@env.command("setup")
@click.argument("version", required=False)
@click.option("--non-interactive", is_flag=True, help="Use defaults without prompting")
@click.pass_context
def env_setup(ctx: click.Context, version: str | None, non_interactive: bool) -> None:
    """Create or update .env file for a version."""
    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)
    env_dir = version_cfg.paths.native_dir
    env_file = os.path.join(env_dir, ".env")

    if os.path.exists(env_file) and not non_interactive:
        if not confirm(f".env already exists at {env_file}. Overwrite?", default=False):
            print_info("Aborted.")
            return

    # Detect platform values
    platform_os = detect_os()
    docker_platform = detect_docker_platform()
    user = detect_user()

    content = _render_env_template(version_cfg, user, platform_os, docker_platform)

    if not non_interactive:
        print_info(f"Creating .env for Odoo v{version}")
        print_table(
            "Detected Configuration",
            {
                "Platform": platform_os,
                "Docker Platform": docker_platform,
                "User": user,
                "DB Port": str(version_cfg.ports.db),
                "Odoo Port": str(version_cfg.ports.odoo),
                "Gevent Port": str(version_cfg.ports.gevent),
            },
        )
        if not confirm("Accept these defaults?"):
            print_info("Use --non-interactive to skip prompts or edit .env manually after creation.")
            # Still create with defaults, user can edit
            pass

    os.makedirs(env_dir, exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as f:
        f.write(content)
    print_success(f".env created at {env_file}")


@env.command("check")
@click.argument("version", required=False)
@click.pass_context
def env_check(ctx: click.Context, version: str | None) -> None:
    """Check if .env file exists and is complete."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_file = os.path.join(version_cfg.paths.native_dir, ".env")

    if not os.path.exists(env_file):
        print_error(f"No .env file found at {env_file}")
        print_info(f"Run: odoodev env setup {version}")
        raise SystemExit(1)

    values = dotenv_values(env_file)
    required_keys = [
        "ENV_NAME",
        "ODOO_VERSION",
        "PLATFORM",
        "DEV_USER",
        "DB_PORT",
        "PGUSER",
        "PGPASSWORD",
        "ODOO_PORT",
        "GEVENT_PORT",
        "POSTGRES_VERSION",
        "DOCKER_PLATFORM",
    ]

    missing = [k for k in required_keys if k not in values or not values[k]]
    if missing:
        print_warning(f"Missing variables in .env: {', '.join(missing)}")
        print_info(f"Run: odoodev env setup {version}")
    else:
        print_success(f".env is complete ({len(values)} variables)")


@env.command("show")
@click.argument("version", required=False)
@click.pass_context
def env_show(ctx: click.Context, version: str | None) -> None:
    """Display current .env configuration."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    env_file = os.path.join(version_cfg.paths.native_dir, ".env")

    if not os.path.exists(env_file):
        print_error(f"No .env file found at {env_file}")
        raise SystemExit(1)

    values = dotenv_values(env_file)
    print_table(f"Environment v{version} ({env_file})", dict(values))


@env.command("dir")
@click.argument("version", required=False)
@click.pass_context
def env_dir(ctx: click.Context, version: str | None) -> None:
    """Print the native environment directory path."""
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    click.echo(version_cfg.paths.native_dir)
