"""Tests for odoodev.core.database module."""

from __future__ import annotations

import os
import types
import zipfile

import pytest
from click.testing import CliRunner
from faker import Faker

from odoodev.cli import cli
from odoodev.core.database import (
    ANONYMIZE_DELETE_TABLES,
    ANONYMIZE_STATIC_QUERIES,
    ANONYMIZE_STATIC_TABLES,
    ANONYMIZE_TABLES,
    RESTORE_COMPRESSION_FACTOR,
    AnonTable,
    _build_anonymize_sql,
    _build_static_update,
    _existing_columns,
    _fetch_ids,
    _sql_literal,
    anonymize_database,
    anonymize_users,
    check_restore_space,
    cleanup_restore_temp,
    copy_filestore,
    create_backup_tar_zst,
    detect_backup_type,
    estimate_uncompressed_size,
    extract_backup,
    format_size,
    get_filestore_path,
    get_restore_temp_dir,
    move_filestore,
    neutralize_bank_sync,
    run_neutralize,
)


def _table_spec(name: str):
    """Return the AnonTable spec for a table name."""
    return next(spec for spec in ANONYMIZE_TABLES if spec.table == name)


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

    def test_extract_tar_gz_routes_to_tar_branch(self, tmp_dir):
        """.tar.gz must extract via the tar branch (dump.sql + filestore), not be
        mistreated as a plain SQL gzip — splitext yields '.gz' so this is a regression guard."""
        import tarfile

        staging = os.path.join(tmp_dir, "staging")
        os.makedirs(os.path.join(staging, "filestore"))
        with open(os.path.join(staging, "dump.sql"), "w") as f:
            f.write("SELECT 1;")
        with open(os.path.join(staging, "filestore", "blob"), "w") as f:
            f.write("data")
        archive = os.path.join(tmp_dir, "backup.tar.gz")
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(os.path.join(staging, "dump.sql"), arcname="dump.sql")
            tf.add(os.path.join(staging, "filestore"), arcname="filestore")

        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(archive, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))
        # If it had hit the gz/SQL branch, the filestore would be missing.
        assert os.path.exists(os.path.join(extract_path, "filestore", "blob"))

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


class TestExtract7z:
    @pytest.mark.parametrize("available", ["7zz", "7z", "7za"])
    def test_extract_7z_uses_available_binary(self, tmp_dir, monkeypatch, available):
        """7z extraction works with any of 7zz/7z/7za (Debian's p7zip provides 7za)."""
        archive = os.path.join(tmp_dir, "backup.7z")
        with open(archive, "w") as f:
            f.write("not-a-real-7z")  # content irrelevant — subprocess is mocked
        extract_path = os.path.join(tmp_dir, "extracted")

        calls: dict[str, list[str]] = {}

        def fake_which(name):
            return f"/usr/bin/{name}" if name == available else None

        def fake_run(cmd, *args, **kwargs):
            calls["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("odoodev.core.database.shutil.which", fake_which)
        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)

        assert extract_backup(archive, extract_path) is True
        assert calls["cmd"][0] == available

    def test_extract_7z_no_binary_returns_false(self, tmp_dir, monkeypatch):
        """When no 7z binary is installed, extraction fails gracefully (not a crash)."""
        archive = os.path.join(tmp_dir, "backup.7z")
        with open(archive, "w") as f:
            f.write("x")
        extract_path = os.path.join(tmp_dir, "extracted")
        monkeypatch.setattr("odoodev.core.database.shutil.which", lambda name: None)
        assert extract_backup(archive, extract_path) is False


class TestExtractTarZst:
    """Tests for the .tar.zst stream-backup format (container2backup v4.7.0+)."""

    @staticmethod
    def _make_tar_zst(tmp_dir: str) -> str:
        """Build a real dump.sql + filestore/ tar and compress it with zstd."""
        import shutil
        import subprocess
        import tarfile

        zstd_bin = shutil.which("zstd")
        if zstd_bin is None:
            pytest.skip("zstd binary not installed")

        staging = os.path.join(tmp_dir, "staging")
        os.makedirs(os.path.join(staging, "filestore", "ab"))
        with open(os.path.join(staging, "dump.sql"), "w") as f:
            f.write("SELECT 1;")
        with open(os.path.join(staging, "filestore", "ab", "abcdef"), "w") as f:
            f.write("blob")

        tar_path = os.path.join(tmp_dir, "backup.tar")
        with tarfile.open(tar_path, "w") as tf:
            tf.add(os.path.join(staging, "dump.sql"), arcname="dump.sql")
            tf.add(os.path.join(staging, "filestore"), arcname="filestore")

        zst_path = os.path.join(tmp_dir, "backup.tar.zst")
        subprocess.run([zstd_bin, "-q", "-f", "-o", zst_path, tar_path], check=True)
        return zst_path

    def test_extract_tar_zst_roundtrip(self, tmp_dir):
        """A real .tar.zst extracts dump.sql and the filestore tree."""
        zst_path = self._make_tar_zst(tmp_dir)
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(zst_path, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))
        assert os.path.exists(os.path.join(extract_path, "filestore", "ab", "abcdef"))

    def test_extract_tar_zst_detects_backup_structure(self, tmp_dir):
        """detect_backup_type recognizes the extracted .tar.zst layout."""
        zst_path = self._make_tar_zst(tmp_dir)
        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(zst_path, extract_path) is True
        info = detect_backup_type(extract_path)
        assert info is not None
        assert info["sql_file"].endswith("dump.sql")
        assert info["filestore"] is not None

    def test_extract_tar_zst_no_binary_returns_false(self, tmp_dir, monkeypatch):
        """When zstd is not installed, extraction fails gracefully (not a crash)."""
        archive = os.path.join(tmp_dir, "backup.tar.zst")
        with open(archive, "w") as f:
            f.write("x")
        extract_path = os.path.join(tmp_dir, "extracted")
        monkeypatch.setattr("odoodev.core.database.shutil.which", lambda name: None)
        assert extract_backup(archive, extract_path) is False


