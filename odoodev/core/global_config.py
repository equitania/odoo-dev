"""Global configuration management for odoodev.

Handles loading/saving of ~/.config/odoodev/config.yaml with defaults
for base directory, database credentials, and active versions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_BASE_DIR = "~/gitbase"
DEFAULT_DB_USER = "ownerp"
DEFAULT_DB_PASSWORD = "CHANGE_AT_FIRST"
DEFAULT_ACTIVE_VERSIONS = ["16", "17", "18", "19"]
DEFAULT_LANGUAGE = "en"
# Odoo res.users login for XML-RPC module actions (TUI export/update/cleanup,
# `odoodev export modules`). Dev-database convention — NOT the PostgreSQL login.
DEFAULT_ODOO_LOGIN_USERNAME = "admin"
DEFAULT_ODOO_LOGIN_PASSWORD = "admin"  # noqa: S105 — dev-tool placeholder, matches xmlrpc_client default
# Container runtime for the local PostgreSQL service: "docker" or "apple"
# (Apple Container — github.com/apple/container, macOS 26+). Docker is the
# default so existing setups keep their behaviour unchanged.
DEFAULT_CONTAINER_RUNTIME = "docker"

# Module-level cache to avoid repeated disk reads
_cached_config: GlobalConfig | None = None


@dataclass(frozen=True)
class DatabaseConfig:
    """Database credential configuration."""

    user: str = DEFAULT_DB_USER
    password: str = DEFAULT_DB_PASSWORD


@dataclass(frozen=True)
class CliConfig:
    """User-interface configuration for the CLI itself."""

    language: str = DEFAULT_LANGUAGE


@dataclass(frozen=True)
class OdooLoginConfig:
    """Odoo XML-RPC login for module actions (export/update-list/cleanup/hot-update).

    This is the res.users account of the local dev instance — distinct from
    both the PostgreSQL credentials (DatabaseConfig) and the Odoo master
    password (admin_passwd in odoo.conf).
    """

    username: str = DEFAULT_ODOO_LOGIN_USERNAME
    password: str = DEFAULT_ODOO_LOGIN_PASSWORD


@dataclass(frozen=True)
class GlobalConfig:
    """Global odoodev configuration stored in ~/.config/odoodev/config.yaml."""

    base_dir: str = DEFAULT_BASE_DIR
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    cli: CliConfig = field(default_factory=CliConfig)
    odoo_login: OdooLoginConfig = field(default_factory=OdooLoginConfig)
    active_versions: list[str] = field(default_factory=lambda: list(DEFAULT_ACTIVE_VERSIONS))
    container_runtime: str = DEFAULT_CONTAINER_RUNTIME

    @property
    def base_dir_expanded(self) -> str:
        """Return base_dir with ~ expanded to full path."""
        return os.path.expanduser(self.base_dir)


def get_config_dir() -> Path:
    """Return the odoodev configuration directory."""
    return Path.home() / ".config" / "odoodev"


def get_config_path() -> Path:
    """Return the path to the global config.yaml."""
    return get_config_dir() / "config.yaml"


def config_exists() -> bool:
    """Check if a global config.yaml exists."""
    return get_config_path().is_file()


def load_global_config() -> GlobalConfig:
    """Load global configuration from config.yaml.

    Returns defaults if no config file exists. Uses module-level cache
    to avoid repeated disk reads within the same process.

    Returns:
        GlobalConfig with loaded or default values.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    config_path = get_config_path()
    if not config_path.is_file():
        _cached_config = GlobalConfig()
        return _cached_config

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        _cached_config = GlobalConfig()
        return _cached_config

    db_data = data.get("database", {})
    db_config = DatabaseConfig(
        user=db_data.get("user", DEFAULT_DB_USER),
        password=db_data.get("password", DEFAULT_DB_PASSWORD),
    )

    cli_data = data.get("cli", {})
    cli_config = CliConfig(language=cli_data.get("language", DEFAULT_LANGUAGE))

    login_data = data.get("odoo_login", {})
    odoo_login = OdooLoginConfig(
        username=login_data.get("username", DEFAULT_ODOO_LOGIN_USERNAME),
        password=login_data.get("password", DEFAULT_ODOO_LOGIN_PASSWORD),
    )

    _cached_config = GlobalConfig(
        base_dir=data.get("base_dir", DEFAULT_BASE_DIR),
        database=db_config,
        cli=cli_config,
        odoo_login=odoo_login,
        active_versions=data.get("active_versions", list(DEFAULT_ACTIVE_VERSIONS)),
        container_runtime=data.get("container_runtime", DEFAULT_CONTAINER_RUNTIME),
    )
    return _cached_config


def save_global_config(config: GlobalConfig) -> Path:
    """Save global configuration to config.yaml.

    Creates the config directory if it doesn't exist.

    Args:
        config: GlobalConfig to persist.

    Returns:
        Path to the saved config file.
    """
    global _cached_config
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    data = {
        "base_dir": config.base_dir,
        "database": {
            "user": config.database.user,
            "password": config.database.password,
        },
        "cli": {
            "language": config.cli.language,
        },
        "odoo_login": {
            "username": config.odoo_login.username,
            "password": config.odoo_login.password,
        },
        "active_versions": config.active_versions,
        "container_runtime": config.container_runtime,
    }

    # 0o600: config.yaml contains the database password in plaintext
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# Generated by: odoodev setup\n")
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Update cache
    _cached_config = config
    return config_path


def clear_config_cache() -> None:
    """Clear the module-level config cache. Useful for testing."""
    global _cached_config
    _cached_config = None


def get_odoo_login_credentials() -> tuple[str, str]:
    """Return the stored Odoo XML-RPC login as (username, password)."""
    cfg = load_global_config()
    return cfg.odoo_login.username, cfg.odoo_login.password


def save_odoo_login_credentials(username: str, password: str) -> Path:
    """Persist the Odoo XML-RPC login in the global config (0600 file)."""
    import dataclasses

    cfg = load_global_config()
    updated = dataclasses.replace(cfg, odoo_login=OdooLoginConfig(username=username, password=password))
    return save_global_config(updated)
