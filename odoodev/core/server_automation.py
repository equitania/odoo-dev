"""Server-mode step handlers for playbook automation on customer servers.

Customer servers run Odoo + PostgreSQL as plain Docker containers
(``live-odoo``/``live-db``, ``test-odoo``/``test-db``) without any odoodev dev
layout. These handlers implement the live -> test mirror workflow: backup from
the live pair, restore into the test pair (drop/create, dump, filestore swap,
sanitize), plus generic SQL and Odoo-RPC configuration steps.

All database access goes through :func:`odoodev.core.database.pg_exec_container`,
so the whole existing sanitize/backup/restore machinery from ``core.database``
is reused unchanged against containers that publish no ports.

Handlers never dereference ``version_cfg.paths`` — server playbooks must work
without a ``~/gitbase`` tree. Like ``automation.py``, no interactive prompts.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from odoodev.core.automation import _step_error, _step_ok, _timed
from odoodev.core.playbook import StepResult
from odoodev.core.version_registry import VersionConfig

logger = logging.getLogger(__name__)

# Placeholders for the host/port parameters of core.database functions: inside a
# pg_exec_container() block they are inert (container exec uses the Unix socket).
_UNUSED_HOST = "container"
_UNUSED_PORT = 0

# Path of the Odoo data dir inside the myodoo containers (bind-mounted from the host).
CONTAINER_DATA_DIR = "/opt/odoo/data"


def _require(args: dict[str, Any], key: str, command: str) -> str:
    value = str(args.get(key, "") or "")
    if not value:
        raise ValueError(f"{command}: missing required arg '{key}' (set it or reference a target)")
    return value


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value is None:
        return default
    return bool(value)


def _reporter(args: dict[str, Any]) -> Callable[[str], None]:
    """The runner's progress callback for this step, or a no-op when nobody listens."""
    callback = args.get("_progress")
    return callback if callable(callback) else (lambda message: None)


def _component_container(args: dict[str, Any], command: str) -> str:
    """Resolve which container a container.* step acts on.

    Explicit ``container`` arg wins; otherwise ``component`` ("odoo"/"db")
    selects the target's container.
    """
    explicit = str(args.get("container", "") or "")
    if explicit:
        return explicit
    component = str(args.get("component", "odoo") or "odoo").lower()
    if component == "db":
        return _require(args, "db_container", command)
    if component == "odoo":
        return _require(args, "odoo_container", command)
    raise ValueError(f"{command}: component must be 'odoo' or 'db', got '{component}'")


def _resolve_data_dir(args: dict[str, Any], command: str) -> str:
    """Host path of the Odoo data mount: explicit ``data_dir`` or docker-inspect lookup."""
    data_dir = str(args.get("data_dir", "") or "")
    if data_dir:
        return os.path.expanduser(data_dir)

    from odoodev.core.docker_exec import resolve_container_host_path

    odoo_container = _require(args, "odoo_container", command)
    resolved = resolve_container_host_path(odoo_container, CONTAINER_DATA_DIR)
    if not resolved:
        raise ValueError(
            f"{command}: could not resolve the host path of '{CONTAINER_DATA_DIR}' for container "
            f"'{odoo_container}' — set 'data_dir' explicitly in the target definition"
        )
    return resolved


# =============================================================================
# Container lifecycle
# =============================================================================


