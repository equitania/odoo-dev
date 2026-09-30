"""Checks a server playbook has to pass before its first step changes anything.

A server playbook drops a database, swaps a filestore and rebuilds an image.
Every mismatch that can be read off the host beforehand is cheaper to report
here than to discover after the drop: the update configuration naming a
different database than the playbook, an ``odoo_version`` that does not match
the release, an image older than the system the backup came from.

Read-only, and silent about what it cannot look at: on a machine without
Docker, without ``docker2update.yaml`` or without the backup file a check
produces no finding at all, so ``odoodev run --dry-run`` stays usable on a
workstation.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Where the myodoo images keep the Odoo kernel's release file.
ODOO_RELEASE_PATH = "/opt/odoo/odoo-server/odoo/release.py"
UPDATE_CONFIG_PATH = "~/docker2update.yaml"

_VERSION_INFO_RE = re.compile(r"^version_info\s*=\s*\((.+)\)\s*$", re.MULTILINE)
# ownERP kernels carry their build date as the last element: '-26.03.10' (YY.MM.DD).
_BUILD_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})")

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One preflight result; ``error`` stops the run, ``warning`` is reported only."""

    level: str
    message: str


@dataclass(frozen=True)
class OdooRelease:
    """The kernel an image was built from, as far as ``release.py`` tells."""

    major: str
    raw: str
    build: str = ""  # "26.03.10", empty when the kernel carries no build date

    @property
    def build_key(self) -> tuple[int, int, int] | None:
        match = _BUILD_RE.fullmatch(self.build)
        return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def parse_release(text: str) -> OdooRelease | None:
    """Parse ``version_info = (19, 0, 0, FINAL, 0, '-26.03.10')`` out of a release.py."""
    match = _VERSION_INFO_RE.search(text or "")
    if not match:
        return None
    raw = match.group(1).strip()
    parts = [part.strip().strip("'\"") for part in raw.split(",")]
    if not parts or not parts[0].isdigit():
        return None
    build_match = _BUILD_RE.search(parts[-1]) if len(parts) > 1 else None
    return OdooRelease(major=parts[0], raw=raw, build=build_match.group(0) if build_match else "")


def read_container_release(container: str) -> OdooRelease | None:
    """The kernel release inside a container's image; None when it cannot be read."""
    from odoodev.core.docker_exec import read_container_file

    content = read_container_file(container, ODOO_RELEASE_PATH)
    return parse_release(content) if content else None


def build_is_older(candidate: str, reference: str) -> bool | None:
    """True if build date ``candidate`` lies before ``reference``; None if either is unreadable."""
    left = OdooRelease("", "", candidate).build_key
    right = OdooRelease("", "", reference).build_key
    if left is None or right is None:
        return None
    return left < right


# ---------------------------------------------------------------------------
# Backup manifest (sidecar file next to the archive)
# ---------------------------------------------------------------------------

_ARCHIVE_SUFFIXES = (".tar.zst", ".tar.gz", ".tgz", ".tar", ".zip", ".7z", ".sql.gz", ".sql", ".dump")


def manifest_candidates(backup_file: str) -> list[str]:
    """Where a backup's manifest may sit: ``<file>.manifest`` or ``<file without suffix>.manifest``."""
    candidates = [f"{backup_file}.manifest"]
    for suffix in _ARCHIVE_SUFFIXES:
        if backup_file.endswith(suffix):
            candidates.append(f"{backup_file[: -len(suffix)]}.manifest")
            break
    return candidates


def read_backup_manifest(backup_file: str) -> dict[str, str]:
    """``key=value`` lines of the manifest next to a backup; empty when there is none."""
    for path in manifest_candidates(backup_file):
        if not os.path.isfile(path):
            continue
        values: dict[str, str] = {}
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    key, sep, value = line.strip().partition("=")
                    if sep and key and not key.startswith("#"):
                        values[key.strip()] = value.strip()
        except OSError as exc:
            logger.warning("Could not read manifest %s: %s", path, exc)
            return {}
        return values
    return {}


