"""Migration mode configuration for cross-version database migrations.

Manages migration groups that allow sharing PostgreSQL containers and
filestore paths between Odoo versions during database migrations.

Config is persisted at ~/.config/odoodev/migration.yaml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Module-level cache to avoid repeated disk reads
_cached_config: MigrationConfig | None = None


@dataclass(frozen=True)
class MigrationGroup:
    """A migration group linking source and target Odoo versions.

    When active, the target version uses the source version's PostgreSQL
    container (port) and a shared filestore path.
    """

    name: str
    from_version: str
    to_version: str
    pg_version: str
    shared_db_port: int
    shared_filestore_base: str
    created_at: str


@dataclass(frozen=True)
class MigrationConfig:
    """Top-level migration configuration with optional active group."""

    active: str | None
    groups: dict[str, MigrationGroup]


def get_migration_config_path() -> Path:
    """Return path to the migration config YAML file."""
    return Path.home() / ".config" / "odoodev" / "migration.yaml"


def load_migration_config() -> MigrationConfig:
    """Load migration configuration from YAML file.

    Returns defaults (no groups, no active) if file does not exist.
    Uses module-level cache to avoid repeated disk reads.

    Returns:
        MigrationConfig with loaded or default values.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    config_path = get_migration_config_path()
    if not config_path.is_file():
        _cached_config = MigrationConfig(active=None, groups={})
        return _cached_config

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        _cached_config = MigrationConfig(active=None, groups={})
        return _cached_config

    groups: dict[str, MigrationGroup] = {}
    for name, group_data in data.get("groups", {}).items():
        groups[name] = MigrationGroup(
            name=name,
            from_version=str(group_data["from_version"]),
            to_version=str(group_data["to_version"]),
            pg_version=group_data["pg_version"],
            shared_db_port=int(group_data["shared_db_port"]),
            shared_filestore_base=group_data["shared_filestore_base"],
            created_at=group_data.get("created_at", ""),
        )

    _cached_config = MigrationConfig(
        active=data.get("active"),
        groups=groups,
    )
    return _cached_config


def save_migration_config(config: MigrationConfig) -> Path:
    """Save migration configuration to YAML file.

    Creates the config directory if it does not exist.

    Args:
        config: MigrationConfig to persist.

    Returns:
        Path to the saved config file.
    """
    global _cached_config
    config_path = get_migration_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "active": config.active,
        "groups": {},
    }
    for name, group in config.groups.items():
        data["groups"][name] = {
            "from_version": group.from_version,
            "to_version": group.to_version,
            "pg_version": group.pg_version,
            "shared_db_port": group.shared_db_port,
            "shared_filestore_base": group.shared_filestore_base,
            "created_at": group.created_at,
        }

    with open(config_path, "w", encoding="utf-8") as f:
        f.write("# Managed by: odoodev migrate — do not edit manually\n")
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    _cached_config = config
    return config_path


def get_active_group() -> MigrationGroup | None:
    """Return the currently active migration group, or None.

    Safe to call from any context — returns None on any error.
    """
    try:
        config = load_migration_config()
        if config.active and config.active in config.groups:
            return config.groups[config.active]
    except Exception:  # noqa: S110 — intentional safety guard, must never break normal operation
        pass
    return None


def create_migration_group(
    from_version: str,
    to_version: str,
    pg_version: str,
    shared_db_port: int,
    shared_filestore_base: str,
    name: str | None = None,
) -> MigrationGroup:
    """Create a new migration group and persist it.

    Args:
        from_version: Source Odoo version (e.g., "16").
        to_version: Target Odoo version (e.g., "18").
        pg_version: PostgreSQL image tag to use.
        shared_db_port: Shared database port (source version's port).
        shared_filestore_base: Base path for shared filestore.
        name: Optional group name. Defaults to "{from}-to-{to}".

    Returns:
        The created MigrationGroup.

    Raises:
        ValueError: If a group with the same name already exists.
    """
    if name is None:
        name = f"{from_version}-to-{to_version}"

    config = load_migration_config()
    if name in config.groups:
        raise ValueError(f"Migration group '{name}' already exists")

    group = MigrationGroup(
        name=name,
        from_version=from_version,
        to_version=to_version,
        pg_version=pg_version,
        shared_db_port=shared_db_port,
        shared_filestore_base=shared_filestore_base,
        created_at=datetime.now(UTC).isoformat(),
    )

    new_groups = dict(config.groups)
    new_groups[name] = group
    new_config = MigrationConfig(active=config.active, groups=new_groups)
    save_migration_config(new_config)

    # Ensure shared filestore directory exists
    filestore_dir = os.path.join(os.path.expanduser(shared_filestore_base), "filestore")
    os.makedirs(filestore_dir, exist_ok=True)

    return group


def activate_migration(name: str) -> MigrationGroup:
    """Activate a migration group by name.

    Args:
        name: Name of the migration group to activate.

    Returns:
        The activated MigrationGroup.

    Raises:
        KeyError: If the group does not exist.
    """
    config = load_migration_config()
    if name not in config.groups:
        available = ", ".join(sorted(config.groups.keys())) or "(none)"
        raise KeyError(f"Migration group '{name}' not found. Available: {available}")

    new_config = MigrationConfig(active=name, groups=config.groups)
    save_migration_config(new_config)
    return config.groups[name]


def deactivate_migration() -> None:
    """Deactivate the currently active migration group."""
    config = load_migration_config()
    new_config = MigrationConfig(active=None, groups=config.groups)
    save_migration_config(new_config)


def remove_migration_group(name: str, force: bool = False) -> None:
    """Remove a migration group definition.

    Args:
        name: Name of the migration group to remove.
        force: If True, deactivate before removing if active.

    Raises:
        KeyError: If the group does not exist.
        ValueError: If the group is active and force is False.
    """
    config = load_migration_config()
    if name not in config.groups:
        available = ", ".join(sorted(config.groups.keys())) or "(none)"
        raise KeyError(f"Migration group '{name}' not found. Available: {available}")

    if config.active == name and not force:
        raise ValueError(
            f"Migration group '{name}' is currently active. "
            "Deactivate first with 'odoodev migrate deactivate' or use --yes to force."
        )

    active = config.active if config.active != name else None
    new_groups = {k: v for k, v in config.groups.items() if k != name}
    new_config = MigrationConfig(active=active, groups=new_groups)
    save_migration_config(new_config)


def clear_migration_cache() -> None:
    """Clear the module-level config cache. Useful for testing."""
    global _cached_config
    _cached_config = None