class TestCreateBackupTarZst:
    """Tests for the .tar.zst backup writer (symmetric to TestExtractTarZst)."""

    @staticmethod
    def _make_source(tmp_dir: str) -> tuple[str, str]:
        """Create a dump.sql plus a filestore directory; return their paths."""
        sql_path = os.path.join(tmp_dir, "dump.sql")
        with open(sql_path, "w") as f:
            f.write("SELECT 1;")
        fs_dir = os.path.join(tmp_dir, "filestore_src")
        os.makedirs(os.path.join(fs_dir, "ab"))
        with open(os.path.join(fs_dir, "ab", "abcdef"), "w") as f:
            f.write("blob")
        return sql_path, fs_dir

    def test_create_and_restore_roundtrip(self, tmp_dir):
        """A created .tar.zst extracts back to dump.sql + filestore tree."""
        import shutil

        if shutil.which("zstd") is None:
            pytest.skip("zstd binary not installed")

        sql_path, fs_dir = self._make_source(tmp_dir)
        output = os.path.join(tmp_dir, "backup.tar.zst")
        assert create_backup_tar_zst(sql_path, output, fs_dir) is True
        assert os.path.exists(output)

        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(output, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))
        assert os.path.exists(os.path.join(extract_path, "filestore", "ab", "abcdef"))

        info = detect_backup_type(extract_path)
        assert info is not None
        assert info["sql_file"].endswith("dump.sql")
        assert info["filestore"] is not None

    def test_create_without_filestore(self, tmp_dir):
        """A created .tar.zst without filestore still contains dump.sql."""
        import shutil

        if shutil.which("zstd") is None:
            pytest.skip("zstd binary not installed")

        sql_path, _ = self._make_source(tmp_dir)
        output = os.path.join(tmp_dir, "backup.tar.zst")
        assert create_backup_tar_zst(sql_path, output, None) is True

        extract_path = os.path.join(tmp_dir, "extracted")
        assert extract_backup(output, extract_path) is True
        assert os.path.exists(os.path.join(extract_path, "dump.sql"))

    def test_no_binary_returns_false(self, tmp_dir, monkeypatch):
        """When zstd is not installed, creation fails gracefully (not a crash)."""
        sql_path, fs_dir = self._make_source(tmp_dir)
        output = os.path.join(tmp_dir, "backup.tar.zst")
        monkeypatch.setattr("odoodev.core.database.shutil.which", lambda name: None)
        assert create_backup_tar_zst(sql_path, output, fs_dir) is False


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


class TestSqlLiteral:
    def test_none_becomes_null(self):
        assert _sql_literal(None) == "NULL"

    def test_plain_string_is_quoted(self):
        assert _sql_literal("hello") == "'hello'"

    def test_single_quote_is_escaped(self):
        assert _sql_literal("O'Brien") == "'O''Brien'"


class TestBuildAnonymizeSql:
    def test_emits_update_from_values(self):
        sql = _build_anonymize_sql(_table_spec("res_partner"), [1, 2], Faker("de_DE"))
        assert "UPDATE res_partner AS t SET" in sql
        assert "FROM (VALUES" in sql
        assert "WHERE t.id = v.id" in sql

    def test_email_forced_to_invalid_tld(self):
        """Emails must never be Faker-generated (could be deliverable)."""
        sql = _build_anonymize_sql(_table_spec("res_partner"), [42], Faker("de_DE"))
        assert "p42@example.invalid" in sql

    def test_deterministic_across_instances(self):
        """Same ids + fresh seeded Faker → identical SQL (reproducible)."""
        sql_a = _build_anonymize_sql(_table_spec("res_partner"), [1, 2, 3], Faker("de_DE"))
        sql_b = _build_anonymize_sql(_table_spec("res_partner"), [1, 2, 3], Faker("de_DE"))
        assert sql_a == sql_b

    def test_chunking_splits_statements(self):
        ids = list(range(1, 11))  # 10 ids, chunk_size 4 → 3 statements
        sql = _build_anonymize_sql(_table_spec("res_partner"), ids, Faker("de_DE"), chunk_size=4)
        assert sql.count("UPDATE res_partner AS t SET") == 3

    def test_empty_ids_yields_empty_sql(self):
        assert _build_anonymize_sql(_table_spec("res_partner"), [], Faker("de_DE")) == ""


