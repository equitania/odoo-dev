"""Tests for restore temp directory selection with space check."""

import os
import shutil
import tempfile
from collections import namedtuple

import pytest

from odoodev.core.database import cleanup_restore_temp, format_size, get_restore_temp_dir

DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


@pytest.fixture
def small_backup(tmp_path):
    """Create a small test backup file (1 KB)."""
    backup = tmp_path / "test_backup.zip"
    backup.write_bytes(b"x" * 1024)
    return str(backup)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Use tmp_path as $HOME to avoid touching real home."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


class TestGetRestoreTempDir:
    """Test get_restore_temp_dir space checking."""

    def test_uses_system_tmp_when_enough_space(self, small_backup):
        """Small backup should use system temp."""
        result = get_restore_temp_dir(small_backup)
        assert os.path.isdir(result)
        assert "odoodev_restore_" in result
        shutil.rmtree(result, ignore_errors=True)

    def test_falls_back_to_home_when_tmp_full(self, small_backup, fake_home, monkeypatch):
        """When system tmp reports no space, fall back to $HOME/odoodev-tmp."""
        real_disk_usage = shutil.disk_usage
        system_tmp = tempfile.gettempdir()

        def mock_disk_usage(path):
            if os.path.normpath(path) == os.path.normpath(system_tmp):
                usage = real_disk_usage(path)
                return DiskUsage(usage.total, usage.used, 0)
            return real_disk_usage(path)

        monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)

        result = get_restore_temp_dir(small_backup)
        assert os.path.isdir(result)
        assert "odoodev_restore_" in result
        home_tmp = os.path.join(str(fake_home), "odoodev-tmp")
        assert result.startswith(home_tmp)
        shutil.rmtree(result, ignore_errors=True)

    def test_result_is_unique_directory(self, small_backup):
        """Each call should create a unique temp directory."""
        dir1 = get_restore_temp_dir(small_backup)
        dir2 = get_restore_temp_dir(small_backup)
        assert dir1 != dir2
        shutil.rmtree(dir1, ignore_errors=True)
        shutil.rmtree(dir2, ignore_errors=True)


class TestCleanupRestoreTemp:
    """Test cleanup_restore_temp cleanup logic."""

    def test_removes_extract_directory(self, tmp_path):
        """Should remove the extract directory."""
        extract = tmp_path / "odoodev_restore_abc123"
        extract.mkdir()
        (extract / "dump.sql").write_text("test")

        cleanup_restore_temp(str(extract))
        assert not extract.exists()

    def test_removes_empty_odoodev_tmp_parent(self, fake_home):
        """Should remove $HOME/odoodev-tmp if empty after cleanup."""
        home_tmp = fake_home / "odoodev-tmp"
        home_tmp.mkdir()
        extract = home_tmp / "odoodev_restore_abc123"
        extract.mkdir()
        (extract / "dump.sql").write_text("test")

        cleanup_restore_temp(str(extract))
        assert not extract.exists()
        assert not home_tmp.exists()

    def test_keeps_nonempty_odoodev_tmp_parent(self, fake_home):
        """Should keep $HOME/odoodev-tmp if other files remain."""
        home_tmp = fake_home / "odoodev-tmp"
        home_tmp.mkdir()
        extract = home_tmp / "odoodev_restore_abc123"
        extract.mkdir()
        (extract / "dump.sql").write_text("test")
        other = home_tmp / "odoodev_restore_other"
        other.mkdir()

        cleanup_restore_temp(str(extract))
        assert not extract.exists()
        assert home_tmp.exists()

    def test_handles_already_deleted(self, tmp_path):
        """Should not crash if directory already gone."""
        nonexistent = str(tmp_path / "already_gone")
        cleanup_restore_temp(nonexistent)


class TestFormatSize:
    """Test format_size helper."""

    def test_bytes(self):
        assert format_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert format_size(7 * 1024 * 1024 * 1024) == "7.0 GB"
