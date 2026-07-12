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
import shutil
import tempfile
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
    """
    from odoodev.core.database import backup_database_sql, create_backup_tar_zst, pg_exec_container

    command = "server.backup"
    db_container = _require(args, "db_container", command)
    db_name = _require(args, "db_name", command)
    owner = str(args.get("owner", "") or "ownerp")
    backup_dir = os.path.expanduser(_require(args, "backup_dir", command))
    level = int(args.get("compression_level", 5))
    only_sql = _as_bool(args.get("only_sql"), default=False)

    if not os.path.isdir(backup_dir):
        return _step_error(command, command, f"Backup directory does not exist: {backup_dir}", 0)

    filestore_path: str | None = None
    if not only_sql:
        data_dir = _resolve_data_dir(args, command)
        filestore_path = os.path.join(data_dir, "filestore", db_name)
        if not os.path.isdir(filestore_path):
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
    output_path = os.path.join(backup_dir, f"{db_name}_{data_container}_dockerbackup_{timestamp}{suffix}.tar.zst")

    temp_dir = tempfile.mkdtemp(prefix="odoodev_server_backup_", dir=backup_dir)
    try:
        dump_path = os.path.join(temp_dir, "dump.sql")
        with pg_exec_container(db_container):
            if not backup_database_sql(db_name, dump_path, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner):
                return _step_error(command, command, f"pg_dump of '{db_name}' via '{db_container}' failed", 0)

        if not create_backup_tar_zst(dump_path, output_path, filestore_path=filestore_path, level=level):
            return _step_error(command, command, f"Creating {output_path} failed", 0)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    return _step_ok(
        command,
        command,
        f"Backup created: {output_path} ({size_mb:.1f} MB)",
        0,
        backup_file=output_path,
        database=db_name,
    )


# =============================================================================
# server.restore — drop/create, dump restore, filestore swap, psql sanitize
# =============================================================================


def _resolve_backup_file(args: dict[str, Any], command: str) -> str:
    """Resolve the restore input from ``backup_source`` (file | newest_in_dir)."""
    from odoodev.core.docker_exec import find_latest_backup

    source = args.get("backup_source") or {}
    if isinstance(source, str):
        source = {"mode": "file", "path": source}
    if not isinstance(source, dict):
        raise ValueError(f"{command}: 'backup_source' must be a mapping or a file path")

    mode = str(source.get("mode", "") or ("file" if source.get("path") else "newest_in_dir"))
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

    raise ValueError(f"{command}: backup_source.mode must be 'file' or 'newest_in_dir', got '{mode}'")


@_timed
def handle_server_restore(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Restore a backup into a target's DB container, swap the filestore, sanitize.

    The target's Odoo container must be stopped (use a ``container.stop`` step
    first). Sanitize flags run the same ``core.database`` functions as the CLI
    ``db restore`` pipeline — psql-based steps only. ``odoo-bin neutralize``
    needs a *running* Odoo container and is therefore the separate
    ``server.neutralize`` step, placed after ``container.start``.
    """
    from odoodev.core.database import (
        check_restore_space,
        create_database,
        deactivate_cronjobs,
        detect_backup_type,
        drop_database,
        extract_backup,
        neutralize_bank_sync,
        pg_exec_container,
        purge_master_data,
        purge_transactional_data,
        restore_database,
        wipe_database,
    )
    from odoodev.core.database import (
        move_filestore as move_filestore_fn,
    )
    from odoodev.core.docker_exec import chown_recursive, docker_container_running

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

    temp_parent = os.path.expanduser(str(args.get("temp_dir", "") or "")) or os.path.dirname(backup_file)
    if check_space:
        ok_space, space_msg, _needed = check_restore_space(backup_file, temp_parent, filestore_dest)
        if not ok_space:
            return _step_error(command, command, space_msg, 0)

    extract_path = tempfile.mkdtemp(prefix="odoodev_server_restore_", dir=temp_parent)
    try:
        if not extract_backup(backup_file, extract_path):
            return _step_error(command, command, f"Extraction of {backup_file} failed", 0)

        detected = detect_backup_type(extract_path)
        if not detected or not detected.get("sql_file"):
            return _step_error(command, command, f"No dump.sql found in {backup_file}", 0)
        sql_file = detected["sql_file"]
        filestore_src = detected.get("filestore")

        with pg_exec_container(db_container):
            if drop and not drop_database(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner):
                return _step_error(command, command, f"Dropping '{db_name}' failed", 0)
            if not create_database(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner, template=template):
                return _step_error(command, command, f"Creating '{db_name}' (TEMPLATE {template}) failed", 0)
            if not restore_database(db_name, sql_file, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner):
                return _step_error(command, command, f"Restoring dump into '{db_name}' failed", 0)

        # Filestore swap (hard error on missing source — a DB without its
        # filestore is a dangerous half-mirrored state).
        if filestore_src:
            if os.path.isdir(filestore_dest):
                shutil.rmtree(filestore_dest)
            if os.path.isdir(sessions_dir):
                shutil.rmtree(sessions_dir)
            if not move_filestore_fn(filestore_src, filestore_dest):
                return _step_error(command, command, f"Moving filestore to {filestore_dest} failed", 0)
            if not chown_recursive(filestore_dest, uid=chown_uid, gid=chown_gid):
                return _step_error(command, command, f"chown -R {chown_uid}:{chown_gid} {filestore_dest} failed", 0)
        elif not _as_bool(args.get("allow_missing_filestore"), default=False):
            return _step_error(
                command,
                command,
                f"Backup {backup_file} contains no filestore — refusing a half-mirrored restore "
                f"(set allow_missing_filestore: true for SQL-only backups)",
                0,
            )
    finally:
        shutil.rmtree(extract_path, ignore_errors=True)

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
            ok = deactivate_cronjobs(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("deactivate_cron")
        if flag("neutralize"):
            # psql portion only; odoo-bin neutralize is the server.neutralize step.
            ok = neutralize_bank_sync(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("neutralize_bank_sync")
        if flag("anonymize"):
            from odoodev.core.database import anonymize_database

            ok = anonymize_database(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
            (sanitize_done if ok else sanitize_failed).append("anonymize")
        if flag("wipe"):
            ok = wipe_database(db_name, host=_UNUSED_HOST, port=_UNUSED_PORT, user=owner)
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

    sanitize_info = f" (sanitize: {', '.join(sanitize_done)})" if sanitize_done else ""
    return _step_ok(
        command,
        command,
        f"Database '{db_name}' restored from {os.path.basename(backup_file)}{sanitize_info}",
        0,
        backup_file=backup_file,
        database=db_name,
        sanitize_steps=sanitize_done,
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
    "server.restore": handle_server_restore,
    "server.neutralize": handle_server_neutralize,
    "server.update-all": handle_server_update_all,
    "sql.execute": handle_sql_execute,
    "rpc.execute": handle_rpc_execute,
}