class TestAnonymizeSpecs:
    def test_res_users_not_anonymized_by_default(self):
        """res_users must stay out of the default pass so logins keep working."""
        assert all(spec.table != "res_users" for spec in ANONYMIZE_TABLES)

    def test_hr_employee_in_default_pass(self):
        spec = _table_spec("hr_employee")
        cols = [f.column for f in spec.fields]
        assert "name" in cols and "work_email" in cols

    def test_static_queries_cover_mail_and_attachments(self):
        joined = " ".join(ANONYMIZE_STATIC_QUERIES)
        assert "mail_message" in joined
        assert "ir_attachment" in joined

    def test_res_partner_split_by_is_company(self):
        """res_partner is split into a company spec and a person spec."""
        partner_specs = [s for s in ANONYMIZE_TABLES if s.table == "res_partner"]
        assert len(partner_specs) == 2
        wheres = [s.where for s in partner_specs]
        assert any("is_company = true" in w for w in wheres)
        assert any("is_company = false" in w for w in wheres)

    def test_company_spec_has_no_job_title(self):
        """Companies get a company name but no person-only job title."""
        company_spec = next(s for s in ANONYMIZE_TABLES if s.table == "res_partner" and "true" in s.where)
        person_spec = next(s for s in ANONYMIZE_TABLES if s.table == "res_partner" and "false" in s.where)
        company_cols = [f.column for f in company_spec.fields]
        person_cols = [f.column for f in person_spec.fields]
        assert "function" not in company_cols
        assert "function" in person_cols
        assert "name" in company_cols and "name" in person_cols


def _all_known_columns() -> set[str]:
    """Every column referenced by any anonymization spec (+ id) for mocking schema."""
    cols = {"id"}
    for spec in ANONYMIZE_TABLES:
        cols |= {f.column for f in spec.fields}
    for static in ANONYMIZE_STATIC_TABLES:
        cols |= {col for col, _ in static.assignments}
    return cols


class TestAnonymizeDatabase:
    def test_runs_all_tables_and_static_queries(self, monkeypatch):
        file_sql: list[str] = []
        psql_queries: list[str] = []

        monkeypatch.setattr("odoodev.core.database._fetch_ids", lambda spec, *a, **k: [1])
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: _all_known_columns())
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file",
            lambda sql, **k: (file_sql.append(sql), (True, ""))[1],
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (psql_queries.append(query), (True, ""))[1],
        )

        assert anonymize_database("mydb") is True
        # One bundled file per per-row table.
        assert len(file_sql) == len(ANONYMIZE_TABLES)
        # Static updates (HR) + linkage deletes + whole-table wipes go through _run_psql.
        expected = len(ANONYMIZE_STATIC_TABLES) + len(ANONYMIZE_DELETE_TABLES) + len(ANONYMIZE_STATIC_QUERIES)
        assert len(psql_queries) == expected

    def test_skips_tables_without_rows(self, monkeypatch):
        file_sql: list[str] = []
        monkeypatch.setattr("odoodev.core.database._fetch_ids", lambda spec, *a, **k: [])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file",
            lambda sql, **k: (file_sql.append(sql), (True, ""))[1],
        )
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda query, **k: (True, ""))
        assert anonymize_database("mydb") is True
        assert file_sql == []  # nothing to anonymize → no file updates

    def test_returns_false_on_failure(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.database._fetch_ids", lambda spec, *a, **k: [1])
        monkeypatch.setattr("odoodev.core.database._run_psql_file", lambda sql, **k: (False, "boom"))
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda query, **k: (True, ""))
        assert anonymize_database("mydb") is False


