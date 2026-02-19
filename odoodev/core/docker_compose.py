"""Docker Compose operations for native Odoo development."""

from __future__ import annotations

import subprocess


def render_compose(version_cfg, user: str, docker_platform: str) -> str:
    """Render docker-compose.yml from Jinja2 template.

    Args:
        version_cfg: VersionConfig for the target version
        user: Username for container naming
        docker_platform: Docker platform string (e.g., 'linux/arm64')

    Returns:
        Rendered docker-compose.yml content
    """
    from jinja2 import Environment, PackageLoader

    jinja_env = Environment(
        loader=PackageLoader("odoodev", "templates"),
        keep_trailing_newline=True,
    )
    template = jinja_env.get_template("docker-compose.yml.j2")
    return template.render(
        version=version_cfg.version,
        user=user,
        docker_platform=docker_platform,
        postgres_version=version_cfg.postgres,
        db_port=version_cfg.ports.db,
        mailpit_port=version_cfg.ports.mailpit,
        smtp_port=version_cfg.ports.smtp,
    )


def compose_up(compose_dir: str, detach: bool = True) -> int:
    """Start Docker Compose services.

    Returns:
        Process return code.
    """
    args = ["docker", "compose", "up"]
    if detach:
        args.append("-d")
    result = subprocess.run(args, cwd=compose_dir)
    return result.returncode


def compose_down(compose_dir: str) -> int:
    """Stop Docker Compose services."""
    result = subprocess.run(["docker", "compose", "down"], cwd=compose_dir)
    return result.returncode


def compose_ps(compose_dir: str) -> int:
    """Show Docker Compose service status."""
    result = subprocess.run(["docker", "compose", "ps"], cwd=compose_dir)
    return result.returncode


def compose_logs(compose_dir: str, follow: bool = False, tail: int = 100) -> int:
    """View Docker Compose logs."""
    args = ["docker", "compose", "logs", f"--tail={tail}"]
    if follow:
        args.append("-f")
    result = subprocess.run(args, cwd=compose_dir)
    return result.returncode
