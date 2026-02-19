"""PostgreSQL database operations for Odoo development."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import zipfile

logger = logging.getLogger(__name__)

# Default credentials
DEFAULT_DB_USER = "ownerp"
DEFAULT_DB_PASSWORD = "CHANGE_AT_FIRST"
DEFAULT_DB_HOST = "localhost"


def _get_pg_env(host: str = DEFAULT_DB_HOST, port: int = 15432) -> dict[str, str]:
    """Get environment variables for PostgreSQL commands."""
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ.get("PGPASSWORD", DEFAULT_DB_PASSWORD)
    env["PGHOST"] = host
    env["PGPORT"] = str(port)
    return env


def _run_psql(
    command: str,
    db: str | None = None,
    host: str = DEFAULT_DB_HOST,
    port: int = 15432,
    user: str = DEFAULT_DB_USER,
) -> tuple[bool, str]:
    """Execute a psql command.

    Returns:
        Tuple of (success, output_or_error).
    """
    env = _get_pg_env(host, port)
    cmd = f"psql -U {user} -h {host} -p {port}"
    if db:
        cmd += f" -d {db}"
    cmd += f" -c \"{command}\""

    try:
        result = subprocess.run(
            cmd, shell=True, check=True, capture_output=True, text=True, env=env,
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


def database_exists(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 15432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Check if a database exists."""
    env = _get_pg_env(host, port)
    cmd = f"psql -U {user} -h {host} -p {port} -lqt | cut -d \\| -f 1 | grep -qw {db_name}"
    result = subprocess.run(cmd, shell=True, capture_output=True, env=env)
    return result.returncode == 0


def list_databases(
    host: str = DEFAULT_DB_HOST,
    port: int = 15432,
    user: str = DEFAULT_DB_USER,
) -> list[str]:
    """List all databases.

    Returns:
        List of database names.
    """
    env = _get_pg_env(host, port)
    cmd = f"psql -U {user} -h {host} -p {port} -lqt"
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, env=env)
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
    port: int = 15432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Drop a database."""
    if not database_exists(db_name, host, port, user):
        logger.info("Database %s does not exist. Skipping.", db_name)
        return True

    env = _get_pg_env(host, port)
    cmd = f"dropdb -U {user} -h {host} -p {port} {db_name}"
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, env=env)
        logger.info("Database %s dropped.", db_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to drop %s: %s", db_name, e.stderr)
        return False


def create_database(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 15432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Create a new database."""
    env = _get_pg_env(host, port)
    cmd = f"createdb -U {user} -T template1 -h {host} -p {port} {db_name}"
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, env=env)
        logger.info("Database %s created.", db_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Failed to create %s: %s", db_name, e.stderr)
        return False


def restore_database(
    db_name: str,
    sql_file: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 15432,
    user: str = DEFAULT_DB_USER,
) -> bool:
    """Restore a database from SQL file."""
    env = _get_pg_env(host, port)
    cmd = f"psql -U {user} -h {host} -p {port} -d {db_name} -f {sql_file}"
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, env=env)
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
                zf.extractall(extract_path)
            return True

        # TAR files
        if ext in (".tar", ".tgz"):
            result = subprocess.run(
                ["tar", "-xf", backup_file, "-C", extract_path],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0

        # GZIP files
        if ext == ".gz":
            result = subprocess.run(
                f'gunzip -c "{backup_file}" > "{extract_path}/dump.sql"',
                shell=True,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0

        # Direct SQL files
        if ext in (".sql", ".dump"):
            shutil.copy(backup_file, os.path.join(extract_path, "dump.sql"))
            return True

        logger.error("Unsupported backup format: %s", ext)
        return False

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

    Args:
        odoo_version: Odoo version string
        db_name: Database name

    Returns:
        Path to filestore directory.
    """
    return os.path.join(
        os.path.expanduser("~"),
        "odoo-share",
        "filestore",
        db_name,
    )


def deactivate_cronjobs(
    db_name: str,
    host: str = DEFAULT_DB_HOST,
    port: int = 15432,
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
    port: int = 15432,
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