class TestRunNeutralize:
    def test_builds_neutralize_command(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, out = run_neutralize(
            "mydb",
            venv_python="/venv/bin/python3",
            odoo_bin="/srv/odoo-bin",
            config_path="/conf/odoo_250101.conf",
            env={"PGHOST": "localhost"},
            cwd="/srv",
        )
        assert ok is True
        assert captured["cmd"] == [
            "/venv/bin/python3",
            "/srv/odoo-bin",
            "neutralize",
            "-c",
            "/conf/odoo_250101.conf",
            "-d",
            "mydb",
        ]
        assert captured["cwd"] == "/srv"

    def test_stdout_extra_arg_appended(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            "odoodev.core.database.subprocess.run",
            lambda cmd, **k: (captured.update(cmd=cmd), types.SimpleNamespace(returncode=0, stdout="", stderr=""))[1],
        )
        run_neutralize("db", "/p", "/b", "/c.conf", {}, "/cwd", extra=["--stdout"])
        assert captured["cmd"][-1] == "--stdout"

    def test_returns_false_on_error(self, monkeypatch):
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            raise sp.CalledProcessError(1, cmd, stderr="boom")

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, out = run_neutralize("db", "/p", "/b", "/c.conf", {}, "/cwd")
        assert ok is False
        assert "boom" in out


class TestResolveOdooInvocation:
    def test_returns_none_when_prereqs_missing(self, monkeypatch, tmp_path):
        from odoodev.commands.start import resolve_odoo_invocation

        cfg = types.SimpleNamespace(
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path))
        )
        # No .venv/odoo-bin/odoo_*.conf present in tmp_path → None
        assert resolve_odoo_invocation(cfg, {}) is None


class TestRestoreCliFlags:
    """The restore command runs neutralize + anonymize by default (opt-out)."""

    def _patch_flow(self, monkeypatch, tmp_path, anon_calls, neut_calls, inv=None):
        from odoodev.commands import db as db_cmd
        from odoodev.commands import start as start_cmd

        cfg = types.SimpleNamespace(
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
        )
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
        monkeypatch.setattr(db_cmd, "drop_database", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "get_restore_temp_dir", lambda b: str(tmp_path))
        monkeypatch.setattr(db_cmd, "extract_backup", lambda b, e: True)
        monkeypatch.setattr(db_cmd, "detect_backup_type", lambda e: {"sql_file": "/x", "filestore": None})
        monkeypatch.setattr(db_cmd, "create_database", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "restore_database", lambda name, sql, **k: True)
        monkeypatch.setattr(db_cmd, "deactivate_cronjobs", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "cleanup_restore_temp", lambda e: None)
        # resolve_odoo_invocation is imported inside db_restore from the start module
        monkeypatch.setattr(start_cmd, "resolve_odoo_invocation", lambda vc, ev: inv)
        monkeypatch.setattr(db_cmd, "run_neutralize", lambda name, **k: (neut_calls.append(name), (True, ""))[1])
        monkeypatch.setattr(db_cmd, "anonymize_database", lambda name, **k: (anon_calls.append(name), True)[1])
        # New post-restore steps — mocked to True so the CLI flow never touches real psql.
        monkeypatch.setattr(db_cmd, "neutralize_bank_sync", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "anonymize_users", lambda name, **k: True)
        # Disk-space check + delete-backup prompt — neutralized for deterministic flow.
        monkeypatch.setattr(db_cmd, "check_restore_space", lambda b, t, d: (True, "", 0))
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)

    def test_help_lists_neutralize_and_anonymize_flags(self):
        result = CliRunner().invoke(cli, ["db", "restore", "--help"])
        assert "--neutralize" in result.output
        assert "--no-neutralize" in result.output
        assert "--anonymize" in result.output
        # removed cloud-integrations flag must be gone
        assert "deactivate-cloud-integrations" not in result.output

    def test_anonymize_runs_by_default(self, monkeypatch, tmp_path):
        anon: list[str] = []
        neut: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, anon, neut)
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup)])
        assert result.exit_code == 0, result.output
        assert anon == ["testdb"]

    def test_no_anonymize_skips(self, monkeypatch, tmp_path):
        anon: list[str] = []
        neut: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, anon, neut)
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--no-anonymize"])
        assert result.exit_code == 0, result.output
        assert anon == []

    def test_neutralize_runs_by_default_when_env_ready(self, monkeypatch, tmp_path):
        anon: list[str] = []
        neut: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        # inv={} → env ready → run_neutralize called
        self._patch_flow(monkeypatch, tmp_path, anon, neut, inv={})
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup)])
        assert result.exit_code == 0, result.output
        assert neut == ["testdb"]

    def test_no_neutralize_skips(self, monkeypatch, tmp_path):
        anon: list[str] = []
        neut: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, anon, neut, inv={})
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--no-neutralize"])
        assert result.exit_code == 0, result.output
        assert neut == []

    def test_neutralize_graceful_skip_when_env_missing(self, monkeypatch, tmp_path):
        anon: list[str] = []
        neut: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        # inv=None → env not ready → restore still succeeds, run_neutralize not called
        self._patch_flow(monkeypatch, tmp_path, anon, neut, inv=None)
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup)])
        assert result.exit_code == 0, result.output
        assert neut == []

    def test_neutralize_command_help(self):
        result = CliRunner().invoke(cli, ["db", "neutralize", "--help"])
        assert result.exit_code == 0
        assert "--stdout" in result.output

    def test_anonymize_users_help_flag(self):
        result = CliRunner().invoke(cli, ["db", "restore", "--help"])
        assert "--anonymize-users" in result.output
        assert "--user-password" in result.output

    def test_anonymize_users_opt_in(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        anon: list[str] = []
        neut: list[str] = []
        users: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, anon, neut)
        monkeypatch.setattr(db_cmd, "anonymize_users", lambda name, **k: (users.append(name), True)[1])
        result = CliRunner().invoke(
            cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--anonymize-users"]
        )
        assert result.exit_code == 0, result.output
        assert users == ["testdb"]

    def test_anonymize_users_off_by_default(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        anon: list[str] = []
        neut: list[str] = []
        users: list[str] = []
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, anon, neut)
        monkeypatch.setattr(db_cmd, "anonymize_users", lambda name, **k: (users.append(name), True)[1])
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup)])
        assert result.exit_code == 0, result.output
        assert users == []  # res_users untouched unless explicitly requested


