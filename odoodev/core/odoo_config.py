"""Odoo configuration file generation from templates and repo data."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

_GENERATED_CONF_RE = re.compile(r"^odoo_\d{6}\.conf$")


def resolve_config_paths(version_cfg, repos_config: dict | None = None) -> tuple[str, str]:
    """Resolve the odoo.conf template path and the generated-config output dir.

    repos.yaml ``paths.template`` / ``paths.config_dir`` override the defaults
    (``conf_dir/odoo{version}_template.conf`` and ``myconfs_dir``).

    Args:
        version_cfg: VersionConfig of the target version.
        repos_config: Parsed repos.yaml dict (or None/{} when unavailable).

    Returns:
        Tuple of (template_path, config_dir), both ~-expanded.
    """
    paths = (repos_config or {}).get("paths") or {}
    template_path = paths.get("template")
    config_dir = paths.get("config_dir", version_cfg.paths.myconfs_dir)
    config_dir = os.path.expanduser(config_dir)

    if not template_path:
        # Fall back to template in conf dir
        template_path = os.path.join(version_cfg.paths.conf_dir, f"odoo{version_cfg.version}_template.conf")

    return os.path.expanduser(template_path), config_dir


def latest_generated_conf(config_dir: str) -> str | None:
    """Return the newest generated ``odoo_YYMMDD.conf`` in config_dir, or None.

    Filenames sort correctly by date (YYMMDD), so the lexicographic maximum
    is the latest generated config.
    """
    try:
        names = os.listdir(config_dir)
    except OSError:
        return None
    matches = sorted(n for n in names if _GENERATED_CONF_RE.match(n))
    if not matches:
        return None
    return os.path.join(config_dir, matches[-1])


def effective_ports(version_cfg) -> dict:
    """Resolve the ports a version actually uses at runtime.

    Multi-user hosts override the registry defaults per user via the
    version's ``.env`` (``DB_PORT``/``ODOO_PORT``/``GEVENT_PORT``/
    ``MAILPIT_PORT``, e.g. user 2 gets 28069/28432). Consumers such as the
    GUI must match containers and build URLs against these values, not the
    registry defaults. Shared by ``config versions --json`` and
    ``export modules``.
    """
    from odoodev.core.container_backend import read_env_file

    env = read_env_file(version_cfg.paths.native_dir)

    def pick(key: str, default: int) -> int:
        raw = (env.get(key) or "").strip()
        return int(raw) if raw.isdigit() else default

    return {
        "db": pick("DB_PORT", version_cfg.ports.db),
        "odoo": pick("ODOO_PORT", version_cfg.ports.odoo),
        "gevent": pick("GEVENT_PORT", version_cfg.ports.gevent),
        "mailpit": pick("MAILPIT_PORT", version_cfg.ports.mailpit),
    }


def generate_addons_path(
    all_paths: dict[str, list[str]],
    repo_metadata: dict[str, dict],
    home_replacement: str = "$HOME",
) -> str:
    """Generate the addons_path configuration section.

    Sections are output in the order they are first encountered in repos.yaml,
    so any section name (e.g. "DACH", "Design", "Chatbot") is supported.

    Args:
        all_paths: Dict of {repo_key: [list_of_paths]}
        repo_metadata: Dict of {repo_key: {section: str, use: bool}}
        home_replacement: String to use for home directory ('$HOME' or actual path)

    Returns:
        Formatted addons_path value for Odoo config.
    """
    home = os.path.expanduser("~")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"    # Generated on {timestamp}"]

    # Base paths first
    if "base" in all_paths:
        for path in all_paths["base"]:
            formatted = path.replace(home, home_replacement) if home_replacement != home else path
            lines.append(f"    {formatted},")

    # Collect entries preserving section order from repos.yaml
    seen_sections: list[str] = []
    sections: dict[str, list[tuple[str, bool]]] = {}
    for key, paths in all_paths.items():
        if key == "base":
            continue
        meta = repo_metadata.get(key, {})
        section = meta.get("section", "Other")
        use = meta.get("use", True)
        if section not in sections:
            sections[section] = []
            seen_sections.append(section)
        for path in paths:
            formatted = path.replace(home, home_replacement) if home_replacement != home else path
            sections[section].append((formatted, use))

    # Output in repos.yaml encounter order
    for section_name in seen_sections:
        entries = sections[section_name]
        lines.append(f"    # {section_name}")
        for path, use in entries:
            prefix = "    " if use else "    # "
            lines.append(f"{prefix}{path},")

    return "\n".join(lines)


def create_odoo_config(
    template_path: str,
    config_dir: str,
    all_paths: dict[str, list[str]],
    repo_metadata: dict[str, dict],
    config_mode: str = "native",
    native_db_host: str = "localhost",
    native_db_port: int | str = 18432,
    dev_user: str | None = None,
    db_user: str | None = None,
    db_password: str | None = None,
    admin_passwd: str | None = None,
    http_port: int | None = None,
    gevent_port: int | None = None,
) -> str | None:
    """Generate Odoo configuration from template.

    Args:
        template_path: Path to odoo_template.conf
        config_dir: Output directory for generated config
        all_paths: Addon paths per repository
        repo_metadata: Metadata per repository (section, use)
        config_mode: 'native' or 'docker'
        native_db_host: Database host for native mode
        native_db_port: Database port for native mode
        dev_user: Developer username for ${DEV_USER} replacement
        db_user: Database user (overrides template default)
        db_password: Database password (overrides template default)
        admin_passwd: Odoo admin master password (overrides template default)
        http_port: Odoo HTTP port (overrides template default)
        gevent_port: Odoo gevent (longpolling) port (overrides template default)

    Returns:
        Path to generated config file, or None on error.
    """
    try:
        with open(template_path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        logger.error("Cannot read template: %s", e)
        return None

    # Generate addons_path
    home = os.path.expanduser("~")
    if config_mode == "native":
        home_replacement = home  # Use actual paths for native
    else:
        home_replacement = "$HOME"  # Keep $HOME for Docker

    addons_path = generate_addons_path(all_paths, repo_metadata, home_replacement)

    # Replace addons_path in template
    content = re.sub(
        r"addons_path\s*=\s*(\n[^\[]*)?",
        f"addons_path =\n{addons_path}\n",
        content,
        count=1,
    )

    # Replace ${DEV_USER}
    user = dev_user or os.environ.get("DEV_USER", os.environ.get("USER", "odoo"))
    content = content.replace("${DEV_USER}", user)

    # Native mode: replace database config
    if config_mode == "native":
        content = content.replace("$HOME", home)
        content = re.sub(r"db_host\s*=\s*dev-db-\d+", f"db_host = {native_db_host}", content)
        content = re.sub(r"db_host\s*=\s*dev-db", f"db_host = {native_db_host}", content)
        content = re.sub(r"db_port\s*=\s*\S+", f"db_port = {native_db_port}", content)

    # Replace database credentials if provided
    if db_user:
        content = re.sub(r"db_user\s*=\s*\S+", f"db_user = {db_user}", content)
    if db_password:
        content = re.sub(r"db_password\s*=\s*\S+", f"db_password = {db_password}", content)
    if admin_passwd:
        content = re.sub(r"admin_passwd\s*=\s*\S+", f"admin_passwd = {admin_passwd}", content)

    # Replace Odoo runtime ports if provided (overrides template defaults from .env)
    if http_port is not None:
        content = re.sub(r"http_port\s*=\s*\S+", f"http_port = {http_port}", content)
    if gevent_port is not None:
        content = re.sub(r"gevent_port\s*=\s*\S+", f"gevent_port = {gevent_port}", content)

    # Save generated config
    os.makedirs(config_dir, exist_ok=True)
    date_suffix = datetime.now().strftime("%y%m%d")
    output_path = os.path.join(config_dir, f"odoo_{date_suffix}.conf")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Config generated: %s", output_path)
        return output_path
    except OSError as e:
        logger.error("Cannot write config: %s", e)
        return None
