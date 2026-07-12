"""Docker-only primitives for server-mode playbooks.

Customer servers run Odoo and PostgreSQL as plain Docker containers
(``live-odoo``/``live-db``, ``test-odoo``/``test-db``) without any odoodev dev
layout. This module provides the container lifecycle and inspection helpers the
server-mode playbook steps are built on.

Deliberately separate from ``container_backend.py``: that module abstracts the
swappable *local dev* database runtime (Docker vs. Apple Container), while
server mode is Docker-only by definition.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

# Timestamp embedded in container2backup filenames: YYYY-MM-DD_HH-MM-SS
_FILENAME_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")


def docker_container_running(name: str, cli: str = "docker") -> bool:
    """Return True if the named container exists and is running."""
    try:
        result = subprocess.run(
            [cli, "inspect", "-f", "{{.State.Running}}", name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def docker_container_exists(name: str, cli: str = "docker") -> bool:
    """Return True if a container with this name exists (running or stopped)."""
    try:
        result = subprocess.run(
            [cli, "inspect", "-f", "{{.Id}}", name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def docker_start(name: str, cli: str = "docker") -> tuple[bool, str]:
    """Start a container by name. Idempotent: an already-running container is success."""
    if docker_container_running(name, cli):
        return True, f"Container '{name}' already running"
    try:
        result = subprocess.run(
            [cli, "start", name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, f"Container '{name}' started"


def docker_stop(name: str, timeout: int = 30, cli: str = "docker") -> tuple[bool, str]:
    """Stop a container by name. Idempotent: an already-stopped/missing container is success
    only when it exists; a missing container is an error (likely a misconfigured playbook).
    """
    if not docker_container_exists(name, cli):
        return False, f"Container '{name}' not found"
    if not docker_container_running(name, cli):
        return True, f"Container '{name}' already stopped"
    try:
        result = subprocess.run(
            [cli, "stop", "-t", str(timeout), name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, f"Container '{name}' stopped"


def docker_exec(
    name: str,
    cmd: list[str],
    stdin_data: bytes | str | None = None,
    cli: str = "docker",
) -> tuple[bool, str, str]:
    """Run a command inside a running container.

    Returns:
        Tuple of (success, stdout, stderr).
    """
    full_cmd = [cli, "exec", "-i", name, *cmd]
    input_bytes: bytes | None
    if isinstance(stdin_data, str):
        input_bytes = stdin_data.encode("utf-8")
    else:
        input_bytes = stdin_data
    try:
        result = subprocess.run(
            full_cmd,
            input=input_bytes,
            stdin=subprocess.DEVNULL if input_bytes is None else None,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        return False, "", str(exc)
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    return result.returncode == 0, stdout, stderr


def resolve_container_host_path(container: str, container_path: str, cli: str = "docker") -> str | None:
    """Resolve the host-side path backing a path inside a container.

    Inspects the container's mounts and matches ``container_path`` against the
    mount destinations (longest prefix wins), then maps the remainder onto the
    mount source. Works for bind mounts (``/opt/odoo/test`` -> ``/opt/odoo/data``)
    and named volumes (``/var/lib/docker/volumes/vol-odoo-test/_data``) alike.

    Returns None when no mount covers ``container_path``.
    """
    try:
        result = subprocess.run(
            [cli, "inspect", "-f", "{{json .Mounts}}", container],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        logger.error("docker inspect failed for %s: %s", container, result.stderr.strip())
        return None

    try:
        mounts = json.loads(result.stdout.strip() or "[]")
    except json.JSONDecodeError:
        logger.error("Unparseable mount JSON for container %s", container)
        return None

    normalized = container_path.rstrip("/")
    best_dest = ""
    best_src = ""
    for mount in mounts or []:
        dest = str(mount.get("Destination", "")).rstrip("/")
        src = str(mount.get("Source", ""))
        if not dest or not src:
            continue
        if (normalized == dest or normalized.startswith(dest + "/")) and len(dest) > len(best_dest):
            best_dest = dest
            best_src = src

    if not best_dest:
        return None
    remainder = normalized[len(best_dest) :].lstrip("/")
    return os.path.join(best_src, remainder) if remainder else best_src


def chown_recursive(path: str, uid: int = 1000, gid: int = 1000) -> bool:
    """Recursively chown a path (default: the Odoo container user 1000:1000).

    Uses the ``chown -R`` binary — server filestores can hold millions of files
    and a Python ``os.walk`` loop would be an order of magnitude slower.
    """
    try:
        result = subprocess.run(
            ["chown", "-R", f"{uid}:{gid}", path],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        logger.error("chown not available: %s", exc)
        return False
    if result.returncode != 0:
        logger.error("chown -R failed for %s: %s", path, result.stderr.strip())
        return False
    return True


def find_latest_backup(directory: str, pattern: str, select_by: str = "mtime") -> str | None:
    """Find the newest backup file matching a glob pattern in a directory.

    ``select_by``:
        - ``mtime`` (default): newest modification time wins.
        - ``filename_timestamp``: the ``YYYY-MM-DD_HH-MM-SS`` timestamp embedded in
          container2backup-style filenames wins (lexicographic comparison is
          chronological for this format); files without a parseable timestamp are
          ignored in this mode.

    Returns the absolute path of the winning file, or None if nothing matches.
    """
    candidates = [p for p in glob.glob(os.path.join(os.path.expanduser(directory), pattern)) if os.path.isfile(p)]
    if not candidates:
        return None

    if select_by == "filename_timestamp":
        stamped: list[tuple[str, str]] = []
        for path in candidates:
            match = _FILENAME_TIMESTAMP_RE.search(os.path.basename(path))
            if match:
                stamped.append((match.group(0), path))
        if not stamped:
            return None
        return os.path.abspath(max(stamped)[1])

    return os.path.abspath(max(candidates, key=os.path.getmtime))
