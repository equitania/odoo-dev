"""Odoo configuration file generation from templates and repo data."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# Section order for addons_path generation
SECTION_ORDER = [
    "Odoo",
    "OCA",
    "Enterprise",
    "Syscoon",
    "3rd-party",
    "Equitania",
    "Customer",
    "Other",
]


def generate_addons_path(
    all_paths: dict[str, list[str]],
    repo_metadata: dict[str, dict],
    home_replacement: str = "$HOME",
) -> str:
    """Generate the addons_path configuration section.

    Args:
        all_paths: Dict of {repo_key: [list_of_paths]}
        repo_metadata: Dict of {repo_key: {section: str, commented: bool}}
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

    # Group by section
    sections: dict[str, list[tuple[str, bool]]] = {}
    for key, paths in all_paths.items():
        if key == "base":
            continue
        meta = repo_metadata.get(key, {})
        section = meta.get("section", "Other")
        commented = meta.get("commented", False)
        if section not in sections:
            sections[section] = []
        for path in paths:
            formatted = path.replace(home, home_replacement) if home_replacement != home else path
            sections[section].append((formatted, commented))

    # Output in section order
    for section_name in SECTION_ORDER:
        if section_name not in sections:
            continue
        entries = sections[section_name]
        lines.append(f"    # {section_name}")
        for path, commented in entries:
            prefix = "    # " if commented else "    "
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
) -> str | None:
    """Generate Odoo configuration from template.

    Args:
        template_path: Path to odoo_template.conf
        config_dir: Output directory for generated config
        all_paths: Addon paths per repository
        repo_metadata: Metadata per repository (section, commented)
        config_mode: 'native' or 'docker'
        native_db_host: Database host for native mode
        native_db_port: Database port for native mode
        dev_user: Developer username for ${DEV_USER} replacement
        db_user: Database user (overrides template default)
        db_password: Database password (overrides template default)
        admin_passwd: Odoo admin master password (overrides template default)

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
