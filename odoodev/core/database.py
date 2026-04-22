"""PostgreSQL database operations for Odoo development."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import zipfile

logger = logging.getLogger(__name__)

# Default credentials — kept as module constants for signature defaults.
# Actual values come from global config at runtime via _get_default_credentials().
DEFAULT_DB_USER = "ownerp"
DEFAULT_DB_PASSWORD = "CHANGE_AT_FIRST"  # noqa: S105 — placeholder, warned at runtime
DEFAULT_DB_HOST = "localhost"

_insecure_default_warned = False


def _warn_once_on_placeholder(password: str) -> None:
    """Emit a one-shot warning when the placeholder default password is in use."""
    global _insecure_default_warned
    if _insecure_default_warned or password != DEFAULT_DB_PASSWORD:
        return
    _insecure_default_warned = True
    logger.warning(
        "PostgreSQL credentials fall back to the placeholder password %r — "
        "run `odoodev setup` to configure a real password.",
        DEFAULT_DB_PASSWORD,
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
    env = _get_pg_env(host, port)
    cmd = ["psql", "-U", user, "-h", host, "-p", str(port)]
    if db:
        cmd.extend(["-d", db])
    cmd.extend(["-c", command])

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def database_exists(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Check if a database exists."""
    env = _get_pg_env(host, port)
    cmd = ["psql", "-U", user, "-h", host, "-p", str(port), "-lqt"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        for line in result.stdout.split("\n"):
            parts = line.split("|")
            if parts and parts[0].strip() == db_name:
                return True
        return False
    except subprocess.CalledProcessError:
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
    env = _get_pg_env(host, port)
    cmd = ["psql", "-U", user, "-h", host, "-p", str(port), "-lqt"]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        databases = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split("|")
            if parts:
                name = parts[0].strip()
                if name and name not in ("", "template0", "template1", "postgres"):
                    databases.append(name)
        return sorted(databases)
    except subprocess.CalledProcessError:
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

    env = _get_pg_env(host, port)
    cmd = ["dropdb", "-U", user, "-h", host, "-p", str(port), db_name]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        logger.info("Database %s dropped.", db_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to drop %s: %s", db_name, e.stderr)
        return False


def create_database(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Create a new database."""
    env = _get_pg_env(host, port)
    cmd = ["createdb", "-U", user, "-T", "template1", "-h", host, "-p", str(port), db_name]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        logger.info("Database %s created.", db_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to create %s: %s", db_name, e.stderr)
        return False


def restore_database(
    db_name: str,
    sql_file: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Restore a database from SQL file."""
    env = _get_pg_env(host, port)
    cmd = ["psql", "-U", user, "-h", host, "-p", str(port), "-d", db_name, "-f", sql_file]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        logger.info("Database %s restored from %s.", db_name, sql_file)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to restore %s: %s", db_name, e.stderr)
        return False


def extract_backup(backup_file: str, extract_path: str) -> bool:
    """Extract a backup file (ZIP, 7z, tar, gz, SQL).

    Args:
        backup_file: Path to backup file
        extract_path: Directory to extract into

    Returns:
        True if extraction successful.
    """
    os.makedirs(extract_path, exist_ok=True)

    ext = os.path.splitext(backup_file)[1].lower()

    try:
        # 7z files
        if ext == ".7z":
            for cmd_7z in ("7zz", "7z"):
                if shutil.which(cmd_7z):
                    result = subprocess.run(
                        [cmd_7z, "x", backup_file, f"-o{extract_path}"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        return True
            logger.error("7z not found. Install: brew install 7zip (macOS) or apt install p7zip-full")
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

        # TAR files
        if ext in (".tar", ".tgz"):
            import tarfile

            with tarfile.open(backup_file) as tf:
                # Validate all members before extraction to prevent path traversal (CWE-22)
                safe_base = os.path.normpath(os.path.abspath(extract_path))
                for member in tf.getmembers():
                    member_path = os.path.normpath(os.path.abspath(os.path.join(extract_path, member.name)))
                    if not member_path.startswith(safe_base + os.sep) and member_path != safe_base:
                        msg = f"Tar path traversal detected: {member.name}"
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
    env = _get_pg_env(host, port)
    cmd = ["pg_dump", "-U", user, "-h", host, "-p", str(port), db_name]
    try:
        with open(output_path, "w", encoding="utf-8") as outfile:
            subprocess.run(cmd, check=True, stdout=outfile, stderr=subprocess.PIPE, text=True, env=env)
        logger.info("Database %s dumped to %s", db_name, output_path)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to dump %s: %s", db_name, e.stderr)
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


def deactivate_cloud(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 18432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Deactivate Nextcloud/Office365 integration."""
    queries = [
        "UPDATE ir_config_parameter SET value = '' WHERE key LIKE '%nextcloud%';",
        "UPDATE ir_config_parameter SET value = '' WHERE key LIKE '%office365%';",
    ]
    success = True
    for query in queries:
        ok, _ = _run_psql(query, db=db_name, host=host, port=port, user=user)
        if not ok:
            success = False
    return success


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