class TestExistingColumns:
    def test_parses_psql_output(self, monkeypatch):
        out = " column_name \n-------------\n id\n name\n work_email\n(3 rows)\n"
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (True, out))
        cols = _existing_columns("hr_employee", "db")
        assert cols == {"id", "name", "work_email"}

    def test_missing_table_returns_empty(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (False, "no such table"))
        assert _existing_columns("nope", "db") == set()


class TestBuildStaticUpdate:
    def test_filters_missing_columns(self):
        stmt = _build_static_update(
            "hr_employee",
            (("birthday", "NULL"), ("ssnid", "NULL"), ("wage", "0")),
            existing={"id", "birthday", "wage"},
        )
        assert stmt is not None
        assert "birthday = NULL" in stmt
        assert "wage = 0" in stmt
        assert "ssnid" not in stmt  # filtered out (not in schema)

    def test_returns_none_when_no_column_exists(self):
        assert _build_static_update("t", (("a", "NULL"),), existing={"id", "b"}) is None

    def test_includes_where(self):
        stmt = _build_static_update("res_users", (("password", "'x'"),), {"password"}, where="id > 1")
        assert stmt == "UPDATE res_users SET password = 'x' WHERE id > 1;"


class TestAnonymizeUsers:
    def test_builds_login_values_and_password_hash(self, monkeypatch):
        file_sql: list[str] = []
        psql: list[str] = []
        monkeypatch.setattr("odoodev.core.database._fetch_ids", lambda spec, *a, **k: [5, 7])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file",
            lambda sql, **k: (file_sql.append(sql), (True, ""))[1],
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (psql.append(q), (True, ""))[1],
        )
        assert anonymize_users("db", dev_password="ownerp") is True
        # logins forced to user{id} (admin exclusion happens at id-selection time)
        assert "user5" in file_sql[0] and "user7" in file_sql[0]
        # password set once as a pbkdf2 hash (never plaintext), admin excluded via WHERE
        assert len(psql) == 1
        assert "UPDATE res_users SET password = " in psql[0]
        assert "id > 1" in psql[0]
        assert "pbkdf2" in psql[0]
        assert "'ownerp'" not in psql[0]

    def test_pbkdf2_hash_is_odoo_compatible(self):
        from odoodev.core.database import _pbkdf2_sha512_hash

        h = _pbkdf2_sha512_hash("ownerp")
        scheme, rounds, salt, checksum = h.lstrip("$").split("$")
        assert scheme == "pbkdf2-sha512"
        assert rounds.isdigit() and int(rounds) >= 25000
        # passlib ab64 encoding: no '+', no '=' padding
        assert "+" not in h and "=" not in h
        assert len(salt) > 0 and len(checksum) > 0
        # salted: two hashes of the same password must differ
        assert h != _pbkdf2_sha512_hash("ownerp")


class TestSqlGuards:
    def test_valid_identifier_passes(self):
        from odoodev.core.database import _check_identifier

        assert _check_identifier("res_partner") == "res_partner"
        assert _check_identifier("hr_employee") == "hr_employee"

    def test_injection_in_identifier_raises(self):
        from odoodev.core.database import _check_identifier

        for bad in ("res_partner; DROP TABLE x", "a'b", "t--", "1table", ""):
            with pytest.raises(ValueError):
                _check_identifier(bad)

    def test_valid_where_fragment_passes(self):
        from odoodev.core.database import _check_where_fragment

        where = "id > 1 AND login NOT IN ('admin', '__system__')"
        assert _check_where_fragment(where) == where

    def test_where_fragment_rejects_statement_tokens(self):
        from odoodev.core.database import _check_where_fragment

        for bad in ("id > 1; DELETE FROM res_users", "id > 1 -- comment", "id > 1 /* x */"):
            with pytest.raises(ValueError):
                _check_where_fragment(bad)

    def test_fetch_ids_rejects_unsafe_table(self):
        spec = AnonTable(table="res_users; DROP TABLE x", fields=(), where="")
        with pytest.raises(ValueError):
            _fetch_ids(spec, "db")


