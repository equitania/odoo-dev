"""PostgreSQL database operations for Odoo development."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from faker import Faker

logger = logging.getLogger(__name__)

# Default credentials — kept as module constants for signature defaults.
# Actual values come from global config at runtime via _get_default_credentials().
DEFAULT_DB_USER = "ownerp"
DEFAULT_DB_PASSWORD = "CHANGE_AT_FIRST"  # noqa: S105 — placeholder, warned at runtime
DEFAULT_DB_HOST = "localhost"

_insecure_default_warned = False


def _warn_once_on_placeholder(password: str) -> None:
    """Emit a one-shot Rich-panel warning when the placeholder password is in use.

    Non-blocking. ``odoodev start`` performs an additional, blocking check via
    ``_check_placeholder_password`` so the user cannot miss it.
    """
    global _insecure_default_warned
    if _insecure_default_warned or password != DEFAULT_DB_PASSWORD:
        return
    _insecure_default_warned = True

    from odoodev.output import print_warning

    print_warning(
        f"PostgreSQL credentials fall back to the placeholder password {DEFAULT_DB_PASSWORD!r} — "
        "run 'odoodev setup' to configure a real password."
    )


def _get_default_credentials() -> tuple[str, str]:
    """Get default database credentials from global config.

    Falls back to module-level constants if config loading fails.
    """
    try:
        from odoodev.core.global_config import load_global_config

        cfg = load_global_config()
        user, password = cfg.database.user, cfg.database.password
    except (ImportError, AttributeError, KeyError, OSError):
        user, password = DEFAULT_DB_USER, DEFAULT_DB_PASSWORD
    _warn_once_on_placeholder(password)
    return user, password


def _get_pg_env(host: str = DEFAULT_DB_HOST, port: int = 18432) -> dict[str, str]:
    """Get environment variables for PostgreSQL commands.

    Prefers .pgpass authentication. Falls back to PGPASSWORD env var
    only if .pgpass does not exist.
    """
    env = os.environ.copy()
    env["PGHOST"] = host
    env["PGPORT"] = str(port)

    pgpass_path = os.path.join(os.path.expanduser("~"), ".pgpass")
    if not os.path.exists(pgpass_path):
        # Fallback: use PGPASSWORD only when .pgpass is unavailable
        _, default_password = _get_default_credentials()
        pgpassword = os.environ.get("PGPASSWORD", default_password)
        _warn_once_on_placeholder(pgpassword)
        env["PGPASSWORD"] = pgpassword
    else:
        # .pgpass exists — remove PGPASSWORD to let psql use .pgpass
        env.pop("PGPASSWORD", None)

    return env


# --- psql/pg_dump execution mode: host CLI tools vs. container exec fallback ---
#
# On migration servers PostgreSQL runs only inside the Docker container and the
# host has no psql/pg_dump (or Debian ships an older client that refuses newer
# servers). When host tools are missing, all pg client commands are executed
# inside the container publishing the target port instead.

PG_EXEC_HOST = "host"
PG_EXEC_CONTAINER = "container"
PG_EXEC_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PgExecMode:
    """How pg client tools (psql/pg_dump/createdb/dropdb) are executed."""

    kind: str  # PG_EXEC_HOST | PG_EXEC_CONTAINER | PG_EXEC_UNAVAILABLE
    container_name: str = ""
    cli: str = "docker"  # container runtime binary for the exec prefix


class PgToolsUnavailableError(RuntimeError):
    """Neither host pg client tools nor a running database container were found."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(
            f"No psql/pg_dump found on this host, and no running PostgreSQL container "
            f"was found for {host}:{port}. Install postgresql-client "
            f"(apt-get install postgresql-client / brew install libpq), "
            f"or start the database container (odoodev docker up)."
        )


_pg_exec_cache: dict[int, PgExecMode] = {}
_pg_exec_info_printed: set[int] = set()


@dataclass(frozen=True)
class PgExecTarget:
    """Explicit container-exec target for psql/pg_dump/createdb/dropdb.

    Bypasses host-tool detection and port-based container discovery entirely.
    Used by server-mode playbooks where the PostgreSQL container publishes no
    host port and is only reachable via ``docker exec``.
    """

    container: str
    cli: str = "docker"


_pg_exec_target: ContextVar[PgExecTarget | None] = ContextVar("_pg_exec_target", default=None)


@contextmanager
def pg_exec_container(container: str, cli: str = "docker") -> Iterator[None]:
    """Force all pg client calls inside this block through ``<cli> exec -i <container>``.

    The ``host``/``port`` arguments of the wrapped database functions become inert
    placeholders (container exec connects via the Unix socket); only ``user`` still
    matters (passed as ``-U``). The override is context-local and never cached, so
    two different containers can be targeted sequentially in one process without
    cross-contamination.
    """
    token = _pg_exec_target.set(PgExecTarget(container=container, cli=cli))
    try:
        yield
    finally:
        _pg_exec_target.reset(token)


def clear_pg_exec_cache() -> None:
    """Clear the module-level PgExecMode cache and info flags. Test helper."""
    _pg_exec_cache.clear()
    _pg_exec_info_printed.clear()


def _host_pg_tools_available() -> bool:
    return shutil.which("psql") is not None and shutil.which("pg_dump") is not None


def resolve_pg_exec_mode(port: int) -> PgExecMode:
    """Decide how to run psql/pg_dump/createdb/dropdb for a given port.

    Priority: an active ``pg_exec_container()`` block (explicit target, never
    cached) > ``ODOODEV_PG_EXEC`` override ("host"/"container") > host CLI tools
    present > a running container publishing ``port`` (via the configured container
    runtime). Cached per port for the process lifetime — tests that vary
    shutil.which/backend behaviour must call ``clear_pg_exec_cache()`` in between.
    """
    forced = _pg_exec_target.get()
    if forced is not None:
        return PgExecMode(kind=PG_EXEC_CONTAINER, container_name=forced.container, cli=forced.cli)

    override = os.environ.get("ODOODEV_PG_EXEC", "auto").lower()
    if override == "host":
        return PgExecMode(kind=PG_EXEC_HOST)

    if port in _pg_exec_cache:
        return _pg_exec_cache[port]

    if override != "container" and _host_pg_tools_available():
        mode = PgExecMode(kind=PG_EXEC_HOST)
        _pg_exec_cache[port] = mode
        return mode

    from odoodev.core.container_backend import get_active_backend

    backend = get_active_backend()
    container_name = backend.find_container_by_port(port)
    if container_name:
        mode = PgExecMode(kind=PG_EXEC_CONTAINER, container_name=container_name, cli=backend.cli)
        if port not in _pg_exec_info_printed:
            _pg_exec_info_printed.add(port)
            from odoodev.output import print_info

            print_info(
                f"Host psql/pg_dump not found — running database commands via "
                f"{backend.name} container '{container_name}'"
            )
    else:
        mode = PgExecMode(kind=PG_EXEC_UNAVAILABLE)

    _pg_exec_cache[port] = mode
    return mode


def _pg_base_cmd(tool: str, mode: PgExecMode, user: str, host: str, port: int) -> list[str]:
    """Build the invocation prefix for a pg client tool (psql/pg_dump/dropdb/createdb).

    Host mode connects over TCP as before. Container mode execs the tool inside
    the database container without ``-h``/``-p``: there psql connects via the
    Unix socket, which the stock postgres image trusts unconditionally
    (pg_hba.conf ``local all all trust``), so no PGPASSWORD is needed either.
    """
    if mode.kind == PG_EXEC_HOST:
        return [tool, "-U", user, "-h", host, "-p", str(port)]
    if mode.kind == PG_EXEC_CONTAINER:
        return [mode.cli, "exec", "-i", mode.container_name, tool, "-U", user]
    raise PgToolsUnavailableError(host, port)


def _pg_exec_env(mode: PgExecMode, host: str, port: int) -> dict[str, str]:
    if mode.kind == PG_EXEC_HOST:
        return _get_pg_env(host, port)
    return os.environ.copy()  # container exec needs no PG* vars (socket trust auth)


def _run_psql(
    command: str,
    db: str | None = None,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, str]:
    """Execute a psql command.

    Returns:
        Tuple of (success, output_or_error).
    """
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("psql", mode, user, host, port)
        if db:
            cmd.extend(["-d", db])
        cmd.extend(["-c", command])
        result = subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_pg_exec_env(mode, host, port),
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except (FileNotFoundError, PgToolsUnavailableError) as e:
        return False, str(e)


def _run_psql_tuples(
    query: str,
    db: str | None = None,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, list[list[str]]]:
    """Execute a query with tuples-only, unaligned, tab-separated output.

    psql's default aligned format is unusable for machine parsing: embedded
    tab characters are rendered as spaces and every value is padded for
    display. ``-t -A -F <tab>`` emits exactly one line per row with literal
    tab bytes between columns; booleans print natively as ``t``/``f``.
    Column values must not contain tabs or newlines (true for the identifier
    and name columns this is used for).

    Returns:
        Tuple of (success, rows) where each row is the list of column strings.
    """
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("psql", mode, user, host, port)
        if db:
            cmd.extend(["-d", db])
        cmd.extend(["-t", "-A", "-F", "\t", "-c", query])
        result = subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_pg_exec_env(mode, host, port),
        )
        return True, [line.split("\t") for line in result.stdout.splitlines() if line]
    except subprocess.CalledProcessError:
        return False, []
    except (FileNotFoundError, PgToolsUnavailableError):
        return False, []


