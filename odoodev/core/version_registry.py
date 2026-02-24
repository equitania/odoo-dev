"""Version registry: loads and validates version configurations from versions.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PortConfig:
    """Port configuration for a specific Odoo version."""

    db: int
    odoo: int
    gevent: int
    mailpit: int
    smtp: int


@dataclass(frozen=True)
class PathConfig:
    """Path configuration for a specific Odoo version."""

    base: str
    server_subdir: str
    dev_subdir: str
    native_subdir: str
    conf_subdir: str

    @property
    def base_expanded(self) -> str:
        """Return base path with ~ expanded."""
        return os.path.expanduser(self.base)

    @property
    def server_dir(self) -> str:
        """Full path to Odoo server directory."""
        return os.path.join(self.base_expanded, self.server_subdir)

    @property
    def dev_dir(self) -> str:
        """Full path to development directory."""
        return os.path.join(self.base_expanded, self.dev_subdir)

    @property
    def native_dir(self) -> str:
        """Full path to native development directory."""
        return os.path.join(self.dev_dir, self.native_subdir)

    @property
    def conf_dir(self) -> str:
        """Full path to configuration directory."""
        return os.path.join(self.dev_dir, self.conf_subdir)

    @property
    def myconfs_dir(self) -> str:
        """Full path to myconfs directory (generated configs)."""
        return os.path.join(self.base_expanded, "myconfs")


@dataclass(frozen=True)
class GitConfig:
    """Git configuration for a specific Odoo version."""

    server_url: str
    branch: str


@dataclass(frozen=True)
class VersionConfig:
    """Complete configuration for a specific Odoo version."""

    version: str
    python: str
    postgres: str
    ports: PortConfig
    paths: PathConfig
    git: GitConfig

    @property
    def env_name(self) -> str:
        """Default environment name."""
        return f"dev{self.version}_native"

    @property
    def version_prefix(self) -> str:
        """Version prefix for naming (e.g., 'v18')."""
        return f"v{self.version}"


def _get_bundled_versions_path() -> Path:
    """Return path to the bundled versions.yaml file."""
    return Path(__file__).parent.parent / "data" / "versions.yaml"


def _get_user_override_path() -> Path:
    """Return path to user override file."""
    return Path.home() / ".config" / "odoodev" / "versions-override.yaml"


def _parse_version(version: str, data: dict) -> VersionConfig:
    """Parse a single version entry from YAML data into VersionConfig."""
    return VersionConfig(
        version=version,
        python=data["python"],
        postgres=data["postgres"],
        ports=PortConfig(**data["ports"]),
        paths=PathConfig(**data["paths"]),
        git=GitConfig(**data["git"]),
    )


def _apply_global_base_dir(
    versions: dict[str, VersionConfig],
    overridden_versions: set[str] | None = None,
) -> dict[str, VersionConfig]:
    """Rebase version paths if global config has a custom base_dir.

    Only rebases versions whose base path still matches the default ~/gitbase pattern.
    Versions with explicit overrides (from versions-override.yaml) are left untouched.

    Args:
        versions: Dict of version configs to potentially rebase.
        overridden_versions: Set of version strings that had explicit path overrides.

    Returns:
        Dict with rebased version configs where applicable.
    """
    from odoodev.core.global_config import DEFAULT_BASE_DIR, load_global_config

    global_cfg = load_global_config()
    if global_cfg.base_dir == DEFAULT_BASE_DIR:
        return versions

    overridden = overridden_versions or set()
    default_base = os.path.expanduser(DEFAULT_BASE_DIR)
    new_base = os.path.expanduser(global_cfg.base_dir)
    result = {}

    for ver, cfg in versions.items():
        if ver in overridden:
            result[ver] = cfg
            continue

        expanded = os.path.expanduser(cfg.paths.base)
        if expanded.startswith(default_base):
            # Rebase: ~/gitbase/v18 → ~/new-base/v18
            relative = expanded[len(default_base) :].lstrip(os.sep)
            new_path = os.path.join(new_base, relative)
            # Use ~ notation if under home
            home = os.path.expanduser("~")
            if new_path.startswith(home):
                new_path = "~" + new_path[len(home) :]
            new_paths = PathConfig(
                base=new_path,
                server_subdir=cfg.paths.server_subdir,
                dev_subdir=cfg.paths.dev_subdir,
                native_subdir=cfg.paths.native_subdir,
                conf_subdir=cfg.paths.conf_subdir,
            )
            result[ver] = VersionConfig(
                version=cfg.version,
                python=cfg.python,
                postgres=cfg.postgres,
                ports=cfg.ports,
                paths=new_paths,
                git=cfg.git,
            )
        else:
            result[ver] = cfg

    return result


def load_versions(override_path: Path | None = None) -> dict[str, VersionConfig]:
    """Load version configurations from bundled YAML and optional user overrides.

    Args:
        override_path: Optional path to user override YAML. Defaults to
                       ~/.config/odoodev/versions-override.yaml

    Returns:
        Dictionary mapping version strings to VersionConfig objects.
    """
    bundled_path = _get_bundled_versions_path()
    with open(bundled_path, encoding="utf-8") as f:
        bundled_data = yaml.safe_load(f)

    versions = {}
    for ver, cfg in bundled_data.get("versions", {}).items():
        versions[str(ver)] = _parse_version(str(ver), cfg)

    # Apply user overrides and track which versions have explicit path overrides
    overridden_versions: set[str] = set()
    user_path = override_path or _get_user_override_path()
    if user_path.exists():
        with open(user_path, encoding="utf-8") as f:
            override_data = yaml.safe_load(f)
        if override_data and "versions" in override_data:
            for ver, cfg in override_data["versions"].items():
                ver_str = str(ver)
                if "paths" in cfg:
                    overridden_versions.add(ver_str)
                if ver_str in versions:
                    versions[ver_str] = _parse_version(ver_str, cfg)
                else:
                    versions[ver_str] = _parse_version(ver_str, cfg)

    # Apply global base_dir from config.yaml (respects overrides)
    versions = _apply_global_base_dir(versions, overridden_versions)

    return versions


def get_version(version: str, versions: dict[str, VersionConfig] | None = None) -> VersionConfig:
    """Get configuration for a specific Odoo version.

    Args:
        version: Version string (e.g., "18")
        versions: Optional pre-loaded versions dict. If None, loads from files.

    Returns:
        VersionConfig for the requested version.

    Raises:
        KeyError: If version is not found in registry.
    """
    if versions is None:
        versions = load_versions()
    if version not in versions:
        available = ", ".join(sorted(versions.keys()))
        raise KeyError(f"Unknown Odoo version '{version}'. Available: {available}")
    return versions[version]


def detect_version_from_cwd() -> str | None:
    """Detect Odoo version from current working directory.

    Looks for patterns like {base_dir}/v18/... in the current path.
    Uses base_dir from global config (defaults to ~/gitbase).

    Returns:
        Version string (e.g., "18") or None if not detected.
    """
    from odoodev.core.global_config import load_global_config

    cwd = os.getcwd()
    global_cfg = load_global_config()
    base_dir = os.path.expanduser(global_cfg.base_dir)
    if cwd.startswith(base_dir):
        relative = cwd[len(base_dir) :].lstrip(os.sep)
        parts = relative.split(os.sep)
        if parts and parts[0].startswith("v"):
            version_str = parts[0][1:]  # Remove 'v' prefix
            if version_str.isdigit():
                return version_str
    return None


def available_versions() -> list[str]:
    """Return sorted list of available version strings."""
    versions = load_versions()
    return sorted(versions.keys())