class TestNeutralizeBankSync:
    def test_fk_safe_order_and_separate_calls(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {
                "account_journal": {"bank_statements_source", "account_online_account_id", "account_online_link_id"},
                "account_online_account": {"id"},
                "account_online_link": {"id"},
            }.get(table, set()),
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (calls.append(q), (True, ""))[1],
        )
        assert neutralize_bank_sync("db") is True
        # three separate statements (own transactions), correct FK order
        assert len(calls) == 3
        assert "bank_statements_source = 'undefined'" in calls[0]
        assert calls[1] == "DELETE FROM account_online_account;"
        assert calls[2] == "DELETE FROM account_online_link;"

    def test_noop_when_tables_absent(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: set())
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (calls.append(q), (True, ""))[1],
        )
        assert neutralize_bank_sync("db") is True
        assert calls == []  # accounting/bank-sync modules not installed → nothing to do


class TestConnectionHelpers:
    def test_connection_count_parses_number(self, monkeypatch):
        psql_out = " count \n-------\n     3\n(1 row)\n"
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (True, psql_out))
        from odoodev.core.database import get_active_connection_count

        assert get_active_connection_count("mydb") == 3

    def test_connection_count_error_returns_minus_one(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (False, "boom"))
        from odoodev.core.database import get_active_connection_count

        assert get_active_connection_count("mydb") == -1

    def test_terminate_connections_query(self, monkeypatch):
        queries: list[str] = []
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (queries.append(q), (True, ""))[1])
        from odoodev.core.database import terminate_connections

        assert terminate_connections("mydb") is True
        assert "pg_terminate_backend" in queries[0]
        assert "mydb" in queries[0]

    def test_unsafe_db_name_raises(self):
        from odoodev.core.database import get_active_connection_count

        with pytest.raises(ValueError):
            get_active_connection_count("bad;name")


class TestCopyRenameDatabase:
    def test_copy_database_uses_template(self, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        from odoodev.core.database import copy_database

        assert copy_database("srcdb", "dstdb") is True
        assert calls[0][0] == "createdb"
        assert "-T" in calls[0]
        assert calls[0][calls[0].index("-T") + 1] == "srcdb"
        assert calls[0][-1] == "dstdb"

    def test_rename_database_alter_statement(self, monkeypatch):
        queries: list[str] = []
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (queries.append(q), (True, ""))[1])
        from odoodev.core.database import rename_database

        assert rename_database("olddb", "newdb") is True
        assert queries[0] == "ALTER DATABASE olddb RENAME TO newdb;"

    def test_copy_rejects_unsafe_names(self):
        from odoodev.core.database import copy_database, rename_database

        with pytest.raises(ValueError):
            copy_database("ok", "bad name")
        with pytest.raises(ValueError):
            rename_database("bad;", "ok")


class TestDbCopyRenameCommands:
    def _patch_common(self, monkeypatch, connections=0):
        import odoodev.commands.db as db_cmd

        monkeypatch.setattr(
            db_cmd,
            "get_version",
            lambda v: types.SimpleNamespace(
                paths=types.SimpleNamespace(native_dir="/nonexistent"),
                ports=types.SimpleNamespace(db=18432),
            ),
        )
        monkeypatch.setattr(db_cmd, "database_exists", lambda name, **k: name == "srcdb")
        monkeypatch.setattr(db_cmd, "get_active_connection_count", lambda name, **k: connections)
        monkeypatch.setattr(db_cmd, "get_filestore_path", lambda v, db_name: f"/nonexistent/fs/{db_name}")
        return db_cmd

    def test_copy_happy_path(self, monkeypatch):
        db_cmd = self._patch_common(monkeypatch)
        copied: list[tuple[str, str]] = []
        monkeypatch.setattr(db_cmd, "copy_database", lambda s, d, **k: (copied.append((s, d)), True)[1])
        result = CliRunner().invoke(cli, ["db", "copy", "18", "-s", "srcdb", "-d", "newdb", "-y"])
        assert result.exit_code == 0
        assert copied == [("srcdb", "newdb")]

    def test_copy_dst_exists_fails(self, monkeypatch):
        db_cmd = self._patch_common(monkeypatch)
        monkeypatch.setattr(db_cmd, "database_exists", lambda name, **k: True)
        result = CliRunner().invoke(cli, ["db", "copy", "18", "-s", "srcdb", "-d", "srcdb2", "-y"])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_copy_src_missing_fails(self, monkeypatch):
        db_cmd = self._patch_common(monkeypatch)
        monkeypatch.setattr(db_cmd, "database_exists", lambda name, **k: False)
        result = CliRunner().invoke(cli, ["db", "copy", "18", "-s", "ghost", "-d", "newdb", "-y"])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_copy_invalid_dst_name(self, monkeypatch):
        self._patch_common(monkeypatch)
        result = CliRunner().invoke(cli, ["db", "copy", "18", "-s", "srcdb", "-d", "1bad", "-y"])
        assert result.exit_code == 1
        assert "Invalid database name" in result.output

    def test_copy_active_connections_abort_without_flag(self, monkeypatch):
        db_cmd = self._patch_common(monkeypatch, connections=2)
        monkeypatch.setattr(db_cmd, "copy_database", lambda s, d, **k: True)
        result = CliRunner().invoke(cli, ["db", "copy", "18", "-s", "srcdb", "-d", "newdb", "-y"])
        assert result.exit_code == 1
        assert "active connection" in result.output

    def test_copy_terminate_connections_flag(self, monkeypatch):
        db_cmd = self._patch_common(monkeypatch, connections=2)
        terminated: list[str] = []
        monkeypatch.setattr(db_cmd, "terminate_connections", lambda name, **k: (terminated.append(name), True)[1])
        monkeypatch.setattr(db_cmd, "copy_database", lambda s, d, **k: True)
        result = CliRunner().invoke(
            cli, ["db", "copy", "18", "-s", "srcdb", "-d", "newdb", "-y", "--terminate-connections"]
        )
        assert result.exit_code == 0
        assert terminated == ["srcdb"]

    def test_rename_happy_path_moves_filestore(self, monkeypatch, tmp_path):
        db_cmd = self._patch_common(monkeypatch)
        fs_root = tmp_path / "fs"
        (fs_root / "srcdb").mkdir(parents=True)
        monkeypatch.setattr(db_cmd, "get_filestore_path", lambda v, db_name: str(fs_root / db_name))
        renamed: list[tuple[str, str]] = []
        monkeypatch.setattr(db_cmd, "rename_database", lambda s, d, **k: (renamed.append((s, d)), True)[1])
        result = CliRunner().invoke(cli, ["db", "rename", "18", "-s", "srcdb", "-d", "newdb", "-y"])
        assert result.exit_code == 0
        assert renamed == [("srcdb", "newdb")]
        assert (fs_root / "newdb").is_dir()
        assert not (fs_root / "srcdb").exists()

    def test_rename_failure_exit_1(self, monkeypatch):
        db_cmd = self._patch_common(monkeypatch)
        monkeypatch.setattr(db_cmd, "rename_database", lambda s, d, **k: False)
        result = CliRunner().invoke(cli, ["db", "rename", "18", "-s", "srcdb", "-d", "newdb", "-y"])
        assert result.exit_code == 1