def database_exists(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Check if a database exists."""
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("psql", mode, user, host, port) + ["-lqt"]
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=_pg_exec_env(mode, host, port)
        )
        for line in result.stdout.split("\n"):
            parts = line.split("|")
            if parts and parts[0].strip() == db_name:
                return True
        return False
    except (subprocess.CalledProcessError, FileNotFoundError, PgToolsUnavailableError):
        return False


def list_databases(
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> list[str]:
    """List all databases.

    Returns:
        List of database names.
    """
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("psql", mode, user, host, port) + ["-lqt"]
        result = subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_pg_exec_env(mode, host, port),
        )
        databases = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split("|")
            if parts:
                name = parts[0].strip()
                if name and name not in ("", "template0", "template1", "postgres"):
                    databases.append(name)
        return sorted(databases)
    except (subprocess.CalledProcessError, FileNotFoundError, PgToolsUnavailableError):
        return []


def drop_database(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Drop a database."""
    if not database_exists(db_name, host, port, user):
        logger.info("Database %s does not exist. Skipping.", db_name)
        return True

    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("dropdb", mode, user, host, port) + [db_name]
        subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_pg_exec_env(mode, host, port),
        )
        logger.info("Database %s dropped.", db_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to drop %s: %s", db_name, e.stderr)
        return False
    except (FileNotFoundError, PgToolsUnavailableError) as e:
        logger.error("Failed to drop %s: %s", db_name, e)
        return False


def create_database(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
    template: str = "template1",
) -> bool:
    """Create a new database.

    ``template`` defaults to ``template1`` (dev behaviour); server-mode restores
    pass ``template0`` per the production runbook. The connecting ``user`` is set
    as the explicit owner.
    """
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("createdb", mode, user, host, port) + ["-T", template, "-O", user, db_name]
        subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_pg_exec_env(mode, host, port),
        )
        logger.info("Database %s created.", db_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to create %s: %s", db_name, e.stderr)
        return False
    except (FileNotFoundError, PgToolsUnavailableError) as e:
        logger.error("Failed to create %s: %s", db_name, e)
        return False


def restore_database(
    db_name: str,
    sql_file: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Restore a database from SQL file.

    The dump is piped via stdin (not ``-f``) so the file path never has to
    exist inside the container when the exec fallback is active.
    """
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("psql", mode, user, host, port) + ["-d", db_name]
        with open(sql_file, "rb") as infile:
            subprocess.run(
                cmd, check=True, stdin=infile, capture_output=True, text=True, env=_pg_exec_env(mode, host, port)
            )
        logger.info("Database %s restored from %s.", db_name, sql_file)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to restore %s: %s", db_name, e.stderr)
        return False
    except (OSError, PgToolsUnavailableError) as e:
        logger.error("Failed to restore %s: %s", db_name, e)
        return False


def get_active_connection_count(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> int:
    """Count active connections to a database (excluding our own psql session).

    Returns -1 if the query failed (e.g. PostgreSQL not reachable).
    """
    _check_identifier(db_name)
    query = f"SELECT count(*) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"
    ok, out = _run_psql(query, db="postgres", host=host, port=port, user=user)
    if not ok:
        return -1
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    return -1


def terminate_connections(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Terminate all active connections to a database via pg_terminate_backend."""
    _check_identifier(db_name)
    query = (
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"
    )
    ok, _ = _run_psql(query, db="postgres", host=host, port=port, user=user)
    return ok


def copy_database(
    src: str,
    dst: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Copy a database via ``createdb -T src dst`` (requires no active connections on src)."""
    _check_identifier(src)
    _check_identifier(dst)
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("createdb", mode, user, host, port) + ["-T", src, dst]
        subprocess.run(
            cmd,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=_pg_exec_env(mode, host, port),
        )
        logger.info("Database %s copied to %s.", src, dst)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to copy %s to %s: %s", src, dst, e.stderr)
        return False
    except (FileNotFoundError, PgToolsUnavailableError) as e:
        logger.error("Failed to copy %s to %s: %s", src, dst, e)
        return False


def rename_database(
    old_name: str,
    new_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Rename a database via ``ALTER DATABASE`` (requires no active connections)."""
    _check_identifier(old_name)
    _check_identifier(new_name)
    query = f"ALTER DATABASE {old_name} RENAME TO {new_name};"
    ok, err = _run_psql(query, db="postgres", host=host, port=port, user=user)
    if ok:
        logger.info("Database %s renamed to %s.", old_name, new_name)
    else:
        logger.error("Failed to rename %s to %s: %s", old_name, new_name, err)
    return ok


def extract_backup(backup_file: str, extract_path: str) -> bool:
    """Extract a backup file (ZIP, 7z, tar, tar.zst, gz, SQL).

    On success the extracted content is restricted to the current user —
    dumps and filestore may contain production PII before anonymization runs.

    Args:
        backup_file: Path to backup file
        extract_path: Directory to extract into

    Returns:
        True if extraction successful.
    """
    ok = _extract_backup_inner(backup_file, extract_path)
    if ok:
        _restrict_permissions(extract_path)
    return ok


def _restrict_permissions(extract_path: str) -> None:
    """Chmod extracted backup content to owner-only (dirs 0o700, files 0o600)."""
    try:
        os.chmod(extract_path, 0o700)
        for root, dirs, files in os.walk(extract_path):
            for name in dirs:
                os.chmod(os.path.join(root, name), 0o700)
            for name in files:
                os.chmod(os.path.join(root, name), 0o600)
    except OSError as e:
        logger.warning("Could not restrict permissions on %s: %s", extract_path, e)


def _extract_backup_inner(backup_file: str, extract_path: str) -> bool:
    """Format-dispatching extraction logic (see :func:`extract_backup`)."""
    os.makedirs(extract_path, exist_ok=True)

    ext = os.path.splitext(backup_file)[1].lower()

    try:
        # Zstandard-compressed tar (.tar.zst) — Equitania server stream backups
        # (container2backup v4.7.0+). Checked before splitext-based dispatch because
        # splitext("x.tar.zst") yields ".zst", which would never match below.
        if backup_file.lower().endswith(".tar.zst"):
            import tarfile

            zstd_bin = shutil.which("zstd")
            if not zstd_bin:
                logger.error(
                    "zstd not found — required to restore .tar.zst backups. "
                    "Install: brew install zstd (macOS) / apt install zstd (Linux)"
                )
                return False
            proc = subprocess.Popen(
                [zstd_bin, "-d", "-c", backup_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                # Stream mode "r|": single pass over the decompressed stream.
                # filter="data" rejects path traversal, symlinks, device files and
                # absolute paths (CWE-22, Python 3.12+ stdlib).
                with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
                    tf.extractall(extract_path, filter="data")
            finally:
                if proc.stdout:
                    proc.stdout.close()
                ret = proc.wait()
            if ret != 0:
                stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                logger.error("zstd decompression failed: %s", stderr)
                return False
            return True

        # 7z files
        if ext == ".7z":
            # Binary names vary by platform/package: 7zz (macOS brew 7zip, Debian 13+ "7zip"),
            # 7z (p7zip-full), 7za (p7zip / p7zip-full on older Debian/Ubuntu).
            for cmd_7z in ("7zz", "7z", "7za"):
                if shutil.which(cmd_7z):
                    result = subprocess.run(
                        [cmd_7z, "x", backup_file, f"-o{extract_path}"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        return True
            logger.error(
                "7z not found. Install one of: brew install 7zip (macOS), "
                "apt install 7zip (Debian 13+, provides 7zz), "
                "or apt install p7zip-full (older Debian/Ubuntu, provides 7z/7za)"
            )
            return False

        # ZIP files
        if ext == ".zip" or zipfile.is_zipfile(backup_file):
            with zipfile.ZipFile(backup_file, "r") as zf:
                # Validate all members before extraction to prevent path traversal (CWE-22)
                safe_base = os.path.normpath(os.path.abspath(extract_path))
                for member in zf.namelist():
                    member_path = os.path.normpath(os.path.abspath(os.path.join(extract_path, member)))
                    if not member_path.startswith(safe_base + os.sep) and member_path != safe_base:
                        msg = f"Zip path traversal detected: {member}"
                        raise ValueError(msg)
                zf.extractall(extract_path)
            return True

        # TAR files (incl. gzip-compressed .tar.gz — tarfile.open auto-detects compression).
        # .tar.gz must be matched explicitly: splitext yields ".gz", which would otherwise
        # fall through to the GZIP branch and be mistreated as a plain SQL dump.
        if ext in (".tar", ".tgz") or backup_file.lower().endswith(".tar.gz"):
            import tarfile

            with tarfile.open(backup_file) as tf:
                # Validate all members before extraction to prevent path traversal (CWE-22)
                safe_base = os.path.normpath(os.path.abspath(extract_path))
                for tar_member in tf.getmembers():
                    member_path = os.path.normpath(os.path.abspath(os.path.join(extract_path, tar_member.name)))
                    if not member_path.startswith(safe_base + os.sep) and member_path != safe_base:
                        msg = f"Tar path traversal detected: {tar_member.name}"
                        raise ValueError(msg)
                # filter="data" blocks symlinks, device files and absolute paths (Python 3.12+ stdlib)
                tf.extractall(extract_path, filter="data")
            return True

        # GZIP files
        if ext == ".gz":
            dump_path = os.path.join(extract_path, "dump.sql")
            with open(dump_path, "w", encoding="utf-8") as outfile:
                result = subprocess.run(
                    ["gunzip", "-c", backup_file],
                    stdout=outfile,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            return result.returncode == 0

        # Direct SQL files
        if ext in (".sql", ".dump"):
            shutil.copy(backup_file, os.path.join(extract_path, "dump.sql"))
            return True

        logger.error("Unsupported backup format: %s", ext)
        return False

    except ValueError:
        raise  # Re-raise path traversal errors — must not be silenced
    except Exception as e:
        logger.error("Extraction failed: %s", e)
        return False


def detect_backup_type(extract_path: str) -> dict | None:
    """Auto-detect backup structure after extraction.

    Returns:
        Dict with 'sql_file' and optional 'filestore' paths, or None.
    """
    # Case 1: dump.sql in root
    root_sql = os.path.join(extract_path, "dump.sql")
    if os.path.exists(root_sql):
        # Look for filestore in subdirectories
        filestore = None
        for entry in os.listdir(extract_path):
            entry_path = os.path.join(extract_path, entry)
            if os.path.isdir(entry_path) and entry != "__MACOSX":
                # Check for filestore subdirectory
                fs_path = os.path.join(entry_path, "filestore")
                if os.path.isdir(fs_path):
                    filestore = fs_path
                elif entry == "filestore":
                    filestore = entry_path
                else:
                    filestore = entry_path
                break
        return {"sql_file": root_sql, "filestore": filestore}

    # Case 2: dump.sql in subdirectory
    for root, _dirs, files in os.walk(extract_path):
        if "dump.sql" in files:
            sql_file = os.path.join(root, "dump.sql")
            filestore = None
            fs_path = os.path.join(root, "filestore")
            if os.path.isdir(fs_path):
                filestore = fs_path
            return {"sql_file": sql_file, "filestore": filestore}

    return None


def copy_filestore(src: str, dest: str) -> bool:
    """Copy filestore contents to destination.

    Args:
        src: Source filestore directory
        dest: Destination filestore directory

    Returns:
        True if copy successful.
    """
    if not os.path.isdir(src):
        logger.error("Filestore source not found: %s", src)
        return False

    os.makedirs(dest, exist_ok=True)

    try:
        for root, _dirs, files in os.walk(src):
            # Skip dump.sql
            files = [f for f in files if f != "dump.sql"]
            rel_root = os.path.relpath(root, src)
            dest_root = os.path.join(dest, rel_root) if rel_root != "." else dest

            os.makedirs(dest_root, exist_ok=True)
            for fname in files:
                shutil.copy2(os.path.join(root, fname), os.path.join(dest_root, fname))

        logger.info("Filestore copied to %s", dest)
        return True
    except Exception as e:
        logger.error("Filestore copy failed: %s", e)
        return False


def move_filestore(src: str, dest: str) -> bool:
    """Move filestore contents to destination instead of copying them.

    Sister of :func:`copy_filestore`. Uses ``shutil.move`` per top-level entry,
    which is an instantaneous rename when source and destination live on the
    same filesystem (the common case: both under ``$HOME``) — avoiding the
    transient double-storage of the filestore during a restore. Across
    filesystem boundaries ``shutil.move`` transparently falls back to
    copy-then-delete.

    Args:
        src: Source filestore directory (its contents are consumed).
        dest: Destination filestore directory.

    Returns:
        True if move successful.
    """
    if not os.path.isdir(src):
        logger.error("Filestore source not found: %s", src)
        return False

    os.makedirs(dest, exist_ok=True)

    try:
        for entry in os.listdir(src):
            # Skip the SQL dump — it is restored separately, not part of the filestore.
            if entry == "dump.sql":
                continue
            src_entry = os.path.join(src, entry)
            dest_entry = os.path.join(dest, entry)
            # If the target already exists (idempotent re-runs), remove it first
            # so shutil.move does not nest the source inside it.
            if os.path.exists(dest_entry):
                if os.path.isdir(dest_entry) and not os.path.islink(dest_entry):
                    shutil.rmtree(dest_entry)
                else:
                    os.remove(dest_entry)
            shutil.move(src_entry, dest_entry)

        logger.info("Filestore moved to %s", dest)
        return True
    except Exception as e:
        logger.error("Filestore move failed: %s", e)
        return False


def get_filestore_path(odoo_version: str, db_name: str) -> str:
    """Get the filestore path for a database.

    When a migration group is active and the version is part of it,
    returns a shared filestore path so both source and target versions
    access the same files.

    Otherwise, each Odoo version uses its own subdirectory under
    ~/odoo-share/vXX/ to prevent filestore collisions.

    Args:
        odoo_version: Odoo version string (e.g., "18")
        db_name: Database name

    Returns:
        Path to filestore directory.
    """
    try:
        from odoodev.core.migration_config import get_active_group

        group = get_active_group()
        if group and odoo_version in (group.from_version, group.to_version):
            base = os.path.expanduser(group.shared_filestore_base)
            return os.path.join(base, "filestore", db_name)
    except Exception:  # noqa: S110 — intentional safety guard
        pass

    return os.path.join(
        os.path.expanduser("~"),
        "odoo-share",
        f"v{odoo_version}",
        "filestore",
        db_name,
    )


def backup_database_sql(
    db_name: str,
    output_path: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Create a SQL dump of a database using pg_dump.

    Args:
        db_name: Database name to dump
        output_path: Full path for the output SQL file
        host: PostgreSQL host
        port: PostgreSQL port
        user: PostgreSQL user

    Returns:
        True if dump was successful.
    """
    try:
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("pg_dump", mode, user, host, port) + [db_name]
        # stdout redirection works transparently in container mode too — the
        # exec'd pg_dump's stdout is forwarded to the host process.
        with open(output_path, "w", encoding="utf-8") as outfile:
            subprocess.run(
                cmd,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=outfile,
                stderr=subprocess.PIPE,
                text=True,
                env=_pg_exec_env(mode, host, port),
            )
        logger.info("Database %s dumped to %s", db_name, output_path)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to dump %s: %s", db_name, e.stderr)
        return False
    except (OSError, PgToolsUnavailableError) as e:
        logger.error("Failed to dump %s: %s", db_name, e)
        return False


def create_backup_zip(
    sql_path: str,
    output_path: str,
    filestore_path: str | None = None,
) -> bool:
    """Create a ZIP backup in Odoo standard format (dump.sql + filestore/).

    Args:
        sql_path: Path to the SQL dump file
        output_path: Full path for the output ZIP file
        filestore_path: Optional path to filestore directory

    Returns:
        True if ZIP was created successfully.
    """
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(sql_path, "dump.sql")

            if filestore_path and os.path.isdir(filestore_path):
                for root, _dirs, files in os.walk(filestore_path):
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        arcname = os.path.join("filestore", os.path.relpath(full_path, filestore_path))
                        zf.write(full_path, arcname)

        logger.info("Backup ZIP created: %s", output_path)
        return True
    except Exception as e:
        logger.error("Failed to create backup ZIP: %s", e)
        return False


def create_backup_tar_zst(
    sql_path: str,
    output_path: str,
    filestore_path: str | None = None,
    level: int = 5,
) -> bool:
    """Create a TAR+Zstandard backup (dump.sql + filestore/).

    Matches the container2backup.py server stream-backup format and the
    counterpart restore in :func:`_extract_backup_inner`. A Python tar stream
    is piped into the zstd CLI — no Python ``zstandard`` package is required.

    Args:
        sql_path: Path to the SQL dump file
        output_path: Full path for the output .tar.zst file
        filestore_path: Optional path to filestore directory
        level: zstd compression level (1=fastest .. 19/22=smallest)

    Returns:
        True if the archive was created successfully.
    """
    import tarfile

    zstd_bin = shutil.which("zstd")
    if not zstd_bin:
        logger.error(
            "zstd not found — required to create .tar.zst backups. "
            "Install: brew install zstd (macOS) / apt install zstd (Linux)"
        )
        return False

    try:
        # zstd reads the tar stream from stdin and writes the compressed archive
        # directly to output_path. -T0 uses all CPU cores, -f overwrites partials.
        proc = subprocess.Popen(
            [zstd_bin, "-T0", f"-{level}", "-f", "-o", output_path],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Stream mode "w|": single pass, no seeking — matches restore's "r|".
            with tarfile.open(fileobj=proc.stdin, mode="w|") as tf:
                tf.add(sql_path, arcname="dump.sql")
                if filestore_path and os.path.isdir(filestore_path):
                    for root, _dirs, files in os.walk(filestore_path):
                        for fname in files:
                            full_path = os.path.join(root, fname)
                            arcname = os.path.join("filestore", os.path.relpath(full_path, filestore_path))
                            tf.add(full_path, arcname=arcname)
        finally:
            if proc.stdin:
                proc.stdin.close()
            ret = proc.wait()
        if ret != 0:
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            logger.error("zstd compression failed: %s", stderr)
            return False

        logger.info("Backup tar.zst created: %s", output_path)
        return True
    except Exception as e:
        logger.error("Failed to create backup tar.zst: %s", e)
        return False


def deactivate_cronjobs(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Deactivate cron jobs and email servers in a database."""
    queries = [
        "UPDATE ir_cron SET active = false;",
        "UPDATE ir_mail_server SET active = false;",
        "UPDATE fetchmail_server SET active = false WHERE active = true;",
    ]
    success = True
    for query in queries:
        ok, _ = _run_psql(query, db=db_name, host=host, port=port, user=user)
        if not ok:
            success = False
    return success


def run_neutralize(
    db_name: str,
    venv_python: str,
    odoo_bin: str,
    config_path: str,
    env: dict[str, str],
    cwd: str,
    extra: list[str] | None = None,
) -> tuple[bool, str]:
    """Run Odoo's native ``odoo-bin neutralize`` on a database.

    Executes ``<venv_python> odoo-bin neutralize -c <conf> -d <db>``. This is a
    standalone Odoo CLI subcommand that connects directly to PostgreSQL and runs
    each installed module's ``data/neutralize.sql`` — it does NOT boot a server,
    so no ``--stop-after-init`` is needed. Missing module SQL files are skipped
    by Odoo itself (``suppress(FileNotFoundError)``).

    Args:
        extra: Additional odoo-bin args (e.g. ``["--stdout"]`` to print the
            neutralization SQL instead of applying it).

    Returns:
        Tuple of (success, output_or_error).
    """
    cmd = [venv_python, odoo_bin, "neutralize", "-c", config_path, "-d", db_name]
    if extra:
        cmd.extend(extra)
    try:
        result = subprocess.run(
            cmd, env=env, cwd=cwd, check=True, stdin=subprocess.DEVNULL, capture_output=True, text=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


# Server-mode defaults: paths inside the myodoo Odoo containers (Dockerfiles/*/bin/boot).
SERVER_ODOO_BIN_PATH = "/opt/odoo/odoo-server/odoo-bin"
SERVER_ODOO_CONF_PATH = "/opt/odoo/etc/odoo.conf"


def _run_odoo_bin_container(
    db_name: str,
    odoo_container: str,
    odoo_args: list[str],
    cli: str = "docker",
) -> tuple[bool, str]:
    """Run an odoo-bin invocation inside a *running* Odoo container via docker exec.

    ``docker exec`` cannot enter a stopped container — callers must ensure the
    container is up (playbooks: place these steps after ``container.start``).

    Returns:
        Tuple of (success, output_or_error).
    """
    from odoodev.core.docker_exec import docker_container_running, docker_exec

    if not docker_container_running(odoo_container, cli):
        return False, (
            f"Container '{odoo_container}' is not running — docker exec needs a running "
            f"container (run this step after container.start)"
        )
    ok, stdout, stderr = docker_exec(odoo_container, odoo_args, cli=cli)
    if not ok:
        return False, stderr or stdout or f"odoo-bin failed in container '{odoo_container}'"
    return True, stdout


def run_neutralize_container(
    db_name: str,
    odoo_container: str,
    odoo_bin_path: str = SERVER_ODOO_BIN_PATH,
    config_path: str = SERVER_ODOO_CONF_PATH,
    cli: str = "docker",
    extra: list[str] | None = None,
) -> tuple[bool, str]:
    """Server-mode sibling of :func:`run_neutralize` — runs inside the Odoo container.

    ``odoo-bin neutralize`` connects directly to PostgreSQL (no server boot), so it
    is safe to run while the container's Odoo server process is serving.
    """
    cmd = ["python3", odoo_bin_path, "neutralize", "-c", config_path, "-d", db_name]
    if extra:
        cmd.extend(extra)
    return _run_odoo_bin_container(db_name, odoo_container, cmd, cli=cli)


def run_update_all_container(
    db_name: str,
    odoo_container: str,
    odoo_bin_path: str = SERVER_ODOO_BIN_PATH,
    config_path: str = SERVER_ODOO_CONF_PATH,
    cli: str = "docker",
    extra_args: list[str] | None = None,
) -> tuple[bool, str]:
    """Update all modules (``odoo-bin -u all --stop-after-init``) inside the Odoo container.

    Mirrors the myodoo boot entrypoint's ``update`` mode. The running server keeps
    its old registry in memory — callers should restart the container afterwards.
    """
    cmd = [
        "python3",
        odoo_bin_path,
        "-c",
        config_path,
        "-d",
        db_name,
        "-u",
        "all",
        "--stop-after-init",
        "--workers=0",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return _run_odoo_bin_container(db_name, odoo_container, cmd, cli=cli)


# Per anonymized model, the changed source columns whose stored computed
# dependents must be recomputed. Raw-SQL anonymization writes these columns
# directly, so Odoo never recomputes fields like complete_name /
# commercial_company_name / email_normalized that depend on them — leaving
# display_name (which reads the stored complete_name) stale in list/kanban views.
RECOMPUTE_TRIGGERS: dict[str, tuple[str, ...]] = {
    # eq_firstname: complete_name @api.depends on it in Equitania's eq_res_partner
    # (column-filtered away on non-eq DBs by the recompute script itself).
    "res.partner": ("name", "email", "vat", "eq_firstname"),
    "crm.lead": ("name", "contact_name", "partner_name", "email_from"),
    "res.partner.bank": ("acc_number",),
    "hr.employee": ("name", "work_email"),
}


def _build_recompute_script(triggers: dict[str, tuple[str, ...]]) -> str:
    """Build the ``odoo-bin shell`` script that recomputes stored computed fields.

    Invalidates the ORM cache, marks the changed source fields as modified so
    their stored dependents are queued, then flushes — recomputing and
    persisting them. ``odoo-bin shell`` rolls back on exit, so the script must
    ``env.cr.commit()`` explicitly. Models/fields absent in this DB are skipped.
    """
    return textwrap.dedent(
        f"""\
        TRIGGERS = {triggers!r}
        for _model, _fields in TRIGGERS.items():
            if _model not in env:
                continue
            _M = env[_model].with_context(active_test=False)
            _f = [_c for _c in _fields if _c in _M._fields]
            if not _f:
                continue
            _recs = _M.search([])
            if not _recs:
                continue
            _recs.invalidate_recordset()
            _recs.modified(_f)
        env.flush_all()
        env.cr.commit()
        print("odoodev-recompute: done")
        """
    )


def run_recompute(
    db_name: str,
    venv_python: str,
    odoo_bin: str,
    config_path: str,
    env: dict[str, str],
    cwd: str,
) -> tuple[bool, str]:
    """Recompute stored computed fields via ``odoo-bin shell`` after raw-SQL edits.

    Pipes :func:`_build_recompute_script` into ``odoo-bin shell`` (which ``exec()``s
    a script from non-tty stdin). Fixes stale ``complete_name`` / display names in
    overviews after anonymization. Same kwargs as :func:`run_neutralize` (from
    ``resolve_odoo_invocation``), so callers use ``run_recompute(name, **inv)``.

    Returns:
        Tuple of (success, output_or_error).
    """
    cmd = [venv_python, odoo_bin, "shell", "-c", config_path, "-d", db_name, "--no-http"]
    script = _build_recompute_script(RECOMPUTE_TRIGGERS)
    try:
        result = subprocess.run(cmd, env=env, cwd=cwd, input=script, check=True, capture_output=True, text=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def parse_module_names(raw: str | list[str] | None) -> list[str]:
    """Normalize a module-list argument into a deduped, order-preserving list.

    Accepts a comma-separated string (CLI option / interactive prompt) or a
    list (playbook YAML), stripping blanks and dropping duplicates.
    """
    if not raw:
        return []
    items = raw if isinstance(raw, list) else str(raw).split(",")
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        name = str(item).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _build_uninstall_modules_script(modules: list[str]) -> str:
    """Build the ``odoo-bin shell`` script that uninstalls the given modules.

    Only modules actually in state 'installed' are targeted; names that don't
    exist or aren't installed are reported via stdout markers, not treated as
    failures — a stale/optional module name is a common, harmless input.

    Modules are uninstalled one at a time, in the given order. Third-party
    modules commonly override ``button_immediate_uninstall`` with singleton
    assumptions (``self.name``), so a multi-record call blows up exactly on
    the invasive modules this feature exists to remove. Each uninstall also
    rebuilds the registry, so every iteration re-creates the environment and
    re-searches its record; a module cascade-uninstalled by a previous
    iteration is reported as not-installed instead of failing. A failing
    module does not block the remaining ones — failures are marked on stdout,
    the traceback goes to stderr, and the script exits non-zero at the end.
    ``button_immediate_uninstall`` commits internally, but ``odoo-bin shell``
    rolls back on exit, so commit explicitly for consistency.
    """
    return textwrap.dedent(
        f"""\
        import sys
        import traceback

        MODULES = {modules!r}
        _cr, _uid, _ctx = env.cr, env.uid, env.context
        _found_names = set(
            env["ir.module.module"].with_context(active_test=False).search([("name", "in", MODULES)]).mapped("name")
        )
        for _name in sorted(set(MODULES) - _found_names):
            print(f"odoodev-uninstall: not-found {{_name}}")
        _failed = False
        for _name in [m for m in MODULES if m in _found_names]:
            env = odoo.api.Environment(_cr, _uid, _ctx)
            _rec = env["ir.module.module"].with_context(active_test=False).search([("name", "=", _name)])
            if _rec.state != "installed":
                print(f"odoodev-uninstall: not-installed {{_name}}")
                continue
            try:
                _rec.button_immediate_uninstall()
                env.cr.commit()
                print(f"odoodev-uninstall: uninstalled {{_name}}")
            except Exception:
                print(f"odoodev-uninstall: failed {{_name}}")
                traceback.print_exc(file=sys.stderr)
                env.cr.rollback()
                _failed = True
        if _failed:
            raise SystemExit(1)
        """
    )


def run_uninstall_modules(
    db_name: str,
    modules: list[str],
    venv_python: str,
    odoo_bin: str,
    config_path: str,
    env: dict[str, str],
    cwd: str,
) -> tuple[bool, str]:
    """Uninstall the given technical module names via ``odoo-bin shell``.

    Runs before the sanitize pipeline (neutralize/anonymize/wipe) so modules
    that interfere with those steps are removed first. Same kwargs as
    :func:`run_neutralize`/:func:`run_recompute` (from ``resolve_odoo_invocation``),
    so callers use ``run_uninstall_modules(name, modules, **inv)``.

    Returns:
        Tuple of (success, output_or_error). The output contains
        ``odoodev-uninstall: ...`` marker lines for not-found / not-installed /
        uninstalled / failed modules. On failure the stdout markers are kept
        (they tell which modules still succeeded) followed by stderr.
    """
    cmd = [venv_python, odoo_bin, "shell", "-c", config_path, "-d", db_name, "--no-http"]
    script = _build_uninstall_modules_script(modules)
    try:
        result = subprocess.run(cmd, env=env, cwd=cwd, input=script, check=True, capture_output=True, text=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + (e.stderr or "")


# --------------------------------------------------------------------------- #
# GDPR data anonymization (post-restore)
#
# Replaces personal data with Faker-generated, deterministic values after a
# production database has been restored into the local dev environment
# (GDPR Art. 5 data minimization, Art. 25 privacy by default).
#
# Strategy: per personal-data table, fetch row ids, generate per-id seeded
# Faker values in Python, then apply one bundled "UPDATE ... FROM (VALUES ...)"
# via "psql -f". E-mail and login columns are NOT taken from Faker but forced
# onto RFC 2606 reserved targets (@example.invalid / user{id}) so no real
# address can ever be reached and unique constraints are preserved.
# --------------------------------------------------------------------------- #

# Chunk size for bundled VALUES updates (guards against ARG_MAX / statement size).
ANONYMIZE_CHUNK_SIZE = 2000


@dataclass(frozen=True)
class AnonField:
    """A single column to anonymize with a Faker-based value generator.

    The generator receives a seeded ``Faker`` instance and the row id and
    returns a Python value (``str`` or ``None``) that is rendered to a SQL
    literal.
    """

    column: str
    generator: Callable[[Faker, int], str | None]


@dataclass(frozen=True)
class AnonTable:
    """A table whose personal-data columns are anonymized row by row."""

    table: str
    fields: tuple[AnonField, ...]
    where: str = ""  # extra WHERE clause to restrict / exclude rows (e.g. system users)


@dataclass(frozen=True)
class StaticAnonTable:
    """A table whose PII columns are wiped with the same constant value for all rows.

    Used for columns that need no per-row variation and/or are non-text (FK, date,
    numeric, bytea, json) — a single ``UPDATE`` sets them to NULL/0. Assignments are
    filtered against the live schema (``_existing_columns``) so the same spec works
    across Odoo versions where a column may not exist.
    """

    table: str
    # (column, raw SQL value expression), e.g. ("birthday", "NULL"), ("wage", "0").
    assignments: tuple[tuple[str, str], ...]
    where: str = ""


# Shared res_partner fields (everything except name/function, which differ for companies).
# The eq_* columns are Equitania custom fields (eq_res_partner); column-filtered away
# on non-eq databases. eq_birthday is a Date and is nulled via the static pass below.
_PARTNER_COMMON_FIELDS: tuple[AnonField, ...] = (
    AnonField("email", lambda f, i: f"p{i}@example.invalid"),
    AnonField("phone", lambda f, i: f.phone_number()),
    AnonField("mobile", lambda f, i: f.phone_number()),
    AnonField("street", lambda f, i: f.street_address()),
    AnonField("street2", lambda f, i: None),
    AnonField("city", lambda f, i: f.city()),
    AnonField("zip", lambda f, i: f.postcode()),
    AnonField("vat", lambda f, i: None),
    AnonField("website", lambda f, i: None),
    AnonField("comment", lambda f, i: None),
    AnonField("eq_name2", lambda f, i: None),
    AnonField("eq_name3", lambda f, i: None),
    AnonField("eq_citypart", lambda f, i: None),
)

# Partners to KEEP: those backing an internal user (res_users) or a company
# (res_company). res_users/res_company are intentionally not anonymized or purged
# by default, so their partner must be left alone too — otherwise an anonymized
# name would hide which user/company is which and make testing confusing. This
# direct keep-set is reused by the master-data purge (extended there with the
# transitive parent/commercial ancestors so kept rows never dangle).
_KEEP_PARTNER_DIRECT_SUBQUERY = (
    "SELECT partner_id FROM res_users WHERE partner_id IS NOT NULL "
    "UNION SELECT partner_id FROM res_company WHERE partner_id IS NOT NULL"
)
# ANDed onto every res_partner anonymization filter so user/company partners keep
# their real name/contact.
_NON_USER_PARTNER_WHERE = f"id NOT IN ({_KEEP_PARTNER_DIRECT_SUBQUERY})"

# Per-row Faker tables. Field order is stable so seeded generation is reproducible.
# res_partner is split by is_company: companies get a company name (and no job title),
# persons get a personal name and a job title.
ANONYMIZE_TABLES: tuple[AnonTable, ...] = (
    AnonTable(
        table="res_partner",
        fields=(AnonField("name", lambda f, i: f.company()),) + _PARTNER_COMMON_FIELDS,
        where=f"is_company = true AND {_NON_USER_PARTNER_WHERE}",
    ),
    AnonTable(
        table="res_partner",
        fields=(AnonField("name", lambda f, i: f.name()),)
        + _PARTNER_COMMON_FIELDS
        + (
            AnonField("function", lambda f, i: f.job()),
            # Equitania custom first-name field (eq_res_partner); column-filtered
            # away on non-eq databases. complete_name @api.depends on eq_firstname,
            # so it is also listed in RECOMPUTE_TRIGGERS below.
            AnonField("eq_firstname", lambda f, i: f.first_name()),
        ),
        # Parenthesize the is_company OR so the user exclusion ANDs onto the whole
        # predicate, not just the IS NULL branch (SQL precedence: AND binds tighter).
        where=f"(is_company = false OR is_company IS NULL) AND {_NON_USER_PARTNER_WHERE}",
    ),
    # NOTE: res_users is intentionally NOT anonymized by default — that would make
    # every login unusable and break testing. Opt in via anonymize_users() / the
    # `--anonymize-users` restore flag instead.
    AnonTable(
        table="crm_lead",
        fields=(
            AnonField("contact_name", lambda f, i: f.name()),
            AnonField("partner_name", lambda f, i: f.company()),
            AnonField("email_from", lambda f, i: f"lead{i}@example.invalid"),
            AnonField("phone", lambda f, i: f.phone_number()),
            AnonField("mobile", lambda f, i: f.phone_number()),
            AnonField("street", lambda f, i: f.street_address()),
            AnonField("city", lambda f, i: f.city()),
            AnonField("zip", lambda f, i: f.postcode()),
            AnonField("description", lambda f, i: None),
        ),
    ),
    AnonTable(
        table="res_partner_bank",
        fields=(
            AnonField("acc_number", lambda f, i: f.iban()),
            AnonField("sanitized_acc_number", lambda f, i: None),
        ),
    ),
    # HR: only the identity text columns are per-row Faker values. The bulk of the
    # employee PII (private address, IDs, dates, binaries, ...) is wiped via the
    # column-filtered static updates below, because those columns differ by Odoo
    # version and many are non-text (FK / date / numeric / bytea).
    AnonTable(
        table="hr_employee",
        fields=(
            AnonField("name", lambda f, i: f.name()),
            AnonField("work_email", lambda f, i: f"emp{i}@example.invalid"),
        ),
    ),
)

# Whole-table updates that need no per-row Faker values (often huge tables).
ANONYMIZE_STATIC_QUERIES: tuple[str, ...] = (
    "UPDATE mail_message SET email_from = NULL, subject = NULL, body = '<p>[anonymized]</p>';",
    "UPDATE ir_attachment SET index_content = NULL;",
)

# HR PII wiped with constant values. One spec per table covers v16/v18/v19 because
# columns are filtered against the live schema before the UPDATE is built:
#   - v16: private address / private_email / private_phone live on res_partner (via
#     address_home_id) and are already handled by the global res_partner pass; those
#     private_* columns simply don't exist on hr_employee and are filtered out here.
#   - v19: ssnid / passport_id / marital / ... moved to hr_version; on hr_employee
#     they no longer exist and are filtered out, while the hr_version spec covers them.
_HR_EMPLOYEE_NULL_COLUMNS: tuple[str, ...] = (
    "work_phone",
    "mobile_phone",
    "private_email",
    "private_phone",
    "private_street",
    "private_street2",
    "private_city",
    "private_zip",
    "private_state_id",
    "private_country_id",
    "identification_id",
    "passport_id",
    "ssnid",
    "sinid",
    "permit_no",
    "visa_no",
    "visa_expire",
    "work_permit_expiration_date",
    "birthday",
    "place_of_birth",
    "country_of_birth",
    "spouse_complete_name",
    "spouse_birthdate",
    "emergency_contact",
    "emergency_phone",
    "has_work_permit",
    "pin",
    "barcode",
    "notes",
    "additional_note",
    "departure_description",
    "legal_name",
    "private_car_plate",
    "salary_distribution",
    "driving_license",
    "image_1920",
    "image_1024",
    "image_512",
    "image_256",
    "image_128",
)

ANONYMIZE_STATIC_TABLES: tuple[StaticAnonTable, ...] = (
    # Equitania custom date-of-birth on res_partner (eq_res_partner); nulled here
    # rather than per-row because it is a Date column. Column-filtered → no-op on
    # non-eq databases.
    StaticAnonTable(
        table="res_partner",
        assignments=(("eq_birthday", "NULL"),),
        where=_NON_USER_PARTNER_WHERE,
    ),
    StaticAnonTable(
        table="hr_employee",
        assignments=tuple((col, "NULL") for col in _HR_EMPLOYEE_NULL_COLUMNS)
        + (
            ("marital", "'single'"),
            ("children", "0"),
            ("km_home_work", "0"),
            ("distance_home_work", "0"),
        ),
    ),
    # v19: contract/personal data moved into hr_version (successor of hr_contract).
    StaticAnonTable(
        table="hr_version",
        assignments=(
            ("wage", "0"),
            ("gender", "NULL"),
            ("ssnid", "NULL"),
            ("sinid", "NULL"),
            ("identification_id", "NULL"),
            ("passport_id", "NULL"),
            ("marital", "'single'"),
            ("spouse_complete_name", "NULL"),
            ("spouse_birthdate", "NULL"),
            ("children", "0"),
        ),
    ),
    # v16/v18: salary lives on hr_contract.
    StaticAnonTable(
        table="hr_contract",
        assignments=(("wage", "0"),),
    ),
)

# Linkage / M2M tables wiped entirely (e.g. v19 employee↔bank-account relation;
# the IBANs themselves are already faked via the global res_partner_bank pass).
ANONYMIZE_DELETE_TABLES: tuple[str, ...] = ("employee_bank_account_rel",)


def _sql_literal(value: str | None) -> str:
    """Render a Python value as a safe single-quoted SQL literal (or NULL)."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Tokens that have no business in an anonymization WHERE filter (statement
# chaining, comments, quoting) — the filters are plain column comparisons.
_FORBIDDEN_WHERE_TOKENS = (";", "--", "/*")


def _check_identifier(name: str) -> str:
    """Fail fast on a table/column name that is not a plain SQL identifier.

    All current callers pass hardcoded constants; this guard exists so the
    f-string query builders cannot be reused with untrusted input.
    """
    if not _SQL_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def _check_where_fragment(where: str) -> str:
    """Fail fast on a WHERE fragment containing statement-breaking tokens."""
    for token in _FORBIDDEN_WHERE_TOKENS:
        if token in where:
            raise ValueError(f"Unsafe SQL WHERE fragment: {where!r}")
    return where


def _existing_columns(
    table: str,
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> set[str]:
    """Return the column names of a public table (empty set if it doesn't exist).

    Used to make anonymization version-robust: columns that don't exist in a given
    Odoo version are filtered out before the UPDATE is built, and a missing table
    yields an empty set so the caller skips it.
    """
    _check_identifier(table)
    query = (
        f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{table}';"
    )
    ok, out = _run_psql(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return set()
    columns: set[str] = set()
    for line in out.splitlines():
        stripped = line.strip()
        # Skip psql header ("column_name"), the dashed separator and the "(N rows)" footer.
        if not stripped or stripped == "column_name" or stripped.startswith("(") or set(stripped) <= {"-"}:
            continue
        columns.add(stripped)
    return columns


def _filter_fields(spec: AnonTable, existing: set[str]) -> AnonTable:
    """Return a copy of ``spec`` keeping only fields whose column exists in the schema."""
    fields = tuple(field for field in spec.fields if field.column in existing)
    return AnonTable(table=spec.table, fields=fields, where=spec.where)


def _build_static_update(
    table: str,
    assignments: tuple[tuple[str, str], ...],
    existing: set[str],
    where: str = "",
) -> str | None:
    """Build a single ``UPDATE`` from constant assignments, skipping missing columns.

    Returns None if no assigned column exists in the live schema.
    """
    _check_identifier(table)
    parts = [f"{_check_identifier(column)} = {value}" for column, value in assignments if column in existing]
    if not parts:
        return None
    clause = f" WHERE {_check_where_fragment(where)}" if where else ""
    return f"UPDATE {table} SET {', '.join(parts)}{clause};"


def _fetch_ids(
    spec: AnonTable,
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> list[int]:
    """Fetch row ids for a table, applying the spec's optional WHERE filter.

    Returns an empty list on any error (e.g. table missing because the module
    is not installed) so anonymization stays non-fatal.
    """
    where = f" WHERE {_check_where_fragment(spec.where)}" if spec.where else ""
    query = f"SELECT id FROM {_check_identifier(spec.table)}{where} ORDER BY id;"
    ok, out = _run_psql(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return []
    ids = []
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            ids.append(int(stripped))
    return ids


def _build_anonymize_sql(
    spec: AnonTable,
    ids: list[int],
    fake: Faker,
    chunk_size: int = ANONYMIZE_CHUNK_SIZE,
) -> str:
    """Build chunked ``UPDATE ... FROM (VALUES ...)`` statements for a table.

    Faker is seeded per row id so the result is deterministic / reproducible.
    """
    _check_identifier(spec.table)
    columns = [_check_identifier(f.column) for f in spec.fields]
    col_list = ", ".join(columns)
    set_clause = ", ".join(f"{c} = v.{c}" for c in columns)
    statements = []
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        rows = []
        for row_id in chunk:
            fake.seed_instance(row_id)
            values = [str(row_id)] + [_sql_literal(f.generator(fake, row_id)) for f in spec.fields]
            rows.append("(" + ", ".join(values) + ")")
        values_block = ",\n".join(rows)
        statements.append(
            f"UPDATE {spec.table} AS t SET {set_clause}\n"
            f"FROM (VALUES\n{values_block}\n) AS v(id, {col_list})\n"
            f"WHERE t.id = v.id;"
        )
    return "\n\n".join(statements)


def _run_psql_file(
    sql: str,
    db: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, str]:
    """Write SQL to a temp file and pipe it into ``psql`` via stdin (ON_ERROR_STOP).

    stdin piping (instead of ``-f``) keeps the temp file host-local when the
    container exec fallback is active.
    """
    fd, path = tempfile.mkstemp(suffix=".sql", prefix="odoodev_anon_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(sql)
        mode = resolve_pg_exec_mode(port)
        cmd = _pg_base_cmd("psql", mode, user, host, port) + ["-d", db, "-v", "ON_ERROR_STOP=1"]
        with open(path, "rb") as infile:
            result = subprocess.run(
                cmd, check=True, stdin=infile, capture_output=True, text=True, env=_pg_exec_env(mode, host, port)
            )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except (FileNotFoundError, PgToolsUnavailableError) as e:
        return False, str(e)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def anonymize_database(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
    locale: str = "de_DE",
) -> bool:
    """Anonymize personal data after a restore using Faker (GDPR Art. 5, 25).

    Covers res_partner, crm_lead, res_partner_bank and hr_employee (per-row Faker
    values) plus the HR PII bulk-wipes (hr_employee / hr_version / hr_contract,
    column filtered for version robustness). Content deletion (mail_message,
    ir_attachment, linkage tables) lives in :func:`wipe_database` — a separate
    opt-in since v0.43.0. ``res_users`` is intentionally NOT touched here so
    logins keep working — opt in via :func:`anonymize_users`. Non-fatal: missing
    tables / columns (uninstalled modules, version differences) are skipped.

    Returns:
        True if every applicable statement succeeded.
    """
    from faker import Faker

    fake = Faker(locale)
    success = True

    # 1. Per-row Faker tables — column-filtered against the live schema so a column
    #    that doesn't exist in this Odoo version is left out instead of erroring.
    for spec in ANONYMIZE_TABLES:
        ids = _fetch_ids(spec, db_name, host=host, port=port, user=user)
        if not ids:
            continue
        existing = _existing_columns(spec.table, db_name, host=host, port=port, user=user)
        effective = _filter_fields(spec, existing) if existing else spec
        if not effective.fields:
            continue
        sql = _build_anonymize_sql(effective, ids, fake)
        ok, _ = _run_psql_file(sql, db=db_name, host=host, port=port, user=user)
        if not ok:
            success = False

    # 2. HR PII bulk-wipes (constant values, column filtered). A missing table
    #    (wrong version / module not installed) yields an empty column set → skip.
    for static_table in ANONYMIZE_STATIC_TABLES:
        existing = _existing_columns(static_table.table, db_name, host=host, port=port, user=user)
        if not existing:
            continue
        stmt = _build_static_update(static_table.table, static_table.assignments, existing, where=static_table.where)
        if stmt is None:
            continue
        ok, _ = _run_psql(stmt, db=db_name, host=host, port=port, user=user)
        if not ok:
            success = False

    return success


def wipe_database(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Delete/blank message and attachment content after a restore (opt-in).

    Split out of :func:`anonymize_database` in v0.43.0 so deletion is a separate,
    explicit decision: DELETEs the linkage tables (``ANONYMIZE_DELETE_TABLES``)
    and runs the whole-table content wipes (``ANONYMIZE_STATIC_QUERIES`` —
    mail_message bodies/subjects, ir_attachment index content). Non-fatal:
    missing tables are skipped.

    Returns:
        True if every applicable statement succeeded.
    """
    success = True

    # 1. Linkage / M2M tables wiped entirely (guarded against missing tables).
    for table in ANONYMIZE_DELETE_TABLES:
        if _existing_columns(table, db_name, host=host, port=port, user=user):
            ok, _ = _run_psql(f"DELETE FROM {table};", db=db_name, host=host, port=port, user=user)
            if not ok:
                success = False

    # 2. Whole-table static content wipes.
    for query in ANONYMIZE_STATIC_QUERIES:
        ok, _ = _run_psql(query, db=db_name, host=host, port=port, user=user)
        if not ok:
            success = False

    return success


# Default dev password for opt-in res_users anonymization (hashed before storing).
DEFAULT_DEV_PASSWORD = "ownerp"  # noqa: S105 — dev-only login, documented for the team

# Rounds matching passlib's pbkdf2_sha512 default, which Odoo accepts and re-hashes on login.
_PBKDF2_SHA512_ROUNDS = 25000


def _pbkdf2_sha512_hash(password: str, rounds: int = _PBKDF2_SHA512_ROUNDS) -> str:
    """Build an Odoo/passlib-compatible ``$pbkdf2-sha512$`` hash with the stdlib only.

    Uses passlib's "ab64" encoding (standard base64 with ``+`` → ``.``, padding
    stripped): ``$pbkdf2-sha512$<rounds>$<salt>$<checksum>``. Odoo verifies this
    via passlib, so no passlib dependency is needed on our side.
    """
    import base64
    import hashlib
    import secrets

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, rounds)

    def ab64(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii").replace("+", ".").rstrip("=")

    return f"$pbkdf2-sha512${rounds}${ab64(salt)}${ab64(digest)}"


# Accounts kept untouched so the dev login keeps working (admin id=1 + technical logins).
_USER_ANON_WHERE = "id > 1 AND login NOT IN ('admin', '__system__', 'default', 'public', 'portaltemplate')"


def anonymize_users(
    db_name: str,
    dev_password: str = DEFAULT_DEV_PASSWORD,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Opt-in anonymization of ``res_users`` (NOT run by default).

    Sets each non-system login to ``user{id}`` and resets the password to a single
    known dev password so the database stays testable. ``admin`` (id=1) and technical
    accounts are left untouched. The password is stored as an Odoo-compatible
    ``pbkdf2_sha512`` hash (one hash is valid for every user).

    Returns:
        True on success, False if a statement failed.
    """
    from faker import Faker

    pw_hash = _pbkdf2_sha512_hash(dev_password)
    success = True

    # 1. Logins → user{id} (per-row, reusing the VALUES mechanism).
    login_spec = AnonTable(
        table="res_users",
        fields=(AnonField("login", lambda f, i: f"user{i}"),),
        where=_USER_ANON_WHERE,
    )
    ids = _fetch_ids(login_spec, db_name, host=host, port=port, user=user)
    if ids:
        sql = _build_anonymize_sql(login_spec, ids, Faker())
        ok, _ = _run_psql_file(sql, db=db_name, host=host, port=port, user=user)
        if not ok:
            success = False

    # 2. Password → one shared dev hash (single static UPDATE).
    pw_sql = f"UPDATE res_users SET password = {_sql_literal(pw_hash)} WHERE {_USER_ANON_WHERE};"
    ok, _ = _run_psql(pw_sql, db=db_name, host=host, port=port, user=user)
    if not ok:
        success = False

    return success


# --------------------------------------------------------------------------- #
# User management (db users TUI): password reset + 2FA disable
#

# Technical accounts hidden from the user-management view. Unlike
# _USER_ANON_WHERE, 'admin' is NOT excluded — resetting admin's password/2FA is
# a legitimate target after restoring a database for development.
_USER_LIST_EXCLUDED_LOGINS = "('__system__', 'default', 'public', 'portaltemplate')"


@dataclass(frozen=True)
class UserInfo:
    """One res_users row as shown in the user-management TUI."""

    id: int
    login: str
    name: str
    active: bool
    totp_enabled: bool
    share: bool  # portal/public user flag


def list_users(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
    include_portal: bool = False,
) -> list[UserInfo]:
    """List Odoo users with their 2FA status for the user-management TUI.

    Joins ``res_partner`` for the display name and reports 2FA as
    ``totp_secret IS NOT NULL`` (column-guarded: databases without ``auth_totp``
    report False for everyone). Inactive users are included; portal/public
    users (``share = true``) only with ``include_portal``. Returns an empty
    list on any error.
    """
    user_cols = _existing_columns("res_users", db_name, host=host, port=port, user=user)
    if not user_cols:
        return []
    totp_expr = "(u.totp_secret IS NOT NULL)" if "totp_secret" in user_cols else "false"
    share_expr = "COALESCE(u.share, false)" if "share" in user_cols else "false"
    portal_filter = "" if include_portal or "share" not in user_cols else " AND COALESCE(u.share, false) = false"
    # Runs via _run_psql_tuples (unaligned, tab-separated): psql's default
    # aligned format renders tabs as spaces, which silently broke row parsing.
    # Booleans print natively as t/f in unaligned mode — no ::text casts.
    query = (
        f"SELECT u.id, u.login, COALESCE(p.name, u.login), u.active, {totp_expr}, {share_expr} "
        "FROM res_users u LEFT JOIN res_partner p ON p.id = u.partner_id "
        f"WHERE u.id > 0 AND u.login NOT IN {_USER_LIST_EXCLUDED_LOGINS}{portal_filter} "
        "ORDER BY u.login;"
    )
    ok, rows = _run_psql_tuples(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return []
    users: list[UserInfo] = []
    for parts in rows:
        if len(parts) != 6 or not parts[0].isdigit():
            continue
        users.append(
            UserInfo(
                id=int(parts[0]),
                login=parts[1],
                name=parts[2],
                active=parts[3] == "t",
                totp_enabled=parts[4] == "t",
                share=parts[5] == "t",
            )
        )
    return users


def set_user_password(
    db_name: str,
    user_id: int,
    new_password: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, str]:
    """Set a user's password to an Odoo-compatible ``pbkdf2_sha512`` hash.

    The plaintext never appears in the SQL (only the salted hash) and must
    never be logged by callers.

    Returns:
        Tuple of (success, output_or_error).
    """
    pw_hash = _pbkdf2_sha512_hash(new_password)
    stmt = f"UPDATE res_users SET password = {_sql_literal(pw_hash)} WHERE id = {int(user_id)};"
    return _run_psql(stmt, db=db_name, host=host, port=port, user=user)


def disable_user_2fa(
    db_name: str,
    user_id: int,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, str]:
    """Disable TOTP 2FA for a user: clear the secret + drop trusted devices.

    Column/table guarded like :func:`neutralize_bank_sync`: a database without
    ``auth_totp`` (no ``totp_secret`` column) is a successful no-op, and the
    ``auth_totp_device`` trusted-device table is only touched when present.

    Returns:
        Tuple of (success, info_message).
    """
    user_cols = _existing_columns("res_users", db_name, host=host, port=port, user=user)
    if "totp_secret" not in user_cols:
        return True, "totp_secret column not present (auth_totp not installed) — nothing to disable"

    ok1, out1 = _run_psql(
        f"UPDATE res_users SET totp_secret = NULL WHERE id = {int(user_id)};",
        db=db_name,
        host=host,
        port=port,
        user=user,
    )

    ok2, out2 = True, ""
    if _existing_columns("auth_totp_device", db_name, host=host, port=port, user=user):
        ok2, out2 = _run_psql(
            f"DELETE FROM auth_totp_device WHERE user_id = {int(user_id)};",
            db=db_name,
            host=host,
            port=port,
            user=user,
        )

    if ok1 and ok2:
        return True, "TOTP secret cleared and trusted devices removed"
    return False, (out1 if not ok1 else out2)


def neutralize_bank_sync(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Disable bank synchronisation after a restore (not covered by odoo-bin neutralize).

    Odoo's native neutralize only marks ``account_online_link.client_id = 'duplicate'``
    and never resets ``account_journal.bank_statements_source``. This wipes the bank
    sync state FK-safely: detach journals → delete online accounts → delete online
    links. Each statement runs as its own psql call (separate transaction) — chaining
    the journal update and the deletes in one transaction can fail. Column/table
    guarded, so it is a no-op when the accounting / bank-sync modules are absent.

    Returns:
        True if every applicable statement succeeded.
    """
    success = True

    # 1. Reset statement source and detach online links/accounts from journals.
    journal_cols = _existing_columns("account_journal", db_name, host=host, port=port, user=user)
    if journal_cols:
        assignments: list[tuple[str, str]] = [
            ("bank_statements_source", "'undefined'"),
            ("account_online_account_id", "NULL"),
            ("account_online_link_id", "NULL"),
        ]
        stmt = _build_static_update("account_journal", tuple(assignments), journal_cols)
        if stmt is not None:
            ok, _ = _run_psql(stmt, db=db_name, host=host, port=port, user=user)
            if not ok:
                success = False

    # 2. Delete the child rows (online accounts) before the parent (online links).
    for table in ("account_online_account", "account_online_link"):
        if _existing_columns(table, db_name, host=host, port=port, user=user):
            ok, _ = _run_psql(f"DELETE FROM {table};", db=db_name, host=host, port=port, user=user)
            if not ok:
                success = False

    return success


# Transactional / movement-data root tables per app. The FK ON-DELETE-CASCADE
# closure of these roots (see _cascade_closure) pulls in the child/linkage tables
# that Odoo declared as cascade-dependent, so only the roots need listing; extras
# are guarded against missing modules/versions via _existing_columns(). Version
# notes: stock_valuation_layer + stock_package_level exist only on v16-v18 (folded
# into stock_move / removed on v19); product_value exists only on v19.
PURGE_TABLES: dict[str, tuple[str, ...]] = {
    "stock": (
        "stock_quant",
        "stock_move_line",
        "stock_move",
        "stock_picking",
        "stock_scrap",
        "stock_lot",
        "stock_valuation_layer",
        "stock_package_level",
        "product_value",
    ),
    "sale": ("sale_order_line", "sale_order"),
    "purchase": ("purchase_order_line", "purchase_order"),
    "account": (
        "account_partial_reconcile",
        "account_full_reconcile",
        "account_move_line",
        "account_payment",
        "account_bank_statement_line",
        "account_bank_statement",
        "account_move",
    ),
    "mrp": ("mrp_workorder", "mrp_production"),
    "pos": ("pos_order_line", "pos_payment", "pos_order", "pos_session"),
}

# Master/config tables the purge must never empty. If the cascade closure reaches
# any of these (e.g. via a custom/OCA module with an ON DELETE CASCADE FK into a
# transactional table), the purge aborts instead of wiping data the customer keeps.
PURGE_PROTECTED_TABLES: frozenset[str] = frozenset(
    {
        "res_partner",
        "res_users",
        "res_company",
        "product_template",
        "product_product",
        "product_pricelist",
        "product_pricelist_item",
    }
)


def resolve_purge_tables(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> list[str]:
    """Return the transactional tables from PURGE_TABLES that exist in this DB."""
    tables: list[str] = []
    for group in PURGE_TABLES.values():
        for table in group:
            if _existing_columns(table, db_name, host=host, port=port, user=user):
                tables.append(table)
    return tables


def _parse_psql_column(out: str, header: str) -> list[str]:
    """Parse a single-column psql text result into a list of values."""
    values: list[str] = []
    for line in out.splitlines():
        val = line.strip()
        if not val or val == header or val.startswith("(") or set(val) <= {"-"}:
            continue
        values.append(val)
    return values


def _cascade_closure(
    tables: list[str],
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> set[str]:
    """Return every table emptied by the ON-DELETE-CASCADE closure of ``tables``.

    Walks the FK graph outward via a recursive CTE over ``pg_constraint``, following
    ONLY ``ON DELETE CASCADE`` edges (``confdeltype = 'c'``). This is the exact set
    of tables that deleting the roots removes: the transactional children and hard
    dependents. FKs declared ``ON DELETE SET NULL`` (e.g. ``res_company`` →
    ``account_move`` for the opening entry, ``project_task`` → ``sale_order_line``)
    are deliberately NOT followed — those referencing rows are kept and their column
    is nulled instead (see :func:`_null_repair_targets`). This is why a plain
    ``TRUNCATE ... CASCADE`` is unusable here: Postgres' TRUNCATE ignores the FK's
    ON DELETE action and would wipe ``res_company`` and every table chained off it.
    """
    if not tables:
        return set()
    for table in tables:
        _check_identifier(table)
    roots = ", ".join(f"'{t}'" for t in tables)
    query = (
        "WITH RECURSIVE closure AS ("
        f"  SELECT c.oid FROM pg_class c WHERE c.relname IN ({roots}) "
        "    AND c.relnamespace = 'public'::regnamespace "
        "  UNION "
        "  SELECT con.conrelid FROM pg_constraint con "
        "    JOIN closure cl ON con.confrelid = cl.oid "
        "    WHERE con.contype = 'f' AND con.confdeltype = 'c'"
        ") "
        "SELECT DISTINCT relname FROM pg_class WHERE oid IN (SELECT oid FROM closure);"
    )
    ok, out = _run_psql(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return set()
    return set(_parse_psql_column(out, "relname"))


def _null_repair_targets(
    closure: set[str],
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> list[tuple[str, str]]:
    """Return (table, column) FK refs that point INTO the closure from KEPT tables.

    These are ``ON DELETE SET NULL`` foreign keys whose target is a purged table but
    whose owning table is kept (e.g. ``res_company.account_opening_move_id``). Odoo
    would normally null them on delete, but the purge runs with FK enforcement off
    (``session_replication_role = replica``), so they are nulled explicitly to avoid
    dangling references on kept rows.
    """
    if not closure:
        return []
    safe_closure = [_check_identifier(t) for t in sorted(closure)]
    in_closure = ", ".join(f"'{t}'" for t in safe_closure)
    query = (
        "SELECT con.conrelid::regclass::text AS tbl, a.attname AS col "
        "FROM pg_constraint con "
        "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1] "
        "WHERE con.contype = 'f' AND con.confdeltype = 'n' "
        f"  AND con.confrelid::regclass::text IN ({in_closure}) "
        f"  AND NOT (con.conrelid::regclass::text IN ({in_closure}));"
    )
    ok, out = _run_psql(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return []
    targets: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 2 or parts[0] in ("tbl", "") or parts[0].startswith("(") or set(parts[0]) <= {"-"}:
            continue
        targets.append((parts[0], parts[1]))
    return targets


def _is_superuser(db_name: str, host: str, port: int, user: str) -> bool:
    """True if the connected role may set session_replication_role (superuser)."""
    ok, out = _run_psql("SHOW is_superuser;", db=db_name, host=host, port=port, user=user)
    return ok and "on" in out.lower()


def purge_transactional_data(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, str]:
    """Delete all transactional/movement data, keeping products, pricelists, partners.

    Empties the movement-data tables (stock moves/quants, sale/purchase orders,
    accounting moves/payments, MRP, POS) and their ON-DELETE-CASCADE dependents.
    Emptying ``stock_quant`` zeroes on-hand stock (``qty_available`` is not stored).
    Products, pricelists, partners, users and config are kept — no FK points from
    them into the transactional tables.

    Mechanism: a plain ``TRUNCATE ... CASCADE`` is unusable because Postgres ignores
    each FK's ON DELETE action and would also wipe ``res_company`` (which references
    ``account_move`` for the opening entry) and everything chained off it. Instead
    the cascade-only closure (:func:`_cascade_closure`) is DELETEd in one transaction
    with ``session_replication_role = replica`` (FK enforcement + ordering off), then
    the SET-NULL back-references from kept tables (:func:`_null_repair_targets`) are
    nulled. A safety pre-check aborts (no deletion) if the closure would reach a
    protected master table — catching custom/OCA modules with a CASCADE FK.

    Returns:
        Tuple of (success, summary_or_error).
    """
    tables = resolve_purge_tables(db_name, host=host, port=port, user=user)
    if not tables:
        return True, "No transactional tables found (no movement-data modules installed)"

    closure = _cascade_closure(tables, db_name, host=host, port=port, user=user)
    if not closure:
        return False, "Could not resolve the transactional table closure (introspection failed)"

    breached = sorted(closure & PURGE_PROTECTED_TABLES)
    if breached:
        return (
            False,
            f"Aborted — deleting the transactional tables would also empty protected table(s): "
            f"{', '.join(breached)}. A custom/OCA module likely adds an ON DELETE CASCADE foreign key "
            "into a transactional table. No data deleted.",
        )

    if not _is_superuser(db_name, host, port, user):
        return (
            False,
            "Aborted — purge requires a superuser role (to disable FK enforcement during the bulk "
            "delete). Connect as the database superuser and retry. No data deleted.",
        )

    repairs = _null_repair_targets(closure, db_name, host=host, port=port, user=user)

    statements = ["BEGIN;", "SET LOCAL session_replication_role = replica;"]
    for table in sorted(closure):
        _check_identifier(table)
        statements.append(f'DELETE FROM "{table}";')
    for table, column in repairs:
        _check_identifier(table)
        _check_identifier(column)
        statements.append(f'UPDATE "{table}" SET "{column}" = NULL WHERE "{column}" IS NOT NULL;')
    statements.append("COMMIT;")

    ok, err = _run_psql_file("\n".join(statements), db=db_name, host=host, port=port, user=user)
    if not ok:
        return False, f"Purge failed: {err.strip()}"
    return True, f"{len(closure)} transactional table(s) emptied, {len(repairs)} reference(s) detached"


# --------------------------------------------------------------------------- #
# Master-data purge — full "template DB from production" reset.
#
# Superset of purge_transactional_data: in ONE session_replication_role=replica
# transaction it (1) empties the movement tables + their cascade closure, (2) empties
# the content roots below + closure, (3) deletes every res_partner EXCEPT those
# backing an internal user or a company (and their ancestors), following the FK graph
# so no orphans/dangling refs remain on kept rows, (4) deletes the attachments of the
# removed records while keeping product images and system assets. Products, pricelists,
# users, companies and config survive. Requires a superuser DB role.
# --------------------------------------------------------------------------- #

# Whole-table content roots deleted on top of the movement tables (PURGE_TABLES).
# Like PURGE_TABLES these are roots; their ON-DELETE-CASCADE children are added by
# _cascade_closure. Filtered to tables that actually exist in the target DB.
CONTENT_PURGE_TABLES: dict[str, tuple[str, ...]] = {
    "helpdesk": ("helpdesk_ticket",),
    "crm": ("crm_lead",),
    "hr": ("hr_employee", "hr_contract", "hr_version"),
    # mail_push_device / mail_scheduled_message / snailmail_letter carry ON DELETE
    # RESTRICT FKs into res_partner; emptying them wholesale here (they are
    # communication artifacts that go anyway) keeps the partner-prune drift guard
    # from aborting on production DBs that sent customer letters / registered devices.
    "mail": (
        "mail_message",
        "mail_activity",
        "mail_followers",
        "mail_scheduled_message",
        "mail_push_device",
        "snailmail_letter",
    ),
}

# Odoo model name per purged root table, for the polymorphic ir_attachment.res_model
# filter. Hardcoded (not table.replace("_", ".")) — a few Odoo _table names break the
# convention, and being explicit documents exactly which attachments are removed.
# Product/view/module/company/user models are deliberately absent → their attachments
# (product images, asset bundles, logos, avatars) are never a delete target.
PURGE_MODEL_NAMES: dict[str, str] = {
    "stock_picking": "stock.picking",
    "stock_move": "stock.move",
    "stock_scrap": "stock.scrap",
    "sale_order": "sale.order",
    "purchase_order": "purchase.order",
    "account_move": "account.move",
    "account_payment": "account.payment",
    "mrp_production": "mrp.production",
    "pos_order": "pos.order",
    "pos_session": "pos.session",
    "helpdesk_ticket": "helpdesk.ticket",
    "crm_lead": "crm.lead",
    "hr_employee": "hr.employee",
    "hr_contract": "hr.contract",
    "hr_version": "hr.version",
    "mail_message": "mail.message",
    "mail_activity": "mail.activity",
}

# WHERE fragment selecting res_partner rows to DELETE (everything not in the keep set).
_PARTNER_DELETE_WHERE = "id NOT IN (SELECT id FROM res_partner_keep)"

# Bound on the FK-graph walk when building the partner cascade-delete plan. Odoo's
# partner cascade depth is 1-2 hops; 6 is a generous ceiling that aborts a runaway.
_PARTNER_CASCADE_MAX_DEPTH = 6


def _resolve_content_purge_tables(
    db_name: str, host: str = DEFAULT_DB_HOST, port: int = 18432, user: str = DEFAULT_DB_USER
) -> list[str]:
    """Return the CONTENT_PURGE_TABLES roots that exist in this DB."""
    tables: list[str] = []
    for group in CONTENT_PURGE_TABLES.values():
        for table in group:
            if _existing_columns(table, db_name, host=host, port=port, user=user):
                tables.append(table)
    return tables


def _keep_partner_temp_table_sql() -> str:
    """SQL creating the res_partner_keep temp table (ids of user/company partners
    plus their transitive parent_id/commercial_partner_id ancestors).

    Kept partners' parent/commercial ancestors are included so that after the prune
    no kept row has a dangling parent_id/commercial_partner_id self-reference.
    """
    # Single self-reference in the recursive term (Postgres allows only one): the
    # LATERAL VALUES unnests both parent_id and commercial_partner_id into rows so
    # one JOIN onto `keep` walks both ancestor links per hop.
    return (
        "CREATE TEMP TABLE res_partner_keep ON COMMIT DROP AS\n"
        "WITH RECURSIVE keep(id) AS (\n"
        "    SELECT partner_id FROM res_users WHERE partner_id IS NOT NULL\n"
        "    UNION SELECT partner_id FROM res_company WHERE partner_id IS NOT NULL\n"
        "    UNION SELECT v.anc FROM keep k\n"
        "        JOIN res_partner p ON p.id = k.id\n"
        "        CROSS JOIN LATERAL (VALUES (p.parent_id), (p.commercial_partner_id)) AS v(anc)\n"
        "        WHERE v.anc IS NOT NULL\n"
        ")\n"
        "SELECT DISTINCT id FROM keep;\n"
        "CREATE INDEX ON res_partner_keep (id);"
    )


def _fk_edges_into(
    table: str, db_name: str, host: str = DEFAULT_DB_HOST, port: int = 18432, user: str = DEFAULT_DB_USER
) -> list[tuple[str, str, str]]:
    """Return (child_table, child_col, confdeltype) for every FK referencing ``table``.

    ``confdeltype``: 'c' cascade, 'n' set null, 'r' restrict, 'a' no action, 'd' set default.
    """
    _check_identifier(table)
    query = (
        "SELECT con.conrelid::regclass::text, a.attname, con.confdeltype "
        "FROM pg_constraint con "
        "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1] "
        f"WHERE con.contype = 'f' AND con.confrelid = '{table}'::regclass;"
    )
    ok, rows = _run_psql_tuples(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return []
    edges: list[tuple[str, str, str]] = []
    for r in rows:
        if len(r) == 3 and _SQL_IDENTIFIER_RE.match(r[0]) and _SQL_IDENTIFIER_RE.match(r[1]):
            edges.append((r[0], r[1], r[2]))
    return edges


def _transient_tables(
    db_name: str, host: str = DEFAULT_DB_HOST, port: int = 18432, user: str = DEFAULT_DB_USER
) -> set[str]:
    """Return the Postgres table names backing Odoo TransientModels (wizards).

    Odoo flags transient models in ``ir_model.transient``; their rows are throwaway
    wizard state (e.g. ``account.payment.register``), safe to clear during a purge.
    The table name follows Odoo's convention of the model with ``.`` replaced by ``_``.
    Returns an empty set on any error (schema/version drift) so the caller falls back
    to the conservative drift guard.
    """
    ok, rows = _run_psql_tuples(
        "SELECT model FROM ir_model WHERE transient = true;", db=db_name, host=host, port=port, user=user
    )
    if not ok:
        return set()
    tables: set[str] = set()
    for r in rows:
        if r and r[0]:
            table = r[0].replace(".", "_")
            if _SQL_IDENTIFIER_RE.match(table):
                tables.add(table)
    return tables


def _cascade_child_edges(
    parents: list[str], db_name: str, host: str = DEFAULT_DB_HOST, port: int = 18432, user: str = DEFAULT_DB_USER
) -> list[tuple[str, str, str]]:
    """Return (child_table, child_col, parent_table) for ON-DELETE-CASCADE FKs whose
    referenced table is one of ``parents``."""
    if not parents:
        return []
    safe = [_check_identifier(p) for p in parents]
    in_list = ", ".join(f"'{p}'" for p in safe)
    query = (
        "SELECT con.conrelid::regclass::text, a.attname, con.confrelid::regclass::text "
        "FROM pg_constraint con "
        "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1] "
        f"WHERE con.contype = 'f' AND con.confdeltype = 'c' AND con.confrelid::regclass::text IN ({in_list});"
    )
    ok, rows = _run_psql_tuples(query, db=db_name, host=host, port=port, user=user)
    if not ok:
        return []
    edges: list[tuple[str, str, str]] = []
    for r in rows:
        if len(r) == 3 and all(_SQL_IDENTIFIER_RE.match(x) for x in r):
            edges.append((r[0], r[1], r[2]))
    return edges


def _partner_cascade_delete_plan(
    db_name: str, host: str = DEFAULT_DB_HOST, port: int = 18432, user: str = DEFAULT_DB_USER
) -> list[str]:
    """Ordered DELETE statements that remove non-kept res_partner rows + their
    ON-DELETE-CASCADE descendants without leaving orphans (deepest child first).

    Walks the cascade FK graph outward from res_partner via a bounded BFS, tracking
    the per-hop FK column so each child delete is row-scoped to the ancestor chain
    (``col IN (SELECT id FROM parent WHERE <parent-delete-cond>)``). The final
    statement deletes the non-kept partners themselves. Runs under FK enforcement
    off, so ordering is for orphan-avoidance, not delete success.
    """
    frontier: dict[str, str] = {"res_partner": _PARTNER_DELETE_WHERE}
    seen = {"res_partner"}
    levels: list[dict[str, str]] = []
    for _ in range(_PARTNER_CASCADE_MAX_DEPTH):
        edges = _cascade_child_edges(list(frontier), db_name, host=host, port=port, user=user)
        next_frontier: dict[str, str] = {}
        for child, col, parent in edges:
            if child in seen or parent not in frontier:
                continue
            cond = f'"{col}" IN (SELECT id FROM "{parent}" WHERE {frontier[parent]})'
            next_frontier[child] = f"{next_frontier[child]} OR {cond}" if child in next_frontier else cond
        if not next_frontier:
            break
        seen |= set(next_frontier)
        levels.append(next_frontier)
        frontier = next_frontier

    statements: list[str] = []
    for level in reversed(levels):
        for child, cond in level.items():
            statements.append(f'DELETE FROM "{child}" WHERE {cond};')
    statements.append(f"DELETE FROM res_partner WHERE {_PARTNER_DELETE_WHERE};")
    return statements


def _partner_purge_model_list(purged_tables: list[str]) -> list[str]:
    """Odoo model names (for the attachment filter) of the purged root tables."""
    return [PURGE_MODEL_NAMES[t] for t in purged_tables if t in PURGE_MODEL_NAMES]


def count_deletable_partners(
    db_name: str, host: str = DEFAULT_DB_HOST, port: int = 18432, user: str = DEFAULT_DB_USER
) -> int:
    """Count res_partner rows the master-data purge would delete (non-user/company)."""
    ok, rows = _run_psql_tuples(
        "WITH keep AS (SELECT partner_id AS id FROM res_users WHERE partner_id IS NOT NULL "
        "UNION SELECT partner_id FROM res_company WHERE partner_id IS NOT NULL) "
        "SELECT count(*) FROM res_partner WHERE id NOT IN (SELECT id FROM keep);",
        db=db_name,
        host=host,
        port=port,
        user=user,
    )
    if ok and rows and rows[0] and rows[0][0].isdigit():
        return int(rows[0][0])
    return 0


def _attachment_delete_sql(model_names: list[str]) -> str:
    """DELETE for ir_attachment: rows of removed records (by res_model) plus the
    avatars of removed partners. Product/view/module/company/user attachments are
    never named, so product images and system assets survive."""
    models = ", ".join(_sql_literal(m) for m in sorted(set(model_names)))
    clause = f"res_model IN ({models}) OR " if models else ""
    return (
        f"DELETE FROM ir_attachment WHERE {clause}"
        "(res_model = 'res.partner' AND res_id IS NOT NULL AND res_id NOT IN (SELECT id FROM res_partner));"
    )


def purge_master_data(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Full template-DB reset: delete movement + content + customer/partner data.

    Keeps products, pricelists, users (+ their partner), companies (+ their partner)
    and config; deletes everything transactional plus CRM/HR/helpdesk/mail content,
    the customer/vendor/contact partners, and the attachments of all removed records.
    Runs as ONE transaction with ``session_replication_role = replica`` (superuser
    required). Aborts with no deletion if the movement/content cascade would reach a
    protected master table, or if an unhandled FK still references a to-be-deleted
    partner after the content purge (drift guard).

    Args:
        dry_run: If True, delete nothing and return a summary of what would be removed.

    Returns:
        Tuple of (success, summary_or_error).
    """
    movement = resolve_purge_tables(db_name, host=host, port=port, user=user)
    content = _resolve_content_purge_tables(db_name, host=host, port=port, user=user)

    move_closure = _cascade_closure(movement, db_name, host=host, port=port, user=user) if movement else set()
    content_closure = _cascade_closure(content, db_name, host=host, port=port, user=user) if content else set()
    full_closure = move_closure | content_closure

    breached = sorted(full_closure & PURGE_PROTECTED_TABLES)
    if breached:
        return (
            False,
            f"Aborted — the movement/content purge would also empty protected table(s): {', '.join(breached)}. "
            "A custom/OCA module likely adds an ON DELETE CASCADE foreign key into a purged table. No data deleted.",
        )

    edges = _fk_edges_into("res_partner", db_name, host=host, port=port, user=user)
    setnull_edges = [(c, col) for c, col, t in edges if t == "n" and c != "res_partner"]
    raw_unhandled = [(c, col) for c, col, t in edges if t not in ("c", "n") and c not in ("res_users", "res_company")]
    # Transient (wizard) tables carry throwaway rows — clear them wholesale instead of
    # aborting on their unhandled FK. Non-transient unknowns still hit the drift guard.
    transient = _transient_tables(db_name, host=host, port=port, user=user)
    transient_edges = [(c, col) for c, col in raw_unhandled if c in transient]
    unhandled_edges = [(c, col) for c, col in raw_unhandled if c not in transient]

    if dry_run:
        to_delete = count_deletable_partners(db_name, host=host, port=port, user=user)
        return True, (
            f"[dry-run] would empty {len(full_closure)} movement/content table(s), "
            f"delete {to_delete} partner(s) (customers/vendors/contacts), and their attachments. "
            "Kept: products, pricelists, users, companies, config."
        )

    if not _is_superuser(db_name, host, port, user):
        return (
            False,
            "Aborted — master-data purge requires a superuser role (to disable FK enforcement during the bulk "
            "delete). Connect as the database superuser and retry. No data deleted.",
        )

    repairs = _null_repair_targets(full_closure, db_name, host=host, port=port, user=user)
    partner_deletes = _partner_cascade_delete_plan(db_name, host=host, port=port, user=user)
    model_names = _partner_purge_model_list(movement + content)

    stmts = ["BEGIN;", "SET LOCAL session_replication_role = replica;"]
    # 1-2. movement + content whole-table closure, then SET-NULL back-references from kept tables.
    for table in sorted(full_closure):
        _check_identifier(table)
        stmts.append(f'DELETE FROM "{table}";')
    for table, column in repairs:
        _check_identifier(table)
        _check_identifier(column)
        stmts.append(f'UPDATE "{table}" SET "{column}" = NULL WHERE "{column}" IS NOT NULL;')
    # 3. partner keep set.
    stmts.append(_keep_partner_temp_table_sql())
    # 3-pre. Clear transient (wizard) tables that carry an unhandled FK into res_partner —
    # throwaway wizard state (e.g. account_payment_register). Emptying them here keeps the
    # drift guard from aborting, without touching any real master data.
    for child in sorted({c for c, _ in transient_edges}):
        _check_identifier(child)
        stmts.append(f'DELETE FROM "{child}";')
    # 3a. drift guard: an unhandled FK still pointing at a to-be-deleted partner aborts (rollback).
    for child, col in unhandled_edges:
        _check_identifier(child)
        _check_identifier(col)
        stmts.append(
            'DO $$ BEGIN IF EXISTS (SELECT 1 FROM "' + child + '" WHERE "' + col + '" IS NOT NULL '
            'AND "' + col + '" NOT IN (SELECT id FROM res_partner_keep)) THEN '
            f"RAISE EXCEPTION 'odoodev-purge-abort: unhandled FK {child}.{col} still references a partner to delete'; "
            "END IF; END $$;"
        )
    # 3b. partner cascade deletes (deepest first) + final res_partner delete.
    stmts.extend(partner_deletes)
    # 3c. defensive assertion: no kept row left with a dangling self-reference.
    stmts.append(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM res_partner WHERE parent_id IS NOT NULL "
        "AND parent_id NOT IN (SELECT id FROM res_partner)) THEN "
        "RAISE EXCEPTION 'odoodev-purge-abort: kept partner has a dangling parent_id (keep-set bug)'; "
        "END IF; END $$;"
    )
    # 3d. SET-NULL repair for kept tables that reference a now-deleted partner.
    for child, col in setnull_edges:
        _check_identifier(child)
        _check_identifier(col)
        stmts.append(
            f'UPDATE "{child}" SET "{col}" = NULL WHERE "{col}" IS NOT NULL '
            f'AND "{col}" NOT IN (SELECT id FROM res_partner);'
        )
    # 4. attachments of removed records (product/system attachments never targeted).
    stmts.append(_attachment_delete_sql(model_names))
    stmts.append("COMMIT;")

    ok, err = _run_psql_file("\n".join(stmts), db=db_name, host=host, port=port, user=user)
    if not ok:
        detail = err.strip()
        if "odoodev-purge-abort" in detail:
            return False, f"Aborted (no data deleted): {detail}"
        return False, f"Master-data purge failed: {detail}"
    return True, (
        f"{len(full_closure)} movement/content table(s) emptied, non-user/company partners deleted, "
        f"attachments of removed records purged (products, pricelists, users, companies, config kept)"
    )


# Heuristic multiplier for estimating the uncompressed size of compressed
# backups whose contained sizes cannot be read cheaply (tar.zst, 7z, tar.gz,
# gz). Filestores are largely incompressible (images/PDFs) while SQL dumps
# compress well; 3x is a conservative middle ground.
RESTORE_COMPRESSION_FACTOR = 3


def estimate_uncompressed_size(backup_file: str) -> int:
    """Estimate the on-disk size a backup occupies once extracted.

    Exact for ZIP archives (the ZIP central directory carries each entry's
    uncompressed size) and for already-uncompressed formats (.sql/.dump/.tar).
    For opaquely-compressed formats (.tar.zst/.7z/.tar.gz/.tgz/.gz) it applies
    :data:`RESTORE_COMPRESSION_FACTOR` to the compressed file size.

    Args:
        backup_file: Path to the backup file.

    Returns:
        Estimated uncompressed size in bytes (0 if the file is unreadable).
    """
    try:
        compressed = os.path.getsize(backup_file)
    except OSError:
        return 0

    name = os.path.basename(backup_file).lower()

    if name.endswith(".zip"):
        try:
            with zipfile.ZipFile(backup_file) as zf:
                return sum(info.file_size for info in zf.infolist())
        except (zipfile.BadZipFile, OSError):
            return compressed * RESTORE_COMPRESSION_FACTOR

    # Already uncompressed — extraction is effectively a copy of the same size.
    if name.endswith((".sql", ".dump", ".tar")):
        return compressed

    # Opaquely compressed archives — apply the heuristic factor.
    if name.endswith((".tar.zst", ".7z", ".tar.gz", ".tgz", ".tar.bz2", ".gz")):
        return compressed * RESTORE_COMPRESSION_FACTOR

    # Unknown extension — be conservative.
    return compressed * RESTORE_COMPRESSION_FACTOR


def _nearest_existing_dir(path: str) -> str:
    """Return the closest existing ancestor directory of ``path``.

    ``shutil.disk_usage`` needs an existing path; the filestore destination
    usually does not exist yet before a restore.
    """
    current = os.path.abspath(path)
    while current and not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current or os.path.sep


def check_restore_space(
    backup_file: str,
    temp_dir: str,
    filestore_dest: str,
    margin: float = 1.15,
) -> tuple[bool, str, int]:
    """Check whether there is enough free disk space to restore a backup.

    Estimates the uncompressed payload and compares it against the free space
    on the extraction filesystem and on the filestore destination filesystem.
    When both live on the same device the requirement is checked jointly;
    otherwise each filesystem is conservatively checked against the full
    estimate (the filestore/SQL split is unknown before extraction).

    Pure computation — no output, no side effects.

    Args:
        backup_file: Path to the backup file.
        temp_dir: Directory the backup is extracted into.
        filestore_dest: Final filestore directory (may not exist yet).
        margin: Safety multiplier applied to the estimate (default 1.15).

    Returns:
        Tuple ``(enough, message, estimated_bytes)``. ``message`` is a
        human-readable, single-line summary suitable for ``print_warning``.
    """
    estimated = estimate_uncompressed_size(backup_file)
    required = int(estimated * margin)

    temp_anchor = _nearest_existing_dir(temp_dir)
    dest_anchor = _nearest_existing_dir(filestore_dest)

    try:
        temp_free = shutil.disk_usage(temp_anchor).free
        dest_free = shutil.disk_usage(dest_anchor).free
    except OSError:
        # Cannot determine free space — do not block the restore.
        return True, "", estimated

    try:
        same_fs = os.stat(temp_anchor).st_dev == os.stat(dest_anchor).st_dev
    except OSError:
        same_fs = False

    if same_fs:
        # Extraction + filestore share the device; peak demand is the payload
        # plus the filestore that is relocated (rename = no extra space).
        enough = temp_free >= required
        free_repr = format_size(temp_free)
    else:
        enough = temp_free >= required and dest_free >= required
        free_repr = f"temp {format_size(temp_free)} / filestore {format_size(dest_free)}"

    if enough:
        msg = ""
    else:
        msg = (
            f"Low disk space for restore: estimated need ~{format_size(required)} "
            f"(uncompressed {format_size(estimated)} + {int((margin - 1) * 100)}% margin), "
            f"available {free_repr}."
        )
    return enough, msg, estimated


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def get_restore_temp_dir(backup_file: str) -> str:
    """Choose a temp directory for backup extraction.

    On Linux, /tmp is typically a tmpfs (RAM-based) with limited capacity,
    so we always use $HOME/odoodev-tmp. On macOS, /tmp is disk-backed
    and safe to use directly.

    Args:
        backup_file: Path to the backup file (unused, kept for API compat).

    Returns:
        Path to a newly created temp directory for extraction.
    """
    import platform

    if platform.system() == "Darwin":
        return tempfile.mkdtemp(prefix="odoodev_restore_")

    # Linux: always use $HOME/odoodev-tmp to avoid tmpfs space issues
    home_tmp = os.path.join(os.path.expanduser("~"), "odoodev-tmp")
    os.makedirs(home_tmp, exist_ok=True)
    return tempfile.mkdtemp(prefix="odoodev_restore_", dir=home_tmp)


def cleanup_restore_temp(extract_path: str) -> None:
    """Clean up restore temp directory and parent odoodev-tmp if empty.

    Args:
        extract_path: Path to the extraction directory to remove.
    """
    try:
        shutil.rmtree(extract_path)
    except OSError:
        logger.warning("Could not remove temp files: %s", extract_path)
        return

    # Clean up $HOME/odoodev-tmp parent if it exists and is now empty
    parent = os.path.dirname(extract_path)
    home_tmp = os.path.join(os.path.expanduser("~"), "odoodev-tmp")
    if os.path.normpath(parent) == os.path.normpath(home_tmp):
        try:
            if not os.listdir(parent):
                os.rmdir(parent)
        except OSError:
            pass
