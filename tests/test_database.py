"""Tests for odoodev.core.database module."""

from __future__ import annotations

import os
import zipfile

import pytest

from odoodev.core.database import (
    cleanup_restore_temp,
    copy_filestore,
    detect_backup_type,
    extract_backup,
    format_size,
    get_filestore_path,
    get_restore_temp_dir,
)


class TestExtractBackup:
    def test_extract_zip(self, tmp_dir):
        """ZIP backup extracts correctly."""
        zip_path = os.path.join(tmp_dir, "backup.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("dump.sql", "SELECT 1;")
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(zip_path, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))

    def test_extract_zip_with_filestore(self, tmp_dir):
        """ZIP backup with filestore subdirectory extracts correctly."""
        zip_path = os.path.join(tmp_dir, "backup.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("dump.sql", "SELECT 1;")
            zf.writestr("filestore/test.txt", "data")
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(zip_path, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "filestore", "test.txt"))

    def test_extract_sql_file(self, tmp_dir):
        """Direct SQL file is copied as dump.sql."""
        sql_path = os.path.join(tmp_dir, "backup.sql")
        with open(sql_path, "w") as f:
            f.write("SELECT 1;")
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(sql_path, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))

    def test_extract_dump_file(self, tmp_dir):
        """Direct .dump file is copied as dump.sql."""
        dump_path = os.path.join(tmp_dir, "backup.dump")
        with open(dump_path, "w") as f:
            f.write("SELECT 1;")
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(dump_path, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))

    def test_unsupported_format(self, tmp_dir):
        """Unsupported format returns False."""
        path = os.path.join(tmp_dir, "backup.xyz")
        with open(path, "w") as f:
            f.write("data")
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(path, extract_path) is False

    def test_zip_path_traversal_blocked(self, tmp_dir):
        """Path traversal in ZIP members is rejected."""
        zip_path = os.path.join(tmp_dir, "evil.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../etc/passwd", "root:x:0:0")
        extract_path = os.path.join(tmp_dir, "extracted")
        with pytest.raises(ValueError, match="path traversal"):
            extract_backup(zip_path, extract_path)

    def test_creates_extract_dir(self, tmp_dir):
        """Extract directory is created if it doesn't exist."""
        sql_path = os.path.join(tmp_dir, "backup.sql")
        with open(sql_path, "w") as f:
            f.write("SELECT 1;")
        extract_path = os.path.join(tmp_dir, "deep", "nested", "dir")
        assert extract_backup(sql_path, extract_path) is True
        assert os.path.isdir(extract_path)


class TestDetectBackupType:
    def test_detects_root_sql(self, tmp_dir):
        """Detects dump.sql in root of extracted directory."""
        os.makedirs(tmp_dir, exist_ok=True)
        with open(os.path.join(tmp_dir, "dump.sql"), "w") as f:
            f.write("SELECT 1;")
        result = detect_backup_type(tmp_dir)
        assert result is not None
        assert result["sql_file"].endswith("dump.sql")

    def test_detects_root_sql_with_filestore(self, tmp_dir):
        """Detects dump.sql + filestore directory."""
        with open(os.path.join(tmp_dir, "dump.sql"), "w") as f:
            f.write("SELECT 1;")
        fs_dir = os.path.join(tmp_dir, "filestore")
        os.makedirs(fs_dir)
        result = detect_backup_type(tmp_dir)
        assert result is not None
        assert result["filestore"] == fs_dir

    def test_detects_nested_sql(self, tmp_dir):
        """Detects dump.sql in subdirectory."""
        sub = os.path.join(tmp_dir, "backup_contents")
        os.makedirs(sub)
        with open(os.path.join(sub, "dump.sql"), "w") as f:
            f.write("SELECT 1;")
        result = detect_backup_type(tmp_dir)
        assert result is not None
        assert "dump.sql" in result["sql_file"]

    def test_returns_none_when_no_sql(self, tmp_dir):
        """Returns None when no dump.sql exists."""
        with open(os.path.join(tmp_dir, "other.txt"), "w") as f:
            f.write("data")
        assert detect_backup_type(tmp_dir) is None

    def test_returns_none_for_empty_dir(self, tmp_dir):
        assert detect_backup_type(tmp_dir) is None


class TestCopyFilestore:
    def test_copies_files(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        dest = os.path.join(tmp_dir, "dest")
        os.makedirs(src)
        with open(os.path.join(src, "file.txt"), "w") as f:
            f.write("data")
        assert copy_filestore(src, dest) is True
        assert os.path.exists(os.path.join(dest, "file.txt"))

    def test_copies_subdirectories(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        sub = os.path.join(src, "sub")
        dest = os.path.join(tmp_dir, "dest")
        os.makedirs(sub)
        with open(os.path.join(sub, "file.txt"), "w") as f:
            f.write("data")
        assert copy_filestore(src, dest) is True
        assert os.path.exists(os.path.join(dest, "sub", "file.txt"))

    def test_skips_dump_sql(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        dest = os.path.join(tmp_dir, "dest")
        os.makedirs(src)
        with open(os.path.join(src, "dump.sql"), "w") as f:
            f.write("SELECT 1;")
        with open(os.path.join(src, "file.txt"), "w") as f:
            f.write("data")
        assert copy_filestore(src, dest) is True
        assert not os.path.exists(os.path.join(dest, "dump.sql"))
        assert os.path.exists(os.path.join(dest, "file.txt"))

    def test_returns_false_for_missing_src(self, tmp_dir):
        assert copy_filestore(os.path.join(tmp_dir, "missing"), os.path.join(tmp_dir, "dest")) is False


class TestFormatSize:
    def test_bytes(self):
        assert format_size(512) == "512.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self):
        assert format_size(1024**3) == "1.0 GB"

    def test_terabytes(self):
        assert format_size(1024**4) == "1.0 TB"

    def test_zero(self):
        assert format_size(0) == "0.0 B"


class TestGetFilestorePath:
    def test_returns_version_specific_path(self):
        path = get_filestore_path("18", "mydb")
        assert "v18" in path
        assert "mydb" in path
        assert path.endswith(os.path.join("v18", "filestore", "mydb"))

    def test_different_versions(self):
        p16 = get_filestore_path("16", "db")
        p18 = get_filestore_path("18", "db")
        assert p16 != p18


class TestGetRestoreTempDir:
    def test_returns_existing_directory(self):
        path = get_restore_temp_dir("backup.zip")
        assert os.path.isdir(path)
        os.rmdir(path)

    def test_contains_odoodev_prefix(self):
        path = get_restore_temp_dir("backup.zip")
        assert "odoodev_restore_" in os.path.basename(path)
        os.rmdir(path)


class TestCleanupRestoreTemp:
    def test_removes_temp_dir(self, tmp_dir):
        target = os.path.join(tmp_dir, "restore_temp")
        os.makedirs(target)
        with open(os.path.join(target, "dump.sql"), "w") as f:
            f.write("data")
        cleanup_restore_temp(target)
        assert not os.path.exists(target)

    def test_handles_nonexistent_dir(self, tmp_dir):
        """Does not raise for missing directory."""
        cleanup_restore_temp(os.path.join(tmp_dir, "nonexistent"))