class TestEstimateUncompressedSize:
    def test_zip_is_exact(self, tmp_path):
        zip_path = tmp_path / "b.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("dump.sql", "X" * 1000)
            zf.writestr("filestore/a.txt", "Y" * 500)
        assert estimate_uncompressed_size(str(zip_path)) == 1500

    def test_sql_is_file_size(self, tmp_path):
        sql = tmp_path / "dump.sql"
        sql.write_bytes(b"Z" * 2048)
        assert estimate_uncompressed_size(str(sql)) == 2048

    def test_compressed_uses_factor(self, tmp_path):
        backup = tmp_path / "b.tar.zst"
        backup.write_bytes(b"Q" * 100)
        assert estimate_uncompressed_size(str(backup)) == 100 * RESTORE_COMPRESSION_FACTOR

    def test_missing_file_returns_zero(self, tmp_path):
        assert estimate_uncompressed_size(str(tmp_path / "nope.zip")) == 0


class TestCheckRestoreSpace:
    def test_enough_space(self, monkeypatch, tmp_path):
        backup = tmp_path / "dump.sql"
        backup.write_bytes(b"A" * 1000)
        monkeypatch.setattr(
            "odoodev.core.database.shutil.disk_usage",
            lambda p: types.SimpleNamespace(total=0, used=0, free=10**9),
        )
        enough, msg, est = check_restore_space(str(backup), str(tmp_path), str(tmp_path / "fs"))
        assert enough is True
        assert msg == ""
        assert est == 1000

    def test_low_space_returns_message(self, monkeypatch, tmp_path):
        backup = tmp_path / "dump.sql"
        backup.write_bytes(b"A" * 10_000)
        monkeypatch.setattr(
            "odoodev.core.database.shutil.disk_usage",
            lambda p: types.SimpleNamespace(total=0, used=0, free=5_000),
        )
        enough, msg, est = check_restore_space(str(backup), str(tmp_path), str(tmp_path / "fs"))
        assert enough is False
        assert "Low disk space" in msg
        assert est == 10_000

    def test_disk_usage_error_does_not_block(self, monkeypatch, tmp_path):
        backup = tmp_path / "dump.sql"
        backup.write_bytes(b"A" * 10)

        def _raise(_p):
            raise OSError("boom")

        monkeypatch.setattr("odoodev.core.database.shutil.disk_usage", _raise)
        enough, _msg, _est = check_restore_space(str(backup), str(tmp_path), str(tmp_path / "fs"))
        assert enough is True


