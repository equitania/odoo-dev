"""Tests for odoodev db backup command and core backup functions."""

import io
import zipfile

import pytest
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.database import backup_database_sql, create_backup_zip, extract_backup


class TestBackupHelp:
    def test_db_backup_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "backup" in result.output

    def test_db_backup_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["db", "backup", "--help"])
        assert result.exit_code == 0
        assert "--name" in result.output
        assert "--type" in result.output
        assert "--output" in result.output


class TestCreateBackupZip:
    def test_zip_sql_only(self, tmp_path):
        """ZIP with SQL only (no filestore)."""
        sql_file = tmp_path / "dump.sql"
        sql_file.write_text("CREATE TABLE test;")
        output_zip = tmp_path / "backup.zip"

        result = create_backup_zip(str(sql_file), str(output_zip))
        assert result is True
        assert output_zip.exists()

        with zipfile.ZipFile(str(output_zip), "r") as zf:
            names = zf.namelist()
            assert "dump.sql" in names
            assert len(names) == 1

    def test_zip_with_filestore(self, tmp_path):
        """ZIP with SQL and filestore."""
        sql_file = tmp_path / "dump.sql"
        sql_file.write_text("CREATE TABLE test;")

        # Create fake filestore
        fs_dir = tmp_path / "filestore"
        fs_dir.mkdir()
        (fs_dir / "ab").mkdir()
        (fs_dir / "ab" / "file1.bin").write_bytes(b"\x00\x01\x02")
        (fs_dir / "cd").mkdir()
        (fs_dir / "cd" / "file2.bin").write_bytes(b"\x03\x04\x05")

        output_zip = tmp_path / "backup.zip"
        result = create_backup_zip(str(sql_file), str(output_zip), str(fs_dir))
        assert result is True

        with zipfile.ZipFile(str(output_zip), "r") as zf:
            names = zf.namelist()
            assert "dump.sql" in names
            assert "filestore/ab/file1.bin" in names
            assert "filestore/cd/file2.bin" in names

    def test_zip_nonexistent_filestore(self, tmp_path):
        """ZIP with non-existent filestore path → SQL only."""
        sql_file = tmp_path / "dump.sql"
        sql_file.write_text("CREATE TABLE test;")
        output_zip = tmp_path / "backup.zip"

        result = create_backup_zip(str(sql_file), str(output_zip), "/nonexistent/path")
        assert result is True

        with zipfile.ZipFile(str(output_zip), "r") as zf:
            names = zf.namelist()
            assert "dump.sql" in names
            assert len(names) == 1


class TestBackupDatabaseSql:
    def test_backup_sql_called(self, monkeypatch, tmp_path):
        """Test that pg_dump is called with correct argument list."""
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)

            class MockResult:
                returncode = 0
                stdout = ""
                stderr = ""

            return MockResult()

        monkeypatch.setattr("odoodev.core.database.subprocess.run", mock_run)

        output_path = str(tmp_path / "test.sql")
        result = backup_database_sql("testdb", output_path, host="localhost", port=18432, user="ownerp")
        assert result is True
        assert len(calls) == 1
        # Command is now a list, not a shell string
        assert calls[0][0] == "pg_dump"
        assert "testdb" in calls[0]
        assert "-U" in calls[0]
        assert "ownerp" in calls[0]


class TestExtractBackupZipTraversal:
    """Test ZIP path traversal protection (CWE-22)."""

    def test_safe_zip_extracts(self, tmp_path):
        """Normal ZIP without traversal extracts successfully."""
        zip_path = tmp_path / "safe.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("dump.sql", "CREATE TABLE test;")
            zf.writestr("filestore/ab/file1.bin", "data")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        result = extract_backup(str(zip_path), str(extract_dir))
        assert result is True
        assert (extract_dir / "dump.sql").exists()
        assert (extract_dir / "filestore" / "ab" / "file1.bin").exists()

    def test_traversal_zip_rejected(self, tmp_path):
        """ZIP with path traversal member is rejected with ValueError."""
        zip_path = tmp_path / "evil.zip"
        # Create ZIP with malicious path traversal entry
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("../../etc/evil.txt", "malicious content")
        zip_path.write_bytes(zip_buf.getvalue())

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with pytest.raises(ValueError, match="path traversal"):
            extract_backup(str(zip_path), str(extract_dir))

        # Verify no file was extracted outside
        assert not (tmp_path / "etc").exists()

    def test_absolute_path_zip_rejected(self, tmp_path):
        """ZIP with absolute path member is rejected."""
        zip_path = tmp_path / "abs.zip"
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("/tmp/evil.txt", "malicious content")
        zip_path.write_bytes(zip_buf.getvalue())

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with pytest.raises(ValueError, match="path traversal"):
            extract_backup(str(zip_path), str(extract_dir))


class TestFormatSize:
    def test_format_sizes(self):
        from odoodev.commands.db import _format_size

        assert "B" in _format_size(500)
        assert "KB" in _format_size(1500)
        assert "MB" in _format_size(1500000)
        assert "GB" in _format_size(1500000000)