@_timed
def handle_container_stop(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Stop a container by name (idempotent for already-stopped containers)."""
    from odoodev.core.docker_exec import docker_stop

    name = _component_container(args, "container.stop")
    timeout = int(args.get("timeout", 30))
    ok, message = docker_stop(name, timeout=timeout)
    if ok:
        return _step_ok("container.stop", "container.stop", message, 0, container=name)
    return _step_error("container.stop", "container.stop", message, 0)


@_timed
def handle_container_start(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Start a container by name (idempotent for already-running containers)."""
    from odoodev.core.docker_exec import docker_start

    name = _component_container(args, "container.start")
    ok, message = docker_start(name)
    if ok:
        return _step_ok("container.start", "container.start", message, 0, container=name)
    return _step_error("container.start", "container.start", message, 0)


# =============================================================================
# server.backup — container2backup-compatible dump + filestore archive
# =============================================================================


@_timed
def handle_server_backup(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Create a fresh backup from a target's DB container + filestore.

    Output is container2backup-compatible:
    ``{backup_dir}/{db}_{data_container}_dockerbackup_{YYYY-MM-DD_HH-MM-SS}.tar.zst``
    containing ``dump.sql`` + ``filestore/``.

    ``safety: true`` turns the step into the backup taken of a restore's
    *destination* before it is replaced: a database that does not exist yet is
    nothing to back up (step ok), a missing filestore degrades to SQL-only, and
    the file is named ``..._prerestore_...`` so that neither a
    ``from_backup_step`` restore nor a ``*_dockerbackup_*`` pattern picks it up
    as the mirror's source.
    """
    from odoodev.core.database import (
        backup_database_sql,
        create_backup_tar_zst,
        database_exists,
        pg_exec_container,
    )

    command = "server.backup"
    db_container = _require(args, "db_container", command)
    db_name = _require(args, "db_name", command)
    owner = str(args.get("owner", "") or "ownerp")
    backup_dir = os.path.expanduser(_require(args, "backup_dir", command))
    level = int(args.get("compression_level", 5))
    only_sql = _as_bool(args.get("only_sql"), default=False)
    safety = _as_bool(args.get("safety"), default=False)

    if not os.path.isdir(backup_dir):
        return _step_error(command, command, f"Backup directory does not exist: {backup_dir}", 0)

    if safety:
        with pg_exec_container(db_container):
            exists = database_exists(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
        if not exists:
            return _step_ok(
                command,
                command,
                f"Database '{db_name}' does not exist in '{db_container}' yet — nothing to back up",
                0,
                database=db_name,
            )

    filestore_path: str | None = None
    if not only_sql:
        data_dir = _resolve_data_dir(args, command)
        filestore_path = os.path.join(data_dir, "filestore", db_name)
        if not os.path.isdir(filestore_path):
            if safety:
                filestore_path = None
                only_sql = True
            else:
                return _step_error(
                    command,
                    command,
                    f"Filestore not found: {filestore_path} — refusing a silent SQL-only backup "
                    f"(set only_sql: true to dump without the filestore)",
                    0,
                )

    data_container = str(args.get("odoo_container", "") or "") or db_container
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = "_sql_only" if only_sql else ""
    kind = "prerestore" if safety else "dockerbackup"
    output_path = os.path.join(backup_dir, f"{db_name}_{data_container}_{kind}_{timestamp}{suffix}.tar.zst")

    report = _reporter(args)
    temp_dir = tempfile.mkdtemp(prefix="odoodev_server_backup_", dir=backup_dir)
    try:
        dump_path = os.path.join(temp_dir, "dump.sql")
        report(f"dumping '{db_name}' from '{db_container}'")
        with pg_exec_container(db_container):
            if not backup_database_sql(db_name, dump_path, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner):
                return _step_error(command, command, f"pg_dump of '{db_name}' via '{db_container}' failed", 0)

        report("compressing dump and filestore" if filestore_path else "compressing dump")
        if not create_backup_tar_zst(dump_path, output_path, filestore_path=filestore_path, level=level):
            return _step_error(command, command, f"Creating {output_path} failed", 0)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    _write_manifest(output_path, db_name, str(args.get("odoo_container", "") or ""))

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if safety:
        # Not 'backup_file': that key hands the file to a from_backup_step restore.
        return _step_ok(
            command,
            command,
            f"Safety backup of '{db_name}' created: {output_path} ({size_mb:.1f} MB)",
            0,
            safety_backup_file=output_path,
            database=db_name,
        )
    return _step_ok(
        command,
        command,
        f"Backup created: {output_path} ({size_mb:.1f} MB)",
        0,
        backup_file=output_path,
        database=db_name,
    )


def _write_manifest(backup_file: str, db_name: str, odoo_container: str) -> None:
    """Record next to the archive which kernel the database last ran on.

    A restore compares that against the destination image: modules newer than
    the kernel they are loaded by fail on their first import, and nothing in
    the dump itself says which kernel it needs.
    """
    from odoodev.core.server_preflight import read_container_release, write_backup_manifest

    values = {
        "db_name": db_name,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file": os.path.basename(backup_file),
    }
    if odoo_container:
        values["container"] = odoo_container
        release = read_container_release(odoo_container)
        if release:
            values["odoo_release"] = release.raw
            if release.build:
                values["odoo_build"] = release.build
    write_backup_manifest(backup_file, values)


# =============================================================================
# server.rebuild — full container rebuild via update_docker_odoo.py
# =============================================================================

# update_docker_odoo.py is deployed to $HOME on customer servers via getScripts.py;
# its container definitions live in ~/docker2update.yaml (release access code sits
# in release.txt inside each container's build folder — no extra secret needed here).
REBUILD_SCRIPT_PATH = "~/update_docker_odoo.py"
REBUILD_CONFIG_PATH = "~/docker2update.yaml"
# Script-internal timeouts are hardcoded (build 3600s + update 1800s); leave headroom.
REBUILD_TIMEOUT = 7200


@_timed
def handle_server_rebuild(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Rebuild and update a target's Odoo container via ``update_docker_odoo.py``.

    Shells out to the myodoo-docker update script — the server's own update
    routine: it fetches the release info from the release server, rebuilds the
    image with ``docker build``, runs the module update against the database
    named in ``docker2update.yaml`` and starts the container under the same
    name. In a mirror playbook it therefore belongs AFTER ``server.restore``:
    placed before, it updates the database that is about to be replaced and
    leaves the restored one on the module state of its backup.
    """
    import subprocess

    command = "server.rebuild"
    container = str(args.get("container", "") or "") or str(args.get("odoo_container", "") or "")
    if not container:
        return _step_error(
            command, command, f"{command}: missing 'container' (set it or reference a target with odoo_container)", 0
        )
    script_path = os.path.expanduser(str(args.get("script_path", "") or REBUILD_SCRIPT_PATH))
    config_path = os.path.expanduser(str(args.get("config", "") or REBUILD_CONFIG_PATH))
    timeout = int(args.get("timeout", REBUILD_TIMEOUT))
    extra_args = args.get("extra_args") or []
    if not isinstance(extra_args, list):
        return _step_error(command, command, f"{command}: 'extra_args' must be a list", 0)
    if not os.path.isfile(script_path):
        return _step_error(
            command,
            command,
            f"Rebuild script not found: {script_path} — deploy update_docker_odoo.py (getScripts.py) first",
            0,
        )
    if not os.path.isfile(config_path):
        return _step_error(
            command,
            command,
            f"Rebuild config not found: {config_path} — the container must be defined in docker2update.yaml",
            0,
        )

    cmd = ["python3", script_path, "-c", config_path, "-s", container, *[str(a) for a in extra_args]]
    report = _reporter(args)
    # The script prints one line per phase (release, build, update, restart). Read
    # line by line so a run of many minutes shows where it is — unbuffered, or a
    # Python child writing to a pipe would deliver everything at the very end.
    output: list[str] = []
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except FileNotFoundError as exc:
        return _step_error(command, command, f"python3 not available: {exc}", 0)

    def pump() -> None:
        for line in process.stdout or ():
            output.append(line)
            text = line.strip()
            if text:
                report(text)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        reader.join(timeout=5)
        return _step_error(command, command, f"Rebuild of '{container}' timed out after {timeout}s", 0)
    reader.join(timeout=5)
    combined = "".join(output)

    if returncode != 0:
        return _step_error(
            command,
            command,
            f"update_docker_odoo.py failed for '{container}' (exit {returncode}): {combined.strip()[-2000:]}",
            returncode,
        )
    # Exit 0 is not the whole contract: the script has reported a successful
    # update while Odoo could not load the database at all (an image whose
    # modules were newer than its kernel). What Odoo logged decides.
    if not _as_bool(args.get("trust_exit_code"), default=False):
        failures = _update_failures(combined)
        if failures:
            return _step_error(
                command,
                command,
                f"update_docker_odoo.py exited 0 for '{container}', but the module update failed: "
                + " | ".join(failures),
                1,
            )
    return _step_ok(
        command,
        command,
        f"Container '{container}' rebuilt and updated via {os.path.basename(script_path)} (running now)",
        0,
        container=container,
    )


# What Odoo logs when a database cannot be brought up on the image's code. Each
# of these means the instance is down, whatever the update script's exit code says.
_UPDATE_FAILURE_MARKERS = (
    "Failed to initialize database",
    "Failed to load registry",
    "Couldn't load module",
)
_UPDATE_FAILURE_DETAIL_RE = re.compile(r"\b(ImportError|ModuleNotFoundError|ParseError|KeyError|psycopg2\.\w+):")


def _update_failures(output: str, limit: int = 4) -> list[str]:
    """The lines of an update run that say the database did not come up.

    Empty when no failure marker is present — a detail line alone (an
    ImportError logged by some cron) is not evidence of a failed update.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    marked = [line for line in lines if any(marker in line for marker in _UPDATE_FAILURE_MARKERS)]
    if not marked:
        return []
    details = [line for line in lines if _UPDATE_FAILURE_DETAIL_RE.search(line)]
    picked: list[str] = []
    for line in marked + details:
        if line not in picked:
            picked.append(line)
    return [line[:300] for line in picked[:limit]]


# =============================================================================
# server.restore — drop/create, dump restore, filestore swap, psql sanitize
# =============================================================================


def _resolve_backup_file(args: dict[str, Any], command: str) -> str:
    """Resolve the restore input from ``backup_source``.

    Modes: ``from_backup_step`` (the exact file a previous ``server.backup``
    step created this run — no pattern guessing), ``file`` (explicit path) and
    ``newest_in_dir`` (glob pattern, newest match).
    """
    from odoodev.core.docker_exec import find_latest_backup

    source = args.get("backup_source") or {}
    if isinstance(source, str):
        source = {"mode": "file", "path": source}
    if not isinstance(source, dict):
        raise ValueError(f"{command}: 'backup_source' must be a mapping or a file path")

    mode = str(source.get("mode", "") or ("file" if source.get("path") else "newest_in_dir"))
    if mode == "from_backup_step":
        runtime = args.get("_runtime") or {}
        backup_file = str(runtime.get("backup_file", "") or "") if isinstance(runtime, dict) else ""
        if not backup_file:
            raise ValueError(
                f"{command}: backup_source.mode 'from_backup_step' needs a successful server.backup "
                f"step earlier in this playbook — add one before the restore, or use mode "
                f"'file'/'newest_in_dir' instead"
            )
        if not os.path.isfile(backup_file):
            raise ValueError(f"{command}: backup file from the backup step no longer exists: {backup_file}")
        return backup_file

    if mode == "file":
        path = os.path.expanduser(str(source.get("path", "") or ""))
        if not path:
            raise ValueError(f"{command}: backup_source.mode 'file' requires 'path'")
        if not os.path.isfile(path):
            raise ValueError(f"{command}: backup file not found: {path}")
        return path

    if mode == "newest_in_dir":
        directory = str(source.get("dir", "") or "")
        pattern = str(source.get("pattern", "") or "")
        if not directory or not pattern:
            raise ValueError(f"{command}: backup_source.mode 'newest_in_dir' requires 'dir' and 'pattern'")
        select_by = str(source.get("select_by", "mtime") or "mtime")
        newest = find_latest_backup(directory, pattern, select_by=select_by)
        if not newest:
            raise ValueError(f"{command}: no backup matching '{pattern}' found in {directory}")
        return newest

    raise ValueError(
        f"{command}: backup_source.mode must be 'from_backup_step', 'file' or 'newest_in_dir', got '{mode}'"
    )


# Names the restore parks things under while it works: the staging copy it
# restores into, and the previous state it keeps until the swap has succeeded.
STAGING_DB_SUFFIX = "__odoodev_new"
PREVIOUS_DB_SUFFIX = "__odoodev_old"
STAGING_DIR_SUFFIX = ".odoodev_new"
PREVIOUS_DIR_SUFFIX = ".odoodev_old"


def _swap_in(
    *,
    db_container: str,
    conn: dict[str, Any],
    db_name: str,
    staging_db: str,
    previous_db: str,
    target_exists: bool,
    filestore_dest: str,
    filestore_staging: str,
    filestore_previous: str,
) -> str:
    """Put the restored database and filestore in place of the current ones.

    Renames only — each either happens or does not, and every step that fails
    undoes the ones before it. Returns an error message, or "" on success.
    An empty ``filestore_staging`` (SQL-only backup) leaves the filestore alone.
    """
    from odoodev.core.database import pg_exec_container, rename_database_quoted

    def rename(old: str, new: str) -> bool:
        with pg_exec_container(db_container):
            return rename_database_quoted(old, new, **conn)

    if target_exists and not rename(db_name, previous_db):
        return f"Could not move the current '{db_name}' aside — it is unchanged, the restored copy was discarded"
    if not rename(staging_db, db_name):
        if target_exists and not rename(previous_db, db_name):
            return (
                f"Swap failed and the previous database could not be renamed back: it is intact as "
                f"'{previous_db}' — rename it to '{db_name}' by hand"
            )
        return f"Could not put the restored database in place — '{db_name}' is unchanged"

    if not filestore_staging:
        return ""
    try:
        if os.path.isdir(filestore_dest):
            os.rename(filestore_dest, filestore_previous)
        os.rename(filestore_staging, filestore_dest)
    except OSError as exc:
        if os.path.isdir(filestore_previous) and not os.path.isdir(filestore_dest):
            os.rename(filestore_previous, filestore_dest)
        rolled_back = rename(db_name, staging_db) and (not target_exists or rename(previous_db, db_name))
        if rolled_back:
            return f"Swapping the filestore failed ({exc}) — database and filestore of '{db_name}' are unchanged"
        return (
            f"Swapping the filestore failed ({exc}) and the database could not be renamed back: check "
            f"'{db_name}', '{staging_db}' and '{previous_db}' by hand"
        )
    return ""


@_timed
def handle_server_restore(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Restore a backup into a target's DB container, swap the filestore, sanitize.

    The dump is restored into a staging database and the filestore into a
    staging directory; only when both are complete are they renamed into place.
    Until that swap the existing database is untouched, so a broken archive, a
    full disk or a missing extension costs nothing. It needs room for the old
    and the new database side by side for the duration of the step.

    The target's Odoo container must be stopped (use a ``container.stop`` step
    first). Sanitize flags run the same ``core.database`` functions as the CLI
    ``db restore`` pipeline — psql-based steps only. ``odoo-bin neutralize``
    needs a *running* Odoo container and is therefore the separate
    ``server.neutralize`` step, placed after ``container.start``.
    """
    from odoodev.core.database import (
        PG_MAX_IDENTIFIER_BYTES,
        check_restore_space,
        count_installed_modules,
        create_database,
        database_exists,
        deactivate_cronjobs,
        detect_backup_type,
        drop_database,
        dump_uses_pgvector,
        extract_backup,
        is_quotable_db_name,
        neutralize_bank_sync,
        pg_exec_container,
        purge_master_data,
        purge_transactional_data,
        restore_database_report,
        server_offers_pgvector,
        wipe_database,
    )
    from odoodev.core.database import (
        move_filestore as move_filestore_fn,
    )
    from odoodev.core.docker_exec import chown_recursive, docker_container_running, ensure_dir_owner

    command = "server.restore"
    db_container = _require(args, "db_container", command)
    db_name = _require(args, "db_name", command)
    owner = str(args.get("owner", "") or "ownerp")
    odoo_container = str(args.get("odoo_container", "") or "")
    template = str(args.get("template", "template0") or "template0")
    drop = _as_bool(args.get("drop"), default=True)
    check_space = _as_bool(args.get("check_space"), default=True)
    chown_uid = int(args.get("chown_uid", 1000))
    chown_gid = int(args.get("chown_gid", 1000))

    backup_file = _resolve_backup_file(args, command)

    # Safety: never restore under a running Odoo server on the same data dir.
    if odoo_container and docker_container_running(odoo_container):
        return _step_error(
            command,
            command,
            f"Odoo container '{odoo_container}' is still running — add a container.stop step before the restore",
            0,
        )

    data_dir = _resolve_data_dir(args, command)
    filestore_root = os.path.join(data_dir, "filestore")
    filestore_dest = os.path.join(filestore_root, db_name)
    sessions_dir = os.path.join(data_dir, "sessions")

    # The dump goes into a staging database and only a successful restore is
    # swapped in by renaming. The previous state therefore survives every
    # failure up to the swap — a failed restore used to leave the server with
    # neither the old database nor the new one.
    staging_db = f"{db_name}{STAGING_DB_SUFFIX}"
    previous_db = f"{db_name}{PREVIOUS_DB_SUFFIX}"
    filestore_staging = os.path.join(filestore_root, f"{db_name}{STAGING_DIR_SUFFIX}")
    filestore_previous = os.path.join(filestore_root, f"{db_name}{PREVIOUS_DIR_SUFFIX}")
    if not (is_quotable_db_name(db_name) and is_quotable_db_name(staging_db) and is_quotable_db_name(previous_db)):
        return _step_error(
            command,
            command,
            f"Database name '{db_name}' cannot be restored safely: allowed are letters, digits, '_', '-', '.', '$' "
            f"and at most {PG_MAX_IDENTIFIER_BYTES - len(STAGING_DB_SUFFIX)} characters",
            0,
        )

    conn: dict[str, Any] = {"host": _UNUSED_HOST, "port": _UNUSED_PORT, "user": owner}
    with pg_exec_container(db_container):
        leftover_db = database_exists(previous_db, **conn)
        target_exists = database_exists(db_name, **conn)
    if leftover_db or os.path.isdir(filestore_previous):
        what = f"database '{previous_db}'" if leftover_db else f"directory {filestore_previous}"
        return _step_error(
            command,
            command,
            f"Found {what} — the previous state kept by an interrupted restore. It may be the only copy of "
            f"'{db_name}': rename it back or remove it by hand, then run the restore again",
            0,
        )
    if target_exists and not drop:
        return _step_error(
            command,
            command,
            f"Database '{db_name}' already exists in '{db_container}' — set drop: true to replace it",
            0,
        )

    temp_parent = os.path.expanduser(str(args.get("temp_dir", "") or "")) or os.path.dirname(backup_file)
    if check_space:
        ok_space, space_msg, _needed = check_restore_space(backup_file, temp_parent, filestore_dest)
        if not ok_space:
            return _step_error(command, command, space_msg, 0)

    notes: list[str] = []
    report = _reporter(args)
    extract_path = tempfile.mkdtemp(prefix="odoodev_server_restore_", dir=temp_parent)
    try:
        report(f"extracting {os.path.basename(backup_file)}")
        if not extract_backup(backup_file, extract_path):
            return _step_error(command, command, f"Extraction of {backup_file} failed", 0)

        detected = detect_backup_type(extract_path)
        if not detected or not detected.get("sql_file"):
            return _step_error(command, command, f"No dump.sql found in {backup_file}", 0)
        sql_file = detected["sql_file"]
        filestore_src = detected.get("filestore")

        # Everything that can refuse the backup is decided here, before the
        # first change to the server.
        if not filestore_src and not _as_bool(args.get("allow_missing_filestore"), default=False):
            return _step_error(
                command,
                command,
                f"Backup {backup_file} contains no filestore — refusing a half-mirrored restore "
                f"(set allow_missing_filestore: true for SQL-only backups)",
                0,
            )
        if dump_uses_pgvector(sql_file):
            with pg_exec_container(db_container):
                offered = server_offers_pgvector(**conn)
            if offered is False and not _as_bool(args.get("without_pgvector"), default=False):
                return _step_error(
                    command,
                    command,
                    f"The backup uses pgvector (Odoo AI module 'ai'), '{db_container}' does not offer it — the "
                    f"restore would silently drop every table with a vector column. Deploy a PostgreSQL image "
                    f"with pgvector, or set without_pgvector: true to restore without the AI tables",
                    0,
                )
            if offered is None:
                notes.append("could not check whether the database server offers pgvector")

        def discard_staging() -> None:
            with pg_exec_container(db_container):
                drop_database(staging_db, **conn)
            shutil.rmtree(filestore_staging, ignore_errors=True)

        # A staging database or directory still lying around is the debris of a
        # failed run, never anybody's data.
        discard_staging()

        report(f"restoring the dump into '{staging_db}' ('{db_name}' stays untouched)")
        with pg_exec_container(db_container):
            if not create_database(staging_db, template=template, **conn):
                return _step_error(command, command, f"Creating '{staging_db}' (TEMPLATE {template}) failed", 0)
            untouched = f"'{db_name}' is unchanged" if target_exists else "nothing was created"
            restored, sql_errors = restore_database_report(staging_db, sql_file, **conn)
            if not restored:
                drop_database(staging_db, **conn)
                detail = f": {sql_errors[0][:300]}" if sql_errors else ""
                return _step_error(command, command, f"Restoring the dump failed{detail} — {untouched}", 0)
            # psql exits 0 even when statements failed. Before the restored copy
            # replaces anything it has to look like an Odoo database.
            if _as_bool(args.get("check_restored"), default=True):
                installed = count_installed_modules(staging_db, **conn)
                if installed <= 0:
                    drop_database(staging_db, **conn)
                    detail = f" First SQL error: {sql_errors[0][:300]}." if sql_errors else ""
                    return _step_error(
                        command,
                        command,
                        f"The restored dump is not a usable Odoo database (no installed modules readable) — "
                        f"{untouched}.{detail} Set check_restored: false to restore a non-Odoo dump",
                        0,
                    )
            if sql_errors:
                notes.append(f"{len(sql_errors)} SQL error(s) during the restore, first: {sql_errors[0][:200]}")

        if filestore_src:
            report("moving the filestore into place and setting its owner")
            if not ensure_dir_owner(filestore_root, uid=chown_uid, gid=chown_gid):
                notes.append(f"{filestore_root} could not be handed to {chown_uid}:{chown_gid}")
            if not move_filestore_fn(filestore_src, filestore_staging):
                discard_staging()
                return _step_error(
                    command, command, f"Moving the filestore to {filestore_staging} failed — '{db_name}' unchanged", 0
                )
            if not chown_recursive(filestore_staging, uid=chown_uid, gid=chown_gid):
                discard_staging()
                return _step_error(
                    command,
                    command,
                    f"chown -R {chown_uid}:{chown_gid} {filestore_staging} failed — '{db_name}' unchanged",
                    0,
                )

        report(f"swapping the restored database in as '{db_name}'")
        swap_error = _swap_in(
            db_container=db_container,
            conn=conn,
            db_name=db_name,
            staging_db=staging_db,
            previous_db=previous_db,
            target_exists=target_exists,
            filestore_dest=filestore_dest,
            filestore_staging=filestore_staging if filestore_src else "",
            filestore_previous=filestore_previous,
        )
        if swap_error:
            discard_staging()
            return _step_error(command, command, swap_error, 0)
    finally:
        shutil.rmtree(extract_path, ignore_errors=True)

    # From here on the new state is live; what follows only tidies up.
    if os.path.isdir(sessions_dir):
        shutil.rmtree(sessions_dir, ignore_errors=True)
    if target_exists:
        with pg_exec_container(db_container):
            if not drop_database(previous_db, **conn):
                notes.append(f"previous database kept as '{previous_db}' (dropping it failed)")
    if os.path.isdir(filestore_previous):
        shutil.rmtree(filestore_previous, ignore_errors=True)
        if os.path.isdir(filestore_previous):
            notes.append(f"previous filestore kept at {filestore_previous} (removing it failed)")

    # --- psql-based sanitize steps (same core functions as the CLI pipeline) ---
    sanitize_all = _as_bool(args.get("sanitize"), default=False)

    def flag(name: str) -> bool:
        value = args.get(name)
        if value is None:
            return sanitize_all
        return _as_bool(value)

    sanitize_done: list[str] = []
    sanitize_failed: list[str] = []
    with pg_exec_container(db_container):
        if flag("deactivate_cron"):
            report("sanitizing: cron jobs and mail servers off")
            ok = deactivate_cronjobs(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("deactivate_cron")
        if flag("neutralize"):
            # psql portion only; odoo-bin neutralize is the server.neutralize step.
            ok = neutralize_bank_sync(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("neutralize_bank_sync")
        if flag("anonymize"):
            from odoodev.core.database import anonymize_database

            report("sanitizing: anonymizing personal data")
            ok = anonymize_database(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("anonymize")
        if flag("wipe"):
            # filestore_dest is the freshly swapped-in filestore of this database,
            # so the attachment files are deleted along with their rows.
            ok = bool(
                wipe_database(
                    db_name,
                    host=_UNUSED_HOST,
                    port=_UNUSED_PORT,
                    user=owner,
                    filestore_path=filestore_dest,
                )
            )
            (sanitize_done if ok else sanitize_failed).append("wipe")
        if _as_bool(args.get("purge_transactions"), default=False):
            ok, msg = purge_transactional_data(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("purge_transactions")
        if _as_bool(args.get("purge_master_data"), default=False):
            ok, msg = purge_master_data(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("purge_master_data")

    if sanitize_failed:
        return _step_error(
            command,
            command,
            f"Restore of '{db_name}' from {os.path.basename(backup_file)} succeeded, "
            f"but sanitize steps failed: {', '.join(sanitize_failed)}",
            0,
        )

    from odoodev.core.server_preflight import read_backup_manifest

    sanitize_info = f" (sanitize: {', '.join(sanitize_done)})" if sanitize_done else ""
    notes_info = f" — note: {'; '.join(notes)}" if notes else ""
    return _step_ok(
        command,
        command,
        f"Database '{db_name}' restored from {os.path.basename(backup_file)}{sanitize_info}{notes_info}",
        0,
        backup_file=backup_file,
        database=db_name,
        sanitize_steps=sanitize_done,
        notes=notes,
        replaced_existing=target_exists,
        # Kernel the backup was taken on, if its manifest says so — server.verify
        # holds the image against it once the container is up again.
        source_build=read_backup_manifest(backup_file).get("odoo_build", ""),
    )


# =============================================================================
# server.neutralize / server.update-all — odoo-bin inside the running container
# =============================================================================


@_timed
def handle_server_neutralize(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Run ``odoo-bin neutralize`` inside the target's *running* Odoo container."""
    from odoodev.core.database import SERVER_ODOO_BIN_PATH, SERVER_ODOO_CONF_PATH, run_neutralize_container

    command = "server.neutralize"
    odoo_container = _require(args, "odoo_container", command)
    db_name = _require(args, "db_name", command)
    ok, output = run_neutralize_container(
        db_name,
        odoo_container,
        odoo_bin_path=str(args.get("odoo_bin_path", "") or SERVER_ODOO_BIN_PATH),
        config_path=str(args.get("config_path", "") or SERVER_ODOO_CONF_PATH),
    )
    if ok:
        return _step_ok(command, command, f"Database '{db_name}' neutralized in '{odoo_container}'", 0)
    return _step_error(command, command, output, 0)


@_timed
def handle_server_update_all(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Run ``odoo-bin -u all --stop-after-init`` inside the target's running Odoo container.

    Restarts the container afterwards by default (``restart: false`` to skip) so
    the serving process picks up the updated registry.
    """
    from odoodev.core.database import SERVER_ODOO_BIN_PATH, SERVER_ODOO_CONF_PATH, run_update_all_container
    from odoodev.core.docker_exec import docker_start, docker_stop

    command = "server.update-all"
    odoo_container = _require(args, "odoo_container", command)
    db_name = _require(args, "db_name", command)
    extra_args = args.get("extra_args") or []
    if not isinstance(extra_args, list):
        return _step_error(command, command, f"{command}: 'extra_args' must be a list", 0)

    _reporter(args)(f"updating all modules of '{db_name}' inside '{odoo_container}'")
    ok, output = run_update_all_container(
        db_name,
        odoo_container,
        odoo_bin_path=str(args.get("odoo_bin_path", "") or SERVER_ODOO_BIN_PATH),
        config_path=str(args.get("config_path", "") or SERVER_ODOO_CONF_PATH),
        extra_args=[str(a) for a in extra_args],
    )
    if not ok:
        return _step_error(command, command, output, 0)

    message = f"Modules updated (-u all) on '{db_name}' in '{odoo_container}'"
    if _as_bool(args.get("restart"), default=True):
        stop_ok, stop_msg = docker_stop(odoo_container)
        start_ok, start_msg = docker_start(odoo_container)
        if not (stop_ok and start_ok):
            return _step_error(command, command, f"{message}, but restart failed: {stop_msg} / {start_msg}", 0)
        message += ", container restarted"
    return _step_ok(command, command, message, 0, database=db_name)


# =============================================================================
# server.verify — is the instance really up on this database?
# =============================================================================

VERIFY_TIMEOUT = 300
VERIFY_POLL_SECONDS = 3
ODOO_HTTP_PORT = 8069
# Module states that only exist between the start and the end of an update.
_PENDING_MODULE_STATES = ("to upgrade", "to install", "to remove")


def _http_status(url: str, timeout: int = 20) -> tuple[int, str]:
    """GET a page the way a browser would (cookies kept across the redirect).

    Returns ``(status, error)``; status 0 means no HTTP answer at all.
    """
    import http.cookiejar
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        # The URL is assembled from a loopback address docker reports — never from playbook text.
        with opener.open(url, timeout=timeout) as response:  # noqa: S310
            return int(response.status), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc.reason)
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)


@_timed
def handle_server_verify(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Check that the target's Odoo container really serves the database.

    A started container and an update script that exited 0 say little: Odoo can
    be running while every request answers 500 because the registry cannot be
    built. This step waits for the container to report healthy, asks the
    database whether an update was left half done, loads the login page of that
    database, and — when the backup's manifest names the kernel it was taken
    on — holds the image's kernel against it.
    """
    from urllib.parse import quote

    from odoodev.core.database import _run_psql_tuples, pg_exec_container
    from odoodev.core.docker_exec import docker_health_status, docker_published_port
    from odoodev.core.server_preflight import build_is_older, read_container_release

    command = "server.verify"
    odoo_container = _require(args, "odoo_container", command)
    db_container = _require(args, "db_container", command)
    db_name = _require(args, "db_name", command)
    owner = str(args.get("owner", "") or "ownerp")
    timeout = int(args.get("timeout", VERIFY_TIMEOUT))
    deadline = time.monotonic() + timeout
    passed: list[str] = []

    report = _reporter(args)

    # 1. Container up and healthy.
    report(f"waiting for '{odoo_container}' to report healthy")
    health = docker_health_status(odoo_container)
    while health == "starting" and time.monotonic() < deadline:
        time.sleep(VERIFY_POLL_SECONDS)
        health = docker_health_status(odoo_container)
    if health not in ("healthy", "none"):
        reason = {
            "missing": "does not exist",
            "stopped": "is not running",
            "starting": f"did not become healthy within {timeout}s",
            "unhealthy": "reports unhealthy",
        }.get(health, f"is in state '{health}'")
        return _step_error(command, command, f"Odoo container '{odoo_container}' {reason}", 0)
    passed.append("container healthy" if health == "healthy" else "container running (image has no healthcheck)")

    # 2. No module left between two states.
    if _as_bool(args.get("check_modules"), default=True):
        report(f"checking the module states of '{db_name}'")
        states = ", ".join(f"'{state}'" for state in _PENDING_MODULE_STATES)
        query = f"SELECT name, state FROM ir_module_module WHERE state IN ({states}) ORDER BY name;"  # noqa: S608
        with pg_exec_container(db_container):
            ok, rows = _run_psql_tuples(query, db=db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
        if not ok:
            return _step_error(
                command, command, f"Could not read the module states of '{db_name}' in '{db_container}'", 0
            )
        if rows:
            listed = ", ".join(f"{row[0]} ({row[-1]})" for row in rows[:8])
            more = f" and {len(rows) - 8} more" if len(rows) > 8 else ""
            return _step_error(
                command,
                command,
                f"{len(rows)} module(s) of '{db_name}' are stuck in an unfinished update: {listed}{more}",
                0,
            )
        passed.append("no pending module states")

    # 3. The login page of this database loads.
    if _as_bool(args.get("http_check"), default=True):
        published = docker_published_port(odoo_container, int(args.get("http_port", ODOO_HTTP_PORT)))
        if published is None:
            passed.append("HTTP check skipped (port not published)")
        else:
            host, port = published
            report(f"loading the login page on {host}:{port}")
            url = f"http://{host}:{port}/web/login?db={quote(db_name)}"
            status, error = _http_status(url)
            while status == 0 and time.monotonic() < deadline:
                time.sleep(VERIFY_POLL_SECONDS)
                status, error = _http_status(url)
            # A registry that cannot be built answers 500. Anything below that is
            # Odoo talking — a database filter may legitimately redirect or refuse.
            if status == 0 or status >= 500:
                detail = f"HTTP {status}" if status else f"no answer ({error})"
                return _step_error(
                    command,
                    command,
                    f"The login page of '{db_name}' on {host}:{port} does not load: {detail} — "
                    f"check 'docker logs {odoo_container}'",
                    0,
                )
            passed.append(f"login page answers HTTP {status}")

    # 4. Kernel not older than the one the backup ran on.
    runtime = args.get("_runtime") or {}
    source_build = str(args.get("source_build", "") or "") or str(
        runtime.get("source_build", "") if isinstance(runtime, dict) else ""
    )
    if source_build:
        release = read_container_release(odoo_container)
        if release and build_is_older(release.build, source_build):
            return _step_error(
                command,
                command,
                f"The image of '{odoo_container}' carries kernel {release.build}, the backup was taken on kernel "
                f"{source_build} — publish a current kernel and rebuild",
                0,
            )
        if release and release.build:
            passed.append(f"kernel {release.build} not older than the backup's {source_build}")

    return _step_ok(
        command,
        command,
        f"'{db_name}' is up in '{odoo_container}': {', '.join(passed)}",
        0,
        database=db_name,
        container=odoo_container,
        checks=passed,
    )


# =============================================================================
# sql.execute — arbitrary playbook-defined SQL (server target or dev fallback)
# =============================================================================


@_timed
def handle_sql_execute(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Execute SQL statements (list) or a SQL file against a target database.

    With a ``target`` (server mode) the statements run via docker exec into the
    target's DB container; without one they run against the dev environment's
    PostgreSQL (version .env/port), making the step usable in dev playbooks too.
    """
    from odoodev.core.database import _run_psql, _run_psql_file, pg_exec_container

    command = "sql.execute"
    db_name = _require(args, "db_name", command)
    statements = args.get("statements") or []
    sql_file = str(args.get("file", "") or "")
    if not statements and not sql_file:
        return _step_error(command, command, f"{command}: provide 'statements' (list) or 'file'", 0)
    if statements and not isinstance(statements, list):
        return _step_error(command, command, f"{command}: 'statements' must be a list", 0)

    db_container = str(args.get("db_container", "") or "")
    if db_container:
        owner = str(args.get("owner", "") or "ownerp")
        conn: dict[str, Any] = {"host": _UNUSED_HOST, "port": _UNUSED_PORT, "user": owner}
    else:
        from odoodev.core.automation import _get_db_params, _load_env_vars

        conn = _get_db_params(version_cfg, _load_env_vars(version_cfg))

    def _run_all() -> StepResult:
        executed = 0
        for index, statement in enumerate(statements, start=1):
            ok, output = _run_psql(str(statement), db=db_name, **conn)
            if not ok:
                return _step_error(command, command, f"Statement {index} failed: {output.strip()}", 0)
            executed += 1
        if sql_file:
            path = os.path.expanduser(sql_file)
            if not os.path.isfile(path):
                return _step_error(command, command, f"SQL file not found: {path}", 0)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            ok, output = _run_psql_file(content, db_name, **conn)
            if not ok:
                return _step_error(command, command, f"SQL file {path} failed: {output.strip()}", 0)
            executed += 1
        return _step_ok(command, command, f"{executed} SQL step(s) executed on '{db_name}'", 0, executed=executed)

    if db_container:
        with pg_exec_container(db_container):
            return _run_all()
    return _run_all()


# =============================================================================
# rpc.execute — declarative Odoo RPC via odoorpc-toolbox
# =============================================================================


def _connect_rpc(rpc_config: dict[str, Any]) -> Any:
    """Connect + login via odoorpc-toolbox from the playbook's resolved rpc config."""
    try:
        from odoorpc_toolbox import ODOO
    except ImportError as exc:
        raise RuntimeError(
            "odoorpc-toolbox is not installed — install the RPC extra: uv pip install 'odoodev-equitania[rpc]'"
        ) from exc

    host = str(rpc_config.get("host", "") or "")
    if not host:
        raise ValueError("rpc.execute: no host configured (playbook 'rpc:' section or ODOO_URL in env_file)")

    protocol = str(rpc_config.get("protocol", "") or "")
    if host.startswith("https://"):
        host = host[len("https://") :]
        protocol = protocol or "jsonrpc+ssl"
    elif host.startswith("http://"):
        host = host[len("http://") :]
    host = host.rstrip("/")
    protocol = protocol or "jsonrpc"

    default_port = 443 if protocol == "jsonrpc+ssl" else 8069
    port = int(rpc_config.get("port") or default_port)
    db = str(rpc_config.get("db", "") or "")
    user = str(rpc_config.get("user", "") or "")
    password = str(rpc_config.get("password", "") or "")
    if not db or not user or not password:
        raise ValueError(
            "rpc.execute: incomplete credentials — need db, user and password "
            "(playbook 'rpc:' section or ODOO_DATABASE/ODOO_USER/ODOO_PASSWORD in env_file)"
        )

    odoo = ODOO(host=host, protocol=protocol, port=port)
    odoo.login(db, user, password)
    return odoo


@_timed
def handle_rpc_execute(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Execute one declarative Odoo RPC operation.

    Forms:
      - ``model`` + ``method`` (+ ``args``/``kwargs``): direct ``execute_kw``.
      - ``model`` + ``domain`` + ``values``: search matching ids, then ``write``.
      - ``model`` + ``domain`` + ``method``: search matching ids, call method on them.
    """
    command = "rpc.execute"
    model = _require(args, "model", command)
    method = str(args.get("method", "") or "")
    domain = args.get("domain")
    values = args.get("values")
    call_args = list(args.get("args") or [])
    call_kwargs = dict(args.get("kwargs") or {})

    if not method and not (domain is not None and values):
        return _step_error(command, command, f"{command}: provide 'method', or 'domain' + 'values'", 0)

    rpc_config = args.get("_rpc_config") or {}
    odoo = _connect_rpc(rpc_config)

    if domain is not None:
        if not isinstance(domain, list):
            return _step_error(command, command, f"{command}: 'domain' must be a list", 0)
        ids = odoo.execute_kw(model, "search", [domain], {})
        if not ids:
            return _step_ok(command, command, f"{model}: no records match the domain — nothing to do", 0, count=0)
        effective_method = method or "write"
        rpc_args: list[Any] = [ids]
        if values is not None:
            rpc_args.append(values)
        rpc_args.extend(call_args)
        result = odoo.execute_kw(model, effective_method, rpc_args, call_kwargs)
        return _step_ok(
            command,
            command,
            f"{model}.{effective_method} on {len(ids)} record(s)",
            0,
            count=len(ids),
            result=repr(result)[:200],
        )

    result = odoo.execute_kw(model, method, call_args, call_kwargs)
    return _step_ok(
        command,
        command,
        f"{model}.{method} executed",
        0,
        result=repr(result)[:200],
    )


# =============================================================================
# Handler registry (merged into PlaybookRunner alongside COMMAND_HANDLERS)
# =============================================================================

SERVER_COMMAND_HANDLERS: dict[str, Any] = {
    "container.stop": handle_container_stop,
    "container.start": handle_container_start,
    "server.backup": handle_server_backup,
    "server.rebuild": handle_server_rebuild,
    "server.restore": handle_server_restore,
    "server.neutralize": handle_server_neutralize,
    "server.update-all": handle_server_update_all,
    "server.verify": handle_server_verify,
    "sql.execute": handle_sql_execute,
    "rpc.execute": handle_rpc_execute,
}