def write_backup_manifest(backup_file: str, values: dict[str, str]) -> str | None:
    """Write ``<backup_file>.manifest`` (0600, like the archive); None when that fails."""
    path = f"{backup_file}.manifest"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning("Could not write manifest %s: %s", path, exc)
        return None
    return path


# ---------------------------------------------------------------------------
# docker2update.yaml
# ---------------------------------------------------------------------------


def _walk_entries(node: Any) -> list[dict[str, Any]]:
    """Every mapping carrying a ``container_name``, wherever the file nests its list."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "container_name" in node:
            found.append(node)
        for value in node.values():
            found.extend(_walk_entries(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_entries(item))
    return found


def find_update_entry(config_path: str, container: str) -> tuple[bool, dict[str, Any] | None]:
    """Look a container up in ``docker2update.yaml``.

    Returns ``(readable, entry)``: ``readable`` is False when the file is
    missing or unparseable (no statement possible), ``entry`` is None when the
    file is readable and does not define the container.
    """
    path = os.path.expanduser(config_path or UPDATE_CONFIG_PATH)
    if not os.path.isfile(path):
        return False, None
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return False, None
    for entry in _walk_entries(data):
        if str(entry.get("container_name", "")) == container:
            return True, entry
    return True, None


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _same_container(args: dict[str, Any], container: str) -> bool:
    return (str(args.get("container", "") or "") or str(args.get("odoo_container", "") or "")) == container


def _resolvable_backup_file(args: dict[str, Any]) -> str:
    """The backup file a restore step will read, if that can be told before the run."""
    from odoodev.core.docker_exec import find_latest_backup

    source = args.get("backup_source") or {}
    if isinstance(source, str):
        return os.path.expanduser(source)
    if not isinstance(source, dict):
        return ""
    mode = str(source.get("mode", "") or ("file" if source.get("path") else "newest_in_dir"))
    if mode == "file":
        return os.path.expanduser(str(source.get("path", "") or ""))
    if mode == "newest_in_dir" and source.get("dir") and source.get("pattern"):
        return (
            find_latest_backup(
                str(source["dir"]), str(source["pattern"]), select_by=str(source.get("select_by", "mtime") or "mtime")
            )
            or ""
        )
    return ""


def _database_state(db_container: str, db_name: str, owner: str) -> bool | None:
    """True/False whether the database exists; None when the DB container cannot be asked."""
    from odoodev.core.database import database_exists, pg_exec_container
    from odoodev.core.docker_exec import docker_container_running

    if not db_container or not docker_container_running(db_container):
        return None
    with pg_exec_container(db_container):
        return database_exists(db_name, host="container", port=0, user=owner)


def _check_restore(version: str, index: int, steps: list[tuple[str, dict[str, Any]]]) -> list[Finding]:
    _command, args = steps[index]
    findings: list[Finding] = []
    container = str(args.get("odoo_container", "") or "")
    db_container = str(args.get("db_container", "") or "")
    db_name = str(args.get("db_name", "") or "")
    owner = str(args.get("owner", "") or "ownerp")

    before = steps[:index]
    after = steps[index + 1 :]
    rebuild_after = container and any(c == "server.rebuild" and _same_container(a, container) for c, a in after)
    rebuild_before = container and any(c == "server.rebuild" and _same_container(a, container) for c, a in before)
    update_after = any(c == "server.update-all" and str(a.get("db_name", "")) == db_name for c, a in after)

    if rebuild_before and not rebuild_after:
        findings.append(
            Finding(
                WARNING,
                f"server.rebuild for '{container}' runs before the restore: it updates the database that is about "
                f"to be replaced, and '{db_name}' stays on the module state of its backup. Move it behind "
                f"server.restore.",
            )
        )
    elif not rebuild_after and not update_after:
        findings.append(
            Finding(
                WARNING,
                f"'{db_name}' is restored but never updated: if the image carries newer modules than the backup, "
                f"Odoo starts on a database that does not match its code. Add server.rebuild after server.restore.",
            )
        )

    exists = _database_state(db_container, db_name, owner) if db_name else None
    drop = args.get("drop", True)
    if exists and drop in (False, "false", "False", "no", "0"):
        findings.append(
            Finding(ERROR, f"Database '{db_name}' already exists in '{db_container}' and the restore has drop: false.")
        )
    elif exists:
        backed_up = any(
            c == "server.backup"
            and str(a.get("db_container", "")) == db_container
            and str(a.get("db_name", "")) == db_name
            for c, a in before
        )
        if not backed_up:
            findings.append(
                Finding(
                    WARNING,
                    f"Database '{db_name}' exists in '{db_container}' and will be replaced without a backup of its "
                    f"current state. Add a server.backup step with safety: true for this target.",
                )
            )

    backup_file = _resolvable_backup_file(args)
    if backup_file and os.path.isfile(backup_file) and container:
        source_build = read_backup_manifest(backup_file).get("odoo_build", "")
        if source_build:
            release = read_container_release(container)
            if release and build_is_older(release.build, source_build):
                message = (
                    f"The image of '{container}' carries kernel {release.build}, the backup was taken on kernel "
                    f"{source_build}. Modules newer than the kernel fail to load."
                )
                if rebuild_after:
                    findings.append(
                        Finding(WARNING, message + " The server.rebuild after the restore has to deliver a newer one.")
                    )
                else:
                    findings.append(Finding(ERROR, message + " Publish a current kernel and rebuild the image first."))
    return findings


def _check_rebuild(version: str, args: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    container = str(args.get("container", "") or "") or str(args.get("odoo_container", "") or "")
    if not container:
        return findings
    config = str(args.get("config", "") or UPDATE_CONFIG_PATH)
    readable, entry = find_update_entry(config, container)
    if not readable:
        return findings
    if entry is None:
        return [Finding(ERROR, f"'{container}' is not defined in {config} — server.rebuild cannot update it.")]

    db_name = str(args.get("db_name", "") or "")
    configured_db = str(entry.get("database_name", "") or "")
    if db_name and configured_db and configured_db != db_name:
        findings.append(
            Finding(
                ERROR,
                f"{config} updates database '{configured_db}' for '{container}', the playbook works on "
                f"'{db_name}'. The module update would run against the wrong database.",
            )
        )
    configured_version = str(entry.get("odoo_version", "") or "").split(".")[0]
    if configured_version and configured_version != str(version).split(".")[0]:
        findings.append(
            Finding(
                ERROR,
                f"{config} has odoo_version '{configured_version}' for '{container}', the playbook is for "
                f"version {version}. The update would use the build scripts of the wrong version.",
            )
        )
    if entry.get("active") is False:
        findings.append(Finding(WARNING, f"'{container}' is switched off (active: false) in {config}."))
    return findings


def preflight_server_steps(version: str, steps: list[tuple[str, dict[str, Any]]]) -> list[Finding]:
    """Run every check over the resolved steps of a playbook.

    ``steps`` are ``(command, args)`` pairs with templates rendered and the
    target already merged in — the same args the handlers will receive.
    """
    findings: list[Finding] = []
    containers: list[str] = []
    for index, (command, args) in enumerate(steps):
        try:
            if command == "server.restore":
                findings.extend(_check_restore(version, index, steps))
            elif command == "server.rebuild":
                findings.extend(_check_rebuild(version, args))
        except Exception as exc:  # a preflight must never be the reason a run dies
            logger.warning("Preflight check for %s failed: %s", command, exc)
        if command in ("server.restore", "server.rebuild", "server.update-all", "server.verify"):
            container = str(args.get("container", "") or "") or str(args.get("odoo_container", "") or "")
            if container and container not in containers:
                containers.append(container)

    major = str(version).split(".")[0]
    for container in containers:
        try:
            release = read_container_release(container)
        except Exception as exc:
            logger.warning("Could not read the release of %s: %s", container, exc)
            continue
        if release and release.major != major:
            # An image that the playbook rebuilds itself may legitimately change version.
            rebuilt = any(c == "server.rebuild" and _same_container(a, container) for c, a in steps)
            findings.append(
                Finding(
                    WARNING if rebuilt else ERROR,
                    f"The image of '{container}' is Odoo {release.major}, the playbook is for version {version}.",
                )
            )

    unique: list[Finding] = []
    for finding in findings:
        if finding not in unique:
            unique.append(finding)
    return unique
