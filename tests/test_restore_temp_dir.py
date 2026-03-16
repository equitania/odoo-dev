"""Tests for restore temp directory selection."""

import os
import platform
import shutil

import pytest

from odoodev.core.database import cleanup_restore_temp, format_size, get_restore_temp_dir


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
    """Test get_restore_temp_dir platform-based selection."""

    def test_creates_unique_directories(self, small_backup):
        """Each call should create a unique temp directory."""
        dir1 = get_restore_temp_dir(small_backup)
        dir2 = get_restore_temp_dir(small_backup)
        assert dir1 != dir2
        assert os.path.isdir(dir1)
        assert os.path.isdir(dir2)
        shutil.rmtree(dir1, ignore_errors=True)
        shutil.rmtree(dir2, ignore_errors=True)

    def test_macos_uses_system_tmp(self, small_backup, monkeypatch):
        """On macOS, should use system temp directory."""
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        result = get_restore_temp_dir(small_backup)
        assert os.path.isdir(result)
        assert "odoodev_restore_" in result
        shutil.rmtree(result, ignore_errors=True)

    def test_linux_uses_home_tmp(self, small_backup, fake_home, monkeypatch):
        """On Linux, should always use $HOME/odoodev-tmp."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        result = get_restore_temp_dir(small_backup)
        assert os.path.isdir(result)
        assert "odoodev_restore_" in result
        home_tmp = os.path.join(str(fake_home), "odoodev-tmp")
        assert result.startswith(home_tmp)
        shutil.rmtree(result, ignore_errors=True)

    def test_linux_creates_home_tmp_parent(self, small_backup, fake_home, monkeypatch):
        """On Linux, should create $HOME/odoodev-tmp if it doesn't exist."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        home_tmp = fake_home / "odoodev-tmp"
        assert not home_tmp.exists()
        result = get_restore_temp_dir(small_backup)
        assert home_tmp.exists()
        shutil.rmtree(result, ignore_errors=True)


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
