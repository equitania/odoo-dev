"""What a myodoo-docker server already knows about itself.

The playbook assistant used to ask for every container name, database name and
data directory by hand, although the server's own configuration holds them:
``~/docker2update.yaml`` lists the Odoo instances the update routine maintains,
``~/container2backup.yaml`` says where the nightly backups go. Typing them again
is slow, and a typo produces exactly the mismatch the preflight then has to
catch.

Read-only and tolerant: a missing or unparseable file yields an empty result,
never an exception — the assistant falls back to asking.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import yaml

logger = logging.getLogger(__name__)

UPDATE_CONFIG_PATH = "~/docker2update.yaml"
BACKUP_CONFIG_PATH = "~/container2backup.yaml"
# container2backup.py writes database archives into this folder below its backup_path.
BACKUP_DATABASE_SUBDIR = "docker"
DEFAULT_BACKUP_DIR = "/opt/backups/docker"
CONTAINER_DATA_DIR = "/opt/odoo/data"

# "-v /opt/odoo/live:/opt/odoo/data" or "--volume=/opt/odoo/live:/opt/odoo/data:rw"
_VOLUME_RE = re.compile(r"(?:-v|--volume)[=\s]+(\S+?):(/[^:\s]+)(?::\S+)?")
_ARCHIVE_SUFFIXES = (".tar.zst", ".tar.gz", ".tgz", ".tar", ".zip", ".7z", ".sql.gz", ".sql", ".dump")


@dataclass(frozen=True)
class Instance:
    """One Odoo instance as ``docker2update.yaml`` defines it."""

    container: str
    database: str
    db_container: str
    data_dir: str = ""  # host path of /opt/odoo/data; empty = resolved via docker inspect at run time
    owner: str = "ownerp"
    odoo_version: str = ""
    active: bool = True

    @property
    def target_name(self) -> str:
        """Short name for the playbook's ``targets:`` block: 'live-odoo' -> 'live'."""
        name = self.container
        for suffix in ("-odoo", "_odoo"):
            if name.endswith(suffix) and len(name) > len(suffix):
                return name[: -len(suffix)]
        return name

    def as_target(self) -> dict[str, str]:
        """The answers-format target block for this instance."""
        return {
            "db_container": self.db_container,
            "db_name": self.database,
            "odoo_container": self.container,
            "owner": self.owner or "ownerp",
            "data_dir": self.data_dir,
        }


@dataclass(frozen=True)
class BackupFile:
    """A backup archive found on disk."""

    path: str
    size: int
    mtime: float


def _load_yaml(path: str) -> Any:
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s: %s", expanded, exc)
        return None


def data_dir_from_volume(volume: str) -> str:
    """Host path mounted at /opt/odoo/data in a ``docker run`` volume string; '' if none."""
    for host_path, container_path in _VOLUME_RE.findall(volume or ""):
        if container_path.rstrip("/") == CONTAINER_DATA_DIR and host_path.startswith(("/", "~", "$")):
            return os.path.expandvars(host_path)
    return ""


def load_instances(config_path: str = UPDATE_CONFIG_PATH) -> list[Instance]:
    """Every instance ``docker2update.yaml`` defines completely, active ones first.

    An entry without container, database or database host is skipped: it cannot
    become a playbook target, and offering it would only move the typing to a
    later prompt.
    """
    from odoodev.core.server_preflight import _walk_entries

    instances: list[Instance] = []
    for entry in _walk_entries(_load_yaml(config_path)):
        container = str(entry.get("container_name", "") or "").strip()
        database = str(entry.get("database_name", "") or "").strip()
        db_container = str(entry.get("db_host", "") or "").strip()
        if not (container and database and db_container):
            continue
        instances.append(
            Instance(
                container=container,
                database=database,
                db_container=db_container,
                data_dir=data_dir_from_volume(str(entry.get("volume", "") or "")),
                owner=str(entry.get("db_user", "") or "ownerp").strip() or "ownerp",
                odoo_version=str(entry.get("odoo_version", "") or "").strip(),
                active=entry.get("active") is not False,
            )
        )
    return sorted(instances, key=lambda instance: not instance.active)


def backup_directory(config_path: str = BACKUP_CONFIG_PATH) -> str:
    """Where the server's backup tool puts database archives; '' when it is not configured."""
    data = _load_yaml(config_path)
    if not isinstance(data, dict):
        return ""
    defaults = data.get("defaults")
    backup_path = str(defaults.get("backup_path", "") or "").strip() if isinstance(defaults, dict) else ""
    if not backup_path:
        return ""
    return os.path.join(os.path.expandvars(backup_path), BACKUP_DATABASE_SUBDIR)


def default_backup_dir(config_path: str = BACKUP_CONFIG_PATH) -> str:
    """The configured backup directory, or the toolkit's convention when nothing is configured."""
    return backup_directory(config_path) or DEFAULT_BACKUP_DIR


def list_backups(directory: str, limit: int = 12) -> list[BackupFile]:
    """The newest backup archives directly inside ``directory``, newest first."""
    expanded = os.path.expanduser(directory)
    found: list[BackupFile] = []
    try:
        with os.scandir(expanded) as entries:
            for entry in entries:
                if not entry.name.endswith(_ARCHIVE_SUFFIXES) or not entry.is_file():
                    continue
                stat = entry.stat()
                found.append(BackupFile(path=entry.path, size=stat.st_size, mtime=stat.st_mtime))
    except OSError:
        return []
    found.sort(key=lambda backup: backup.mtime, reverse=True)
    return found[:limit]


def format_size(size: int) -> str:
    """Human-readable size: 9028428100 -> '8.4 GB'."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
