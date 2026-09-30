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
import shutil
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


def ensure_dir_owner(path: str, uid: int = 1000, gid: int = 1000) -> bool:
    """Create a directory if missing and hand this one directory to ``uid:gid``.

    Not recursive — meant for a parent like ``<data_dir>/filestore`` that a
    root-run restore would otherwise leave root-owned, so the Odoo process could
    not create the filestore of a second database next to the restored one.
    """
    try:
        os.makedirs(path, exist_ok=True)
        stat = os.stat(path)
        if stat.st_uid != uid or stat.st_gid != gid:
            os.chown(path, uid, gid)
    except OSError as exc:
        logger.error("Could not hand %s to %s:%s: %s", path, uid, gid, exc)
        return False
    return True


def docker_container_image(name: str, cli: str = "docker") -> str:
    """Image a container was created from; '' when it cannot be inspected."""
    try:
        result = subprocess.run(
            [cli, "inspect", "-f", "{{.Config.Image}}", name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# Where the helper container sees the data directory and the extracted backup.
HELPER_DATA_MOUNT = "/odoodev-data"
HELPER_SOURCE_MOUNT = "/odoodev-src"


class HostDataDir:
    """Filestore operations done directly on the host — the case for root."""

    via_container = False

    def ensure_owned_dir(self, path: str, uid: int, gid: int) -> bool:
        return ensure_dir_owner(path, uid=uid, gid=gid)

    def place(self, src: str, dest: str, uid: int, gid: int) -> str:
        """Move the contents of ``src`` to ``dest`` and hand them to uid:gid. Returns '' or an error."""
        from odoodev.core.database import move_filestore

        if not move_filestore(src, dest):
            return f"Moving the filestore to {dest} failed"
        if not chown_recursive(dest, uid=uid, gid=gid):
            return f"chown -R {uid}:{gid} {dest} failed"
        return ""

    def rename(self, old: str, new: str) -> None:
        os.rename(old, new)

    def remove(self, path: str) -> None:
        shutil.rmtree(path, ignore_errors=True)


class HelperDataDir:
    """The same operations through a short-lived root container.

    A server operated by an unprivileged account in the ``docker`` group cannot
    write into the Odoo data directory: it belongs to the container's user
    (uid 1000), and handing files to that uid needs root. A throwaway container
    with the data directory mounted can do both. It runs from an image that is
    already on the server, without network.
    """

    via_container = True

    def __init__(self, data_dir: str, image: str, cli: str = "docker") -> None:
        self.data_dir = os.path.realpath(data_dir)
        self.image = image
        self.cli = cli

    def _inside(self, path: str, root: str, mount: str) -> str:
        relative = os.path.relpath(os.path.realpath(path), root)
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            raise ValueError(f"{path} is outside {root}")
        return mount if relative == os.curdir else f"{mount}/{relative}"

    def _data(self, path: str) -> str:
        return self._inside(path, self.data_dir, HELPER_DATA_MOUNT)

    def _run(self, script: str, script_args: list[str], source_dir: str = "") -> tuple[bool, str]:
        cmd = [self.cli, "run", "--rm", "--user", "0:0", "--network", "none", "--entrypoint", "sh"]
        cmd += ["-v", f"{self.data_dir}:{HELPER_DATA_MOUNT}"]
        if source_dir:
            cmd += ["-v", f"{source_dir}:{HELPER_SOURCE_MOUNT}"]
        # Paths travel as positional parameters, never inside the script text.
        cmd += [self.image, "-c", script, "sh", *script_args]
        try:
            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        except FileNotFoundError as exc:
            return False, str(exc)
        if result.returncode != 0:
            logger.error("Helper container failed (%s): %s", script, result.stderr.strip())
        return result.returncode == 0, result.stderr.strip()

    def ensure_owned_dir(self, path: str, uid: int, gid: int) -> bool:
        ok, _err = self._run('mkdir -p "$1" && chown "$2" "$1"', [self._data(path), f"{uid}:{gid}"])
        return ok

    def place(self, src: str, dest: str, uid: int, gid: int) -> str:
        source_dir = os.path.realpath(src)
        script = 'mkdir -p "$2" && cp -a "$1"/. "$2"/ && chown -R "$3" "$2" && rm -rf "$1"/*'
        ok, err = self._run(script, [HELPER_SOURCE_MOUNT, self._data(dest), f"{uid}:{gid}"], source_dir=source_dir)
        return "" if ok else f"Placing the filestore at {dest} through a helper container failed: {err[:300]}"

    def rename(self, old: str, new: str) -> None:
        ok, err = self._run('[ ! -e "$2" ] && mv "$1" "$2"', [self._data(old), self._data(new)])
        if not ok:
            raise OSError(err or f"could not rename {old} to {new}")

    def remove(self, path: str) -> None:
        if os.path.lexists(path):
            self._run('rm -rf "$1"', [self._data(path)])


def data_dir_ops(data_dir: str, image_container: str, cli: str = "docker") -> HostDataDir | HelperDataDir:
    """How this process can change the Odoo data directory: directly, or through a helper container.

    Root and anyone who can write the filestore directory work on the host. An
    unprivileged account gets the helper, started from the image of
    ``image_container`` (the database container: it is running, so its image
    is present and nothing has to be pulled).
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() == 0:
        return HostDataDir()
    filestore_root = os.path.join(data_dir, "filestore")
    probe = filestore_root if os.path.isdir(filestore_root) else data_dir
    if os.access(probe, os.W_OK):
        return HostDataDir()
    image = docker_container_image(image_container, cli)
    if not image:
        return HostDataDir()
    return HelperDataDir(data_dir, image, cli)


def docker_health_status(name: str, cli: str = "docker") -> str:
    """Health of a container: ``healthy``/``unhealthy``/``starting``, ``none`` when the
    image defines no HEALTHCHECK, ``stopped`` when it is not running, ``missing``
    when it cannot be inspected at all.
    """
    template = "{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
    try:
        result = subprocess.run(
            [cli, "inspect", "-f", template, name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "missing"
    if result.returncode != 0:
        return "missing"
    running, _, health = result.stdout.strip().partition("|")
    if running != "true":
        return "stopped"
    return health or "none"


def docker_published_port(name: str, container_port: int, cli: str = "docker") -> tuple[str, int] | None:
    """Host address a container port is published on, or None when it is not published.

    A wildcard bind (``0.0.0.0``/``::``) is returned as loopback — the caller
    connects from the host itself.
    """
    try:
        result = subprocess.run(
            [cli, "port", name, str(container_port)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        host, _, port = line.strip().rpartition(":")
        if not port.isdigit():
            continue
        host = host.strip("[]")
        if host in ("", "0.0.0.0", "::"):  # noqa: S104 - recognising a wildcard bind, not binding to it
            host = "127.0.0.1"
        if ":" in host:  # IPv6 literal other than the wildcard: prefer an IPv4 line
            continue
        return host, int(port)
    return None


def read_container_file(name: str, path: str, cli: str = "docker") -> str | None:
    """Content of a file inside a container's image, or None when it cannot be read.

    A running container is read via ``docker exec``; a stopped one through a
    throwaway ``docker run`` of its image (no network, entrypoint ``cat``), so
    the check works in the middle of a restore where Odoo has to be down.
    """
    try:
        if docker_container_running(name, cli):
            cmd = [cli, "exec", name, "cat", path]
        else:
            image = subprocess.run(
                [cli, "inspect", "-f", "{{.Config.Image}}", name],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )
            if image.returncode != 0 or not image.stdout.strip():
                return None
            cmd = [cli, "run", "--rm", "--network", "none", "--entrypoint", "cat", image.stdout.strip(), path]
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


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