class TestMoveFilestore:
    def test_moves_contents_and_skips_dump(self, tmp_path):
        src = tmp_path / "src"
        (src / "sub").mkdir(parents=True)
        (src / "dump.sql").write_text("SELECT 1;")
        (src / "a.txt").write_text("a")
        (src / "sub" / "b.txt").write_text("b")
        dest = tmp_path / "dest"

        assert move_filestore(str(src), str(dest)) is True
        assert (dest / "a.txt").read_text() == "a"
        assert (dest / "sub" / "b.txt").read_text() == "b"
        # dump.sql is not part of the filestore
        assert not (dest / "dump.sql").exists()
        # source contents (except dump.sql) are gone — no double storage
        assert not (src / "a.txt").exists()
        assert not (src / "sub").exists()

    def test_missing_source_returns_false(self, tmp_path):
        assert move_filestore(str(tmp_path / "nope"), str(tmp_path / "dest")) is False

    def test_overwrites_existing_dest_entry(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("new")
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "a.txt").write_text("old")
        assert move_filestore(str(src), str(dest)) is True
        assert (dest / "a.txt").read_text() == "new"


class TestRestoreBackupHandling:
    """Disk-space check, move-vs-copy, and delete-backup behavior of `db restore`."""

    def _patch(self, monkeypatch, tmp_path, *, space_ok=True, fs_spy=None):
        from odoodev.commands import db as db_cmd
        from odoodev.commands import start as start_cmd

        cfg = types.SimpleNamespace(
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
        )
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
        monkeypatch.setattr(db_cmd, "drop_database", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "get_restore_temp_dir", lambda b: str(tmp_path / "extract"))
        monkeypatch.setattr(db_cmd, "extract_backup", lambda b, e: True)
        monkeypatch.setattr(db_cmd, "get_filestore_path", lambda v, n: str(tmp_path / "fs" / n))
        monkeypatch.setattr(
            db_cmd, "detect_backup_type", lambda e: {"sql_file": "/x", "filestore": str(tmp_path / "extract" / "fs")}
        )
        monkeypatch.setattr(db_cmd, "create_database", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "restore_database", lambda name, sql, **k: True)
        monkeypatch.setattr(db_cmd, "deactivate_cronjobs", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "cleanup_restore_temp", lambda e: None)
        monkeypatch.setattr(start_cmd, "resolve_odoo_invocation", lambda vc, ev: None)
        monkeypatch.setattr(db_cmd, "neutralize_bank_sync", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "anonymize_database", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "anonymize_users", lambda name, **k: True)
        monkeypatch.setattr(db_cmd, "check_restore_space", lambda b, t, d: (space_ok, "" if space_ok else "low", 0))
        # filestore source exists so the move/copy branch is exercised
        (tmp_path / "extract" / "fs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "extract" / "fs" / "x.txt").write_text("x")
        if fs_spy is not None:
            monkeypatch.setattr(db_cmd, "move_filestore", lambda s, d: (fs_spy.append("move"), True)[1])
            monkeypatch.setattr(db_cmd, "copy_filestore", lambda s, d: (fs_spy.append("copy"), True)[1])
        return db_cmd

    def test_delete_backup_flag_removes_file(self, monkeypatch, tmp_path):
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--delete-backup"])
        assert result.exit_code == 0, result.output
        assert not backup.exists()

    def test_keep_backup_flag_keeps_file_without_prompt(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch(monkeypatch, tmp_path)
        prompts: list[str] = []
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: (prompts.append("asked"), False)[1])
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--keep-backup"])
        assert result.exit_code == 0, result.output
        assert backup.exists()
        assert prompts == []

    def test_default_asks_to_delete_backup(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch(monkeypatch, tmp_path)
        prompts: list[str] = []
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: (prompts.append("asked"), False)[1])
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup)])
        assert result.exit_code == 0, result.output
        assert backup.exists()
        assert prompts == ["asked"]

    def test_low_space_aborts_when_declined(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch(monkeypatch, tmp_path, space_ok=False)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup)])
        assert result.exit_code == 0
        assert "Aborted" in result.output

    def test_no_check_space_skips_check(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        backup = tmp_path / "b.zip"
        backup.write_text("x")
        called: list[str] = []
        self._patch(monkeypatch, tmp_path, space_ok=False)
        monkeypatch.setattr(db_cmd, "check_restore_space", lambda b, t, d: (called.append("x"), (False, "low", 0))[1])
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(
            cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--no-check-space", "--keep-backup"]
        )
        assert result.exit_code == 0, result.output
        assert called == []

    def test_default_moves_filestore(self, monkeypatch, tmp_path):
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        spy: list[str] = []
        self._patch(monkeypatch, tmp_path, fs_spy=spy)
        result = CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--keep-backup"])
        assert result.exit_code == 0, result.output
        assert spy == ["move"]

    def test_keep_temp_copies_filestore(self, monkeypatch, tmp_path):
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        spy: list[str] = []
        self._patch(monkeypatch, tmp_path, fs_spy=spy)
        result = CliRunner().invoke(
            cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), "--keep-temp", "--keep-backup"]
        )
        assert result.exit_code == 0, result.output
        assert spy == ["copy"]
