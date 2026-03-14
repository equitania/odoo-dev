"""Non-interactive command handlers for playbook automation.

Each handler wraps a core function, accepts a VersionConfig and args dict,
and returns a StepResult. No interactive prompts (confirm, console.input)
are used — all handlers are designed for unattended execution.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

from odoodev.core.playbook import StepResult
from odoodev.core.version_registry import VersionConfig

logger = logging.getLogger(__name__)


def _step_ok(name: str, command: str, message: str, duration_ms: int, **details: Any) -> StepResult:
    """Create a successful StepResult."""
    return StepResult(
        name=name,
        command=command,
        status="ok",
        message=message,
        exit_code=0,
        duration_ms=duration_ms,
        details=dict(details),
    )


def _step_error(name: str, command: str, message: str, duration_ms: int, exit_code: int = 1) -> StepResult:
    """Create an error StepResult."""
    return StepResult(
        name=name,
        command=command,
        status="error",
        message=message,
        exit_code=exit_code,
        duration_ms=duration_ms,
    )


def _timed(func: Callable) -> Callable:
    """Decorator that measures execution time and catches exceptions.

    Wrapped handlers receive (version_cfg, args) and must return StepResult.
    If an exception occurs, it is caught and returned as an error StepResult.
    """

    def wrapper(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
        start = time.monotonic()
        try:
            result = func(version_cfg, args)
            # Inject duration if the handler returned 0ms (placeholder)
            if result.duration_ms == 0:
                duration_ms = int((time.monotonic() - start) * 1000)
                result = StepResult(
                    name=result.name,
                    command=result.command,
                    status=result.status,
                    message=result.message,
                    exit_code=result.exit_code,
                    duration_ms=duration_ms,
                    details=result.details,
                )
            return result
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            cmd_name = getattr(func, "_command_name", func.__name__)
            return _step_error(cmd_name, cmd_name, str(exc), duration_ms)

    return wrapper


# --- Helper: load .env for a version ---


def _load_env_vars(version_cfg: VersionConfig) -> dict[str, str]:
    """Load .env file for the version (non-interactive)."""
    env_file = os.path.join(version_cfg.paths.native_dir, ".env")
    env_vars: dict[str, str] = {}
    if not os.path.exists(env_file):
        return env_vars
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    return env_vars


def _get_db_params(version_cfg: VersionConfig, env_vars: dict[str, str] | None = None) -> dict[str, Any]:
    """Get database connection parameters."""
    if env_vars is None:
        env_vars = {}
    return {
        "host": env_vars.get("PGHOST", "localhost"),
        "port": int(env_vars.get("DB_PORT", str(version_cfg.ports.db))),
        "user": env_vars.get("PGUSER", "ownerp"),
    }


# =============================================================================
# Docker handlers
# =============================================================================


@_timed
def handle_docker_up(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Start Docker Compose services."""
    from odoodev.core.docker_compose import compose_up

    native_dir = version_cfg.paths.native_dir
    rc = compose_up(native_dir, detach=True)
    if rc == 0:
        return _step_ok("docker.up", "docker.up", "Docker services started", 0)
    return _step_error("docker.up", "docker.up", f"docker compose up failed (exit {rc})", 0, exit_code=rc)


