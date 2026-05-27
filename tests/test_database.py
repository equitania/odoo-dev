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
    ANONYMIZE_STATIC_QUERIES,
    ANONYMIZE_TABLES,
    _build_anonymize_sql,
    _sql_literal,
    anonymize_database,
    cleanup_restore_temp,
    copy_filestore,
    detect_backup_type,
    extract_backup,
    format_size,
    get_filestore_path,
    get_restore_temp_dir,
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
    def test_res_users_excludes_system_accounts(self):
        spec = _table_spec("res_users")
        assert "id > 1" in spec.where
        assert "admin" in spec.where

    def test_res_users_login_and_password(self):
        spec = _table_spec("res_users")
        sql = _build_anonymize_sql(spec, [5], Faker("de_DE"))
        assert "user5" in sql  # login forced, not Faker
        assert "NULL" in sql  # password cleared

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


class TestAnonymizeDatabase:
    def test_runs_all_tables_and_static_queries(self, monkeypatch):
        file_sql: list[str] = []
        static_queries: list[str] = []

        monkeypatch.setattr("odoodev.core.database._fetch_ids", lambda spec, *a, **k: [1])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file",
            lambda sql, **k: (file_sql.append(sql), (True, ""))[1],
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (static_queries.append(query), (True, ""))[1],
        )

        assert anonymize_database("mydb") is True
        assert len(file_sql) == len(ANONYMIZE_TABLES)
        assert len(static_queries) == len(ANONYMIZE_STATIC_QUERIES)

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
