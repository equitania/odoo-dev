"""Tests for odoodev db backup command and core backup functions."""

import zipfile

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.database import backup_database_sql, create_backup_zip


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
        """Test that pg_dump is called with correct arguments."""
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
        assert "pg_dump" in calls[0]
        assert "testdb" in calls[0]
        assert output_path in calls[0]


class TestFormatSize:
    def test_format_sizes(self):
        from odoodev.commands.db import _format_size

        assert "B" in _format_size(500)
        assert "KB" in _format_size(1500)
        assert "MB" in _format_size(1500000)
        assert "GB" in _format_size(1500000000)