@_timed
def handle_docker_down(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Stop Docker Compose services."""
    from odoodev.core.docker_compose import compose_down

    native_dir = version_cfg.paths.native_dir
    rc = compose_down(native_dir)
    if rc == 0:
        return _step_ok("docker.down", "docker.down", "Docker services stopped", 0)
    return _step_error("docker.down", "docker.down", f"docker compose down failed (exit {rc})", 0, exit_code=rc)


@_timed
def handle_docker_status(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Show Docker Compose service status."""
    from odoodev.core.docker_compose import compose_ps

    native_dir = version_cfg.paths.native_dir
    rc = compose_ps(native_dir)
    if rc == 0:
        return _step_ok("docker.status", "docker.status", "Docker status displayed", 0)
    return _step_error("docker.status", "docker.status", f"docker compose ps failed (exit {rc})", 0, exit_code=rc)


# =============================================================================
# Git / repos handlers
# =============================================================================


@_timed
def handle_pull(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Pull (update) all existing repositories."""
    from odoodev.commands.repos import _collect_all_repos, _find_repos_config, _load_repos_config
    from odoodev.core.git_ops import set_ssh_key, update_repo

    config_path_arg = args.get("config")
    verbose = args.get("verbose", False)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    # Find repos config
    config_path = config_path_arg or _find_repos_config(version_cfg)
    if not config_path:
        return _step_error("pull", "pull", f"No repos.yaml found for v{version_cfg.version}", 0)

    config = _load_repos_config(config_path)
    branch = config.get("branch", "develop")
    base_path = config.get("paths", {}).get("base", version_cfg.paths.base_expanded)
    base_path = os.path.expanduser(base_path)

    ssh_key = config.get("ssh_key")
    if ssh_key:
        set_ssh_key(ssh_key)

    updated = 0
    failed = 0

    # Server repo
    server_config = config.get("server", {})
    server_path = os.path.join(base_path, server_config.get("path", version_cfg.paths.server_subdir))
    if os.path.isdir(server_path):
        if update_repo(server_path, branch):
            updated += 1
        else:
            failed += 1

    # Addon repos
    all_repos = _collect_all_repos(config)
    for repo in all_repos:
        repo_path = repo.get("path", "")
        full_path = os.path.join(base_path, repo_path)
        if os.path.isdir(full_path):
            if update_repo(full_path, branch):
                updated += 1
            else:
                failed += 1

    if failed > 0:
        return _step_error("pull", "pull", f"{failed} repositories failed to update", 0)
    return _step_ok("pull", "pull", f"{updated} repositories updated", 0, updated=updated)


@_timed
def handle_repos(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Clone/update repositories and generate Odoo configuration."""
    from odoodev.commands.repos import (
        _collect_all_repos,
        _find_repos_config,
        _generate_config,
        _load_repos_config,
        _process_repos,
    )
    from odoodev.core.git_ops import (
        check_repo_access,
        clone_repo_with_progress,
        set_ssh_key,
        update_repo,
        verify_all_repo_access,
    )

    config_path_arg = args.get("config")
    config_only = args.get("config-only", args.get("config_only", False))
    server_only = args.get("server-only", args.get("server_only", False))
    skip_access_check = args.get("skip-access-check", args.get("skip_access_check", False))
    verbose = args.get("verbose", False)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    config_path = config_path_arg or _find_repos_config(version_cfg)
    if not config_path:
        return _step_error("repos", "repos", f"No repos.yaml found for v{version_cfg.version}", 0)

    config = _load_repos_config(config_path)
    branch = config.get("branch", "develop")
    base_path = config.get("paths", {}).get("base", version_cfg.paths.base_expanded)
    base_path = os.path.expanduser(base_path)

    ssh_key = config.get("ssh_key")
    if ssh_key:
        set_ssh_key(ssh_key)

    # Config-only mode
    if config_only:
        all_paths, repo_metadata = _process_repos(config, base_path, branch, set())
        _generate_config(config, version_cfg, all_paths, repo_metadata)
        return _step_ok("repos", "repos", "Odoo config regenerated (config-only)", 0)

    # Access check
    accessible_paths: set[str] = set()
    if not skip_access_check:
        all_repos = _collect_all_repos(config)
        if all_repos:
            accessible, inaccessible = verify_all_repo_access(all_repos)
            accessible_paths = {r.get("path", "") for r in accessible}

    # Server
    server_config = config.get("server", {})
    server_path = os.path.join(base_path, server_config.get("path", version_cfg.paths.server_subdir))
    server_url = server_config.get("git_url", version_cfg.git.server_url)

    if os.path.isdir(server_path):
        update_repo(server_path, branch)
    else:
        if not skip_access_check and not check_repo_access(server_url, timeout=15):
            return _step_error("repos", "repos", f"Cannot access server repository: {server_url}", 0)
        clone_repo_with_progress(server_url, server_path, branch)

    if server_only:
        return _step_ok("repos", "repos", "Server updated", 0)

    # Process repos
    all_paths, repo_metadata = _process_repos(config, base_path, branch, accessible_paths)
    _generate_config(config, version_cfg, all_paths, repo_metadata)

    return _step_ok("repos", "repos", f"Repositories processed for v{version_cfg.version}", 0)


# =============================================================================
# Start / stop handlers
# =============================================================================


@_timed
def handle_start(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Start Odoo as a background subprocess (non-blocking).

    Unlike the interactive ``start`` command, this handler:
    - Launches Odoo via ``subprocess.Popen`` (detached)
    - Waits 3 seconds and checks if the process is still running
    - Returns immediately with the PID
    """
    from odoodev.commands.start import _find_odoo_config, _load_env_file, _set_environment
    from odoodev.core.prerequisites import check_port
    from odoodev.core.venv_manager import get_venv_python

    native_dir = version_cfg.paths.native_dir
    odoo_dir = version_cfg.paths.server_dir
    myconfs_dir = version_cfg.paths.myconfs_dir
    venv_dir = os.path.join(native_dir, ".venv")

    # Prerequisites
    env_file = os.path.join(native_dir, ".env")
    if not os.path.exists(env_file):
        return _step_error("start", "start", f"No .env file found at {env_file}", 0)

    if not os.path.isdir(venv_dir):
        return _step_error("start", "start", f"No venv found at {venv_dir}", 0)

    odoo_bin = os.path.join(odoo_dir, "odoo-bin")
    if not os.path.exists(odoo_bin):
        return _step_error("start", "start", f"odoo-bin not found at {odoo_bin}", 0)

    config_path = _find_odoo_config(myconfs_dir)
    if not config_path:
        return _step_error("start", "start", f"No Odoo config found in {myconfs_dir}", 0)

    # Check DB port — start Docker if needed
    env_vars = _load_env_file(env_file)
    db_port = int(env_vars.get("DB_PORT", str(version_cfg.ports.db)))
    if not check_port("localhost", db_port):
        from odoodev.core.docker_compose import compose_up

        compose_up(native_dir, detach=True)
        time.sleep(5)
        if not check_port("localhost", db_port):
            return _step_error("start", "start", f"PostgreSQL not accessible on port {db_port}", 0)

    env = _set_environment(env_vars)
    python = get_venv_python(venv_dir)

    mode = args.get("mode", "normal")
    cmd = [python, odoo_bin, "-c", config_path]

    if mode == "dev":
        cmd.append("--dev=all")
    elif mode == "test":
        cmd.extend(["--test-enable", "--stop-after-init"])

    extra_args = args.get("extra_args", [])
    if extra_args:
        cmd.extend(extra_args)

    # Launch as background process
    log_file = os.path.join(native_dir, "odoo.log")
    with open(log_file, "a", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=odoo_dir,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    # Wait and verify process is alive
    time.sleep(3)
    if proc.poll() is not None:
        return _step_error(
            "start",
            "start",
            f"Odoo process exited immediately (exit code: {proc.returncode}). Check {log_file}",
            0,
            exit_code=proc.returncode,
        )

    return _step_ok("start", "start", f"Odoo started (PID {proc.pid}, mode={mode})", 0, pid=proc.pid, log=log_file)


@_timed
def handle_stop(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Stop Odoo process and optionally Docker services."""
    from odoodev.core.docker_compose import compose_down
    from odoodev.core.process_manager import find_odoo_process, stop_process

    keep_docker = args.get("keep-docker", args.get("keep_docker", False))
    force = args.get("force", False)

    odoo_port = version_cfg.ports.odoo
    pids = find_odoo_process(odoo_port)

    stopped = 0
    if pids:
        for pid in pids:
            if stop_process(pid, timeout=5, force=force):
                stopped += 1

    if not keep_docker:
        compose_down(version_cfg.paths.native_dir)

    if pids and stopped == 0:
        return _step_error("stop", "stop", "Failed to stop Odoo processes", 0)

    msg_parts = []
    if pids:
        msg_parts.append(f"{stopped} Odoo process(es) stopped")
    else:
        msg_parts.append("No Odoo process found")
    if not keep_docker:
        msg_parts.append("Docker services stopped")

    return _step_ok("stop", "stop", "; ".join(msg_parts), 0, stopped_pids=stopped)


# =============================================================================
# Database handlers
# =============================================================================


@_timed
def handle_db_list(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """List all databases."""
    from odoodev.core.database import list_databases

    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    databases = list_databases(host=params["host"], port=params["port"], user=params["user"])
    return _step_ok("db.list", "db.list", f"{len(databases)} database(s) found", 0, databases=databases)


@_timed
def handle_db_backup(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Create a database backup (SQL or ZIP)."""
    import shutil
    import tempfile
    from datetime import datetime

    from odoodev.core.database import backup_database_sql, create_backup_zip, database_exists, get_filestore_path

    name = args.get("name")
    if not name:
        return _step_error("db.backup", "db.backup", "Missing required arg: 'name'", 0)

    backup_type = args.get("type", "sql")
    output_dir = os.path.abspath(args.get("output", "."))

    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    if not database_exists(name, host=params["host"], port=params["port"], user=params["user"]):
        return _step_error("db.backup", "db.backup", f"Database '{name}' does not exist", 0)

    os.makedirs(output_dir, exist_ok=True)
    date_suffix = datetime.now().strftime("%y%m%d")

    if backup_type == "sql":
        output_file = os.path.join(output_dir, f"{name}_{date_suffix}.sql")
        if not backup_database_sql(name, output_file, **params):
            return _step_error("db.backup", "db.backup", "SQL backup failed", 0)
        return _step_ok("db.backup", "db.backup", f"Backup created: {output_file}", 0, file=output_file)

    # ZIP backup
    tmp_dir = tempfile.mkdtemp(prefix="odoodev_backup_")
    try:
        sql_path = os.path.join(tmp_dir, "dump.sql")
        if not backup_database_sql(name, sql_path, **params):
            return _step_error("db.backup", "db.backup", "Database dump failed", 0)

        filestore_path = get_filestore_path(version_cfg.version, name)
        fs_dir = filestore_path if os.path.isdir(filestore_path) else None

        output_file = os.path.join(output_dir, f"{name}_{date_suffix}.zip")
        if not create_backup_zip(sql_path, output_file, fs_dir):
            return _step_error("db.backup", "db.backup", "ZIP creation failed", 0)

        return _step_ok("db.backup", "db.backup", f"Backup created: {output_file}", 0, file=output_file)
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except OSError as e:
            logger.warning("Could not remove temp directory %s: %s", tmp_dir, e)


@_timed
def handle_db_restore(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Restore a database from backup file (non-interactive)."""
    import shutil
    import tempfile

    from odoodev.core.database import (
        copy_filestore,
        create_database,
        deactivate_cloud,
        deactivate_cronjobs,
        detect_backup_type,
        drop_database,
        extract_backup,
        get_filestore_path,
        restore_database,
    )

    name = args.get("name")
    backup_file = args.get("backup-file", args.get("backup_file"))
    if not name or not backup_file:
        return _step_error("db.restore", "db.restore", "Missing required args: 'name' and 'backup-file'", 0)

    backup_file = os.path.abspath(backup_file)
    if not os.path.exists(backup_file):
        return _step_error("db.restore", "db.restore", f"Backup file not found: {backup_file}", 0)

    do_drop = args.get("drop", True)
    deactivate_cron_flag = args.get("deactivate-cron", args.get("deactivate_cron", True))
    deactivate_cloud_flag = args.get("deactivate-cloud-integrations", args.get("deactivate_cloud_integrations", True))

    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    # Drop existing
    if do_drop:
        drop_database(name, **params)

    # Extract
    extract_path = tempfile.mkdtemp(prefix="odoodev_restore_")
    try:
        if not extract_backup(backup_file, extract_path):
            return _step_error("db.restore", "db.restore", "Backup extraction failed", 0)

        backup_info = detect_backup_type(extract_path)
        if not backup_info:
            return _step_error("db.restore", "db.restore", "Could not detect backup structure", 0)

        sql_file = backup_info["sql_file"]
        filestore_src = backup_info.get("filestore")

        if not create_database(name, **params):
            return _step_error("db.restore", "db.restore", f"Failed to create database '{name}'", 0)

        if not restore_database(name, sql_file, **params):
            return _step_error("db.restore", "db.restore", "Database restore failed", 0)

        # Filestore
        if filestore_src and os.path.isdir(filestore_src):
            filestore_dest = get_filestore_path(version_cfg.version, name)
            copy_filestore(filestore_src, filestore_dest)

        # Post-restore
        if deactivate_cron_flag:
            deactivate_cronjobs(name, **params)
        if deactivate_cloud_flag:
            deactivate_cloud(name, **params)

        return _step_ok("db.restore", "db.restore", f"Database '{name}' restored", 0)

    finally:
        try:
            shutil.rmtree(extract_path)
        except OSError as e:
            logger.warning("Could not remove temp directory %s: %s", extract_path, e)


@_timed
def handle_db_drop(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Drop a database (no confirmation — automation mode)."""
    from odoodev.core.database import drop_database

    name = args.get("name")
    if not name:
        return _step_error("db.drop", "db.drop", "Missing required arg: 'name'", 0)

    env_vars = _load_env_vars(version_cfg)
    params = _get_db_params(version_cfg, env_vars)

    if drop_database(name, host=params["host"], port=params["port"], user=params["user"]):
        return _step_ok("db.drop", "db.drop", f"Database '{name}' dropped", 0)
    return _step_error("db.drop", "db.drop", f"Failed to drop database '{name}'", 0)


# =============================================================================
# Environment / venv handlers
# =============================================================================


@_timed
def handle_env_check(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Check if .env file exists and is complete."""
    native_dir = version_cfg.paths.native_dir
    env_file = os.path.join(native_dir, ".env")

    if not os.path.exists(env_file):
        return _step_error("env.check", "env.check", f"No .env file found at {env_file}", 0)

    from dotenv import dotenv_values

    values = dotenv_values(env_file)
    required_keys = [
        "ENV_NAME",
        "ODOO_VERSION",
        "PLATFORM",
        "DEV_USER",
        "DB_PORT",
        "PGUSER",
        "PGPASSWORD",
        "ODOO_PORT",
        "GEVENT_PORT",
        "POSTGRES_VERSION",
        "DOCKER_PLATFORM",
    ]
    missing = [k for k in required_keys if k not in values or not values[k]]
    if missing:
        return _step_error("env.check", "env.check", f"Missing variables: {', '.join(missing)}", 0)

    return _step_ok("env.check", "env.check", f".env is complete ({len(values)} variables)", 0)


@_timed
def handle_venv_check(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Check venv status and requirements freshness."""
    venv_dir = os.path.join(version_cfg.paths.native_dir, ".venv")
    requirements = os.path.join(version_cfg.paths.native_dir, "requirements.txt")

    if not os.path.exists(venv_dir):
        return _step_error("venv.check", "venv.check", f"No venv found at {venv_dir}", 0)

    issues: list[str] = []

    # Check Python binary
    python_bin = os.path.join(venv_dir, "bin", "python3")
    if not os.path.exists(python_bin):
        issues.append("Python binary not found in venv")

    # Check requirements hash
    if os.path.exists(requirements):
        from odoodev.core.venv_manager import check_requirements_changed

        if check_requirements_changed(venv_dir, requirements):
            issues.append("requirements.txt has changed since last install")

    if issues:
        return _step_error("venv.check", "venv.check", "; ".join(issues), 0)

    return _step_ok("venv.check", "venv.check", f"Venv OK at {venv_dir}", 0)


@_timed
def handle_venv_setup(version_cfg: VersionConfig, args: dict[str, Any]) -> StepResult:
    """Create or update virtual environment."""
    from odoodev.core.venv_manager import create_venv, install_requirements, store_requirements_hash

    venv_dir = os.path.join(version_cfg.paths.native_dir, ".venv")
    requirements = os.path.join(version_cfg.paths.native_dir, "requirements.txt")

    prompt = f"odoo-v{version_cfg.version}"

    if not create_venv(venv_dir, version_cfg.python, prompt):
        return _step_error("venv.setup", "venv.setup", "Failed to create venv", 0)

    if os.path.exists(requirements):
        if not install_requirements(venv_dir, requirements):
            return _step_error("venv.setup", "venv.setup", "Failed to install requirements", 0)
        store_requirements_hash(venv_dir, requirements)

    return _step_ok("venv.setup", "venv.setup", f"Venv ready at {venv_dir}", 0)


# =============================================================================
# Handler registry
# =============================================================================

COMMAND_HANDLERS: dict[str, Callable[[VersionConfig, dict[str, Any]], StepResult]] = {
    "docker.up": handle_docker_up,
    "docker.down": handle_docker_down,
    "docker.status": handle_docker_status,
    "pull": handle_pull,
    "repos": handle_repos,
    "start": handle_start,
    "stop": handle_stop,
    "db.list": handle_db_list,
    "db.backup": handle_db_backup,
    "db.restore": handle_db_restore,
    "db.drop": handle_db_drop,
    "env.check": handle_env_check,
    "venv.check": handle_venv_check,
    "venv.setup": handle_venv_setup,
}
