"""Tests for odoodev.core.database module."""

from __future__ import annotations

import os
import re
import types
import zipfile

import pytest
from click.testing import CliRunner
from faker import Faker

from odoodev.cli import cli
from odoodev.core.database import (
    ANONYMIZE_STATIC_TABLES,
    ANONYMIZE_TABLES,
    PURGE_TABLES,
    RESTORE_COMPRESSION_FACTOR,
    WIPE_ATTACHMENT_DELETE_SQL,
    WIPE_DELETE_TABLES,
    WIPE_ORPHAN_REPAIR_SQL,
    AnonTable,
    _build_anonymize_sql,
    _build_recompute_script,
    _build_static_update,
    _existing_columns,
    _fetch_ids,
    _null_repair_targets,
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
    purge_transactional_data,
    resolve_purge_tables,
    run_neutralize,
    run_recompute,
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

    def test_wipe_targets_cover_mail_and_attachments(self):
        assert "mail_message" in WIPE_DELETE_TABLES
        assert "ir_attachment" in WIPE_ATTACHMENT_DELETE_SQL

    def test_mail_message_is_deleted_after_its_children(self):
        """Child-before-parent order keeps the wipe working under NO ACTION FKs."""
        order = list(WIPE_DELETE_TABLES)
        assert order.index("mail_tracking_value") < order.index("mail_message")
        assert order.index("mail_notification") < order.index("mail_message")
        assert order.index("mail_followers_mail_message_subtype_rel") < order.index("mail_followers")

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

    def test_person_spec_anonymizes_eq_firstname(self):
        """Equitania custom first-name field is anonymized on persons (v0.44.0)."""
        from odoodev.core.database import RECOMPUTE_TRIGGERS

        person_spec = next(s for s in ANONYMIZE_TABLES if s.table == "res_partner" and "false" in s.where)
        assert "eq_firstname" in [f.column for f in person_spec.fields]
        # complete_name depends on eq_firstname → it must trigger a recompute too.
        assert "eq_firstname" in RECOMPUTE_TRIGGERS["res.partner"]

    def test_anonymizes_eq_partner_text_fields(self):
        """Equitania name-line / district text fields are blanked on all partners (v0.44.1)."""
        for where_key in ("true", "false"):
            spec = next(s for s in ANONYMIZE_TABLES if s.table == "res_partner" and where_key in s.where)
            cols = [f.column for f in spec.fields]
            assert {"eq_name2", "eq_name3", "eq_citypart"} <= set(cols)

    def test_eq_birthday_wiped_via_static(self):
        """Equitania date-of-birth is nulled via a res_partner static update (v0.44.1)."""
        partner_static = next((s for s in ANONYMIZE_STATIC_TABLES if s.table == "res_partner"), None)
        assert partner_static is not None
        assert ("eq_birthday", "NULL") in partner_static.assignments

    def test_res_partner_specs_exclude_user_partners(self):
        """Partners linked to a res_users row keep their name/contact so internal
        users stay recognizable while testing (v0.47.0). res_users itself is not
        anonymized by default, so its partner must not be either."""
        partner_specs = [s for s in ANONYMIZE_TABLES if s.table == "res_partner"]
        for spec in partner_specs:
            assert "partner_id FROM res_users" in spec.where

    def test_person_spec_parenthesizes_is_company_or(self):
        """The is_company OR must be grouped so the user-exclusion AND binds to the
        whole predicate (operator precedence), not just the IS NULL branch."""
        person_spec = next(s for s in ANONYMIZE_TABLES if s.table == "res_partner" and "false" in s.where)
        assert "(is_company = false OR is_company IS NULL)" in person_spec.where

    def test_static_res_partner_excludes_user_partners(self):
        """The static res_partner pass (eq_birthday NULL) also skips user partners."""
        partner_static = next(s for s in ANONYMIZE_STATIC_TABLES if s.table == "res_partner")
        assert "partner_id FROM res_users" in partner_static.where

    def test_fetch_ids_query_carries_user_exclusion(self, monkeypatch):
        """The exclusion actually reaches the emitted SELECT for both partner specs."""
        from odoodev.core import database as d

        captured: dict[str, str] = {}
        monkeypatch.setattr(d, "_run_psql", lambda q, **k: (captured.__setitem__("q", q), (True, ""))[1])
        for spec in [s for s in ANONYMIZE_TABLES if s.table == "res_partner"]:
            d._fetch_ids(spec, "db")
            assert "NOT IN (SELECT partner_id FROM res_users" in captured["q"]

    def test_user_exclusion_passes_where_guard(self):
        """The subquery must survive the WHERE-fragment safety guard."""
        from odoodev.core.database import _NON_USER_PARTNER_WHERE, _check_where_fragment

        assert _check_where_fragment(_NON_USER_PARTNER_WHERE) == _NON_USER_PARTNER_WHERE

    def test_anonymize_keep_also_excludes_company_partners(self):
        """v0.48.0: the own company's partner is kept legible too (not just users)."""
        from odoodev.core.database import _NON_USER_PARTNER_WHERE

        assert "partner_id FROM res_users" in _NON_USER_PARTNER_WHERE
        assert "partner_id FROM res_company" in _NON_USER_PARTNER_WHERE


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
        # Static updates (HR) go through _run_psql — deletes/wipes moved to wipe_database (v0.43.0).
        assert len(psql_queries) == len(ANONYMIZE_STATIC_TABLES)
        joined = " ".join(psql_queries)
        assert "DELETE FROM" not in joined
        assert "mail_message" not in joined

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


class TestWipeDatabase:
    """Content deletion split out of anonymize_database (v0.43.0).

    Since v0.62.0 ``--wipe`` really DELETEs chatter rows and attachments instead
    of only blanking mail_message bodies (which left tracking values, followers,
    activities and every attachment file in place).
    """

    def _capture(self, monkeypatch, ok=True):
        psql_queries: list[str] = []
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: {"id"})
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (psql_queries.append(query), (ok, ""))[1],
        )
        return psql_queries

    def test_deletes_chatter_rows_instead_of_blanking_them(self, monkeypatch):
        """Regression: blanking mail_message.body left the whole chatter visible."""
        from odoodev.core.database import wipe_database

        psql_queries = self._capture(monkeypatch)
        assert wipe_database("mydb") is True
        joined = " ".join(psql_queries)

        # The chatter is emptied, not masked.
        assert "DELETE FROM mail_message" in joined
        assert "DELETE FROM mail_tracking_value" in joined
        assert "DELETE FROM mail_followers" in joined
        assert "DELETE FROM mail_activity" in joined
        # No masking UPDATE survives — that was the bug.
        assert "[anonymized]" not in joined
        assert "UPDATE mail_message" not in joined

    def test_deletes_attachment_rows_not_just_the_search_index(self, monkeypatch):
        """Regression: only index_content was nulled, so invoice PDFs stayed."""
        from odoodev.core.database import wipe_database

        psql_queries = self._capture(monkeypatch)
        assert wipe_database("mydb") is True
        joined = " ".join(psql_queries)

        assert "DELETE FROM ir_attachment" in joined
        assert "UPDATE ir_attachment" not in joined

    def test_attachment_delete_keeps_assets_and_binary_field_storage(self, monkeypatch):
        """Compiled assets and Binary/Image field storage must survive the wipe."""
        from odoodev.core.database import wipe_database

        psql_queries = self._capture(monkeypatch)
        wipe_database("mydb")
        stmt = next(q for q in psql_queries if q.startswith("DELETE FROM ir_attachment"))

        # res_field IS NOT NULL == product images / avatars stored as attachments.
        assert "res_field IS NULL" in stmt
        assert "ir.ui.view" in stmt

    def test_skips_missing_tables(self, monkeypatch):
        from odoodev.core.database import wipe_database

        psql_queries: list[str] = []
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: set())
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (psql_queries.append(query), (True, ""))[1],
        )
        assert wipe_database("mydb") is True
        assert psql_queries == []

    def test_returns_false_on_failure(self, monkeypatch):
        from odoodev.core.database import wipe_database

        psql_queries = self._capture(monkeypatch, ok=False)
        assert wipe_database("mydb") is False
        assert psql_queries  # it did try

    def test_runs_filestore_gc_when_path_given(self, monkeypatch, tmp_path):
        from odoodev.core.database import wipe_database

        self._capture(monkeypatch)
        seen: dict = {}
        monkeypatch.setattr(
            "odoodev.core.database.gc_filestore",
            lambda db, path, **k: (seen.update(db=db, path=path), (True, 3))[1],
        )
        fs = tmp_path / "mydb"
        fs.mkdir()
        assert wipe_database("mydb", filestore_path=str(fs)) is True
        assert seen == {"db": "mydb", "path": str(fs)}

    def test_skips_filestore_gc_without_path(self, monkeypatch):
        from odoodev.core.database import wipe_database

        self._capture(monkeypatch)
        called: list = []
        monkeypatch.setattr(
            "odoodev.core.database.gc_filestore",
            lambda db, path, **k: (called.append(path), (True, 0))[1],
        )
        assert wipe_database("mydb") is True
        assert called == []


# Theme customization written by web_editor.assets: an ir_asset record with
# directive=replace pointing at an ir_attachment whose url is exactly this path.
CUSTOM_SCSS_PATH = "/_custom/web.assets_frontend/website/static/src/scss/options/user_values.scss"


class TestWipeKeepsAssetSources:
    """Regression for the v0.62.0 wipe that broke SCSS compilation (v0.62.1).

    The attachment DELETE removed the asset SOURCES (custom theme SCSS with
    ``res_model IS NULL``, ``web.asset_styles_company_report``) and left their
    XML IDs dangling, so ``web.assets_frontend`` no longer compiled and Odoo
    showed a permanent "style error" banner in the backend.

    The statements are executed against SQLite rather than asserted as strings:
    the guards are only worth anything if the right rows actually survive.
    """

    def _db(self):
        import sqlite3

        con = sqlite3.connect(":memory:")
        con.executescript(
            "CREATE TABLE ir_attachment (id INTEGER PRIMARY KEY, name TEXT, url TEXT,"
            " res_model TEXT, res_field TEXT, store_fname TEXT);"
            "CREATE TABLE ir_model_data (id INTEGER PRIMARY KEY, module TEXT, name TEXT,"
            " model TEXT, res_id INTEGER);"
            "CREATE TABLE ir_asset (id INTEGER PRIMARY KEY, bundle TEXT, path TEXT);"
        )
        con.executemany(
            "INSERT INTO ir_attachment VALUES (?, ?, ?, ?, ?, ?)",
            [
                # Module data: company report styles, listed in web's manifest.
                (12, "res.company.scss", "web/static/asset_styles_company_report.scss", None, None, None),
                # Theme customization: SCSS source referenced by an ir_asset replace.
                (20, "user_values.scss", CUSTOM_SCSS_PATH, None, None, "ab/scss"),
                # Website snippet default image — reached only via its XML ID.
                (30, "s_banner_default_image", None, "website", None, "cd/img"),
                # Real user content: invoice PDF and a detached chatter upload.
                (40, "INV-2024-0001.pdf", None, "account.move", None, "ef/pdf"),
                (41, "notes.txt", None, None, None, "ef/txt"),
                # Binary field storage and a compiled bundle.
                (50, "product image", None, "product.template", "image_1920", "gh/img"),
                (60, "web.assets_frontend.min.css", "/web/assets/1/x.css", "ir.ui.view", None, "ij/css"),
            ],
        )
        con.executemany(
            "INSERT INTO ir_model_data VALUES (?, ?, ?, ?, ?)",
            [
                (1, "web", "asset_styles_company_report", "ir.attachment", 12),
                (2, "website", "s_banner_default_image", "ir.attachment", 30),
                # Left behind by a v0.62.0 wipe: points at a deleted attachment.
                (3, "website", "s_cover_default_image", "ir.attachment", 999),
            ],
        )
        con.executemany(
            "INSERT INTO ir_asset VALUES (?, ?, ?)",
            [
                (1, "web.assets_frontend", CUSTOM_SCSS_PATH),
                (2, "web.assets_frontend", "/_custom/web.assets_frontend/website/static/src/scss/gone.scss"),
            ],
        )
        return con

    def _wipe(self, con):
        con.execute(WIPE_ATTACHMENT_DELETE_SQL)
        for _table, statement in WIPE_ORPHAN_REPAIR_SQL:
            con.execute(statement)
        return con

    def _ids(self, con, table="ir_attachment"):
        return {row[0] for row in con.execute(f"SELECT id FROM {table}")}  # noqa: S608 — literal table names

    def test_asset_sources_survive_the_wipe(self):
        """Deleting these stopped web.assets_frontend from compiling."""
        con = self._wipe(self._db())
        assert 12 in self._ids(con)  # web/static/asset_styles_company_report.scss
        assert 20 in self._ids(con)  # /_custom/.../user_values.scss

    def test_attachments_with_an_xml_id_survive_the_wipe(self):
        """A row referenced by ir_model_data is module data, not user content."""
        con = self._wipe(self._db())
        assert 30 in self._ids(con)

    def test_user_content_is_still_deleted(self):
        """The guards must not turn the wipe into a no-op."""
        con = self._wipe(self._db())
        assert 40 not in self._ids(con)  # invoice PDF
        assert 41 not in self._ids(con)  # res_model IS NULL chatter upload

    def test_binary_fields_and_bundles_still_survive(self):
        con = self._wipe(self._db())
        assert {50, 60} <= self._ids(con)

    def test_no_xml_id_points_at_a_deleted_attachment(self):
        """Acceptance criterion: zero orphaned ir_model_data rows after a wipe."""
        con = self._wipe(self._db())
        orphans = con.execute(
            "SELECT count(*) FROM ir_model_data d LEFT JOIN ir_attachment a ON a.id = d.res_id"
            " WHERE d.model = 'ir.attachment' AND a.id IS NULL"
        ).fetchone()[0]
        assert orphans == 0

    def test_env_ref_target_still_resolves(self):
        """env.ref('web.asset_styles_company_report') must not hit a dead res_id."""
        con = self._wipe(self._db())
        row = con.execute(
            "SELECT a.id FROM ir_model_data d JOIN ir_attachment a ON a.id = d.res_id"
            " WHERE d.module = 'web' AND d.name = 'asset_styles_company_report'"
        ).fetchone()
        assert row == (12,)

    def test_custom_assets_without_a_source_are_removed(self):
        """A /_custom/ ir_asset without its SCSS attachment breaks the bundle."""
        con = self._wipe(self._db())
        assert self._ids(con, "ir_asset") == {1}

    def test_repair_runs_after_the_attachment_delete(self, monkeypatch):
        """Order matters: repairing first would leave the new orphans behind."""
        from odoodev.core.database import wipe_database

        queries: list[str] = []
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: {"id"})
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (queries.append(query), (True, ""))[1],
        )
        wipe_database("mydb")

        attachments = next(i for i, q in enumerate(queries) if q.startswith("DELETE FROM ir_attachment"))
        model_data = next(i for i, q in enumerate(queries) if q.startswith("DELETE FROM ir_model_data"))
        assets = next(i for i, q in enumerate(queries) if q.startswith("DELETE FROM ir_asset"))
        assert attachments < model_data < assets


class TestGcFilestore:
    """Orphaned filestore files are removed after the attachment DELETE."""

    def _make_filestore(self, tmp_path, names):
        root = tmp_path / "v16_lager_a"
        for name in names:
            f = root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("payload")
        return root

    def test_removes_unreferenced_files(self, monkeypatch, tmp_path):
        from odoodev.core.database import gc_filestore

        root = self._make_filestore(tmp_path, ["ab/keepme", "cd/orphan1", "ef/orphan2"])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (True, "store_fname\n-----------\nab/keepme\n(1 row)\n"),
        )
        ok, deleted = gc_filestore("v16_lager_a", str(root))
        assert ok is True
        assert deleted == 2
        assert (root / "ab/keepme").exists()
        assert not (root / "cd/orphan1").exists()
        assert not (root / "ef/orphan2").exists()

    def test_keeps_everything_when_all_referenced(self, monkeypatch, tmp_path):
        from odoodev.core.database import gc_filestore

        root = self._make_filestore(tmp_path, ["ab/one", "cd/two"])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (True, "store_fname\n-----------\nab/one\ncd/two\n(2 rows)\n"),
        )
        ok, deleted = gc_filestore("v16_lager_a", str(root))
        assert (ok, deleted) == (True, 0)
        assert (root / "ab/one").exists()
        assert (root / "cd/two").exists()

    def test_aborts_when_query_fails_so_nothing_is_deleted(self, monkeypatch, tmp_path):
        """A failed query must never be read as 'no attachment references'."""
        from odoodev.core.database import gc_filestore

        root = self._make_filestore(tmp_path, ["ab/one"])
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda query, **k: (False, "boom"))
        ok, deleted = gc_filestore("v16_lager_a", str(root))
        assert (ok, deleted) == (False, 0)
        assert (root / "ab/one").exists()

    def test_refuses_path_not_matching_the_database(self, monkeypatch, tmp_path):
        """Safety guard: only a directory named after the DB may be garbage-collected."""
        from odoodev.core.database import gc_filestore

        root = self._make_filestore(tmp_path, ["ab/one"])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (True, "store_fname\n-----------\n(0 rows)\n"),
        )
        ok, deleted = gc_filestore("some_other_db", str(root))
        assert (ok, deleted) == (False, 0)
        assert (root / "ab/one").exists()

    def test_missing_filestore_is_a_no_op(self, tmp_path):
        from odoodev.core.database import gc_filestore

        ok, deleted = gc_filestore("v16_lager_a", str(tmp_path / "v16_lager_a"))
        assert (ok, deleted) == (True, 0)


class TestPurgeTransactionalData:
    """Transactional-data purge (v0.44.0) — TRUNCATE CASCADE with FK safety check."""

    def _all_purge_tables(self) -> list[str]:
        return [t for group in PURGE_TABLES.values() for t in group]

    def _patch(self, monkeypatch, script_sink, *, closure_extra=None, superuser=True, repairs=None, run_ok=True):
        """Patch the purge collaborators. `script_sink` collects the DELETE script."""
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: {"id"})
        monkeypatch.setattr(
            "odoodev.core.database._cascade_closure",
            lambda tables, *a, **k: set(tables) | set(closure_extra or ()),
        )
        monkeypatch.setattr("odoodev.core.database._is_superuser", lambda *a, **k: superuser)
        monkeypatch.setattr("odoodev.core.database._null_repair_targets", lambda closure, *a, **k: repairs or [])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file",
            lambda sql, **k: (script_sink.append(sql), (run_ok, "" if run_ok else "boom"))[1],
        )

    def test_deletes_closure_under_replica_role(self, monkeypatch):
        scripts: list[str] = []
        self._patch(monkeypatch, scripts, repairs=[("res_company", "account_opening_move_id")])
        ok, msg = purge_transactional_data("mydb")
        assert ok is True
        assert len(scripts) == 1
        sql = scripts[0]
        # Single transaction with FK enforcement off, no TRUNCATE (cannot be used here).
        assert "BEGIN;" in sql and "COMMIT;" in sql
        assert "SET LOCAL session_replication_role = replica;" in sql
        assert "TRUNCATE" not in sql
        for table in self._all_purge_tables():
            assert f'DELETE FROM "{table}";' in sql  # noqa: S608 — table names from a trusted constant
        # SET-NULL back-reference from a kept table is repaired.
        assert 'UPDATE "res_company" SET "account_opening_move_id" = NULL' in sql

    def test_skips_missing_tables(self, monkeypatch):
        scripts: list[str] = []
        present = {"stock_move", "account_move", "sale_order"}
        # Closure == the present roots only (mock returns the filtered set it was given).
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"id"} if table in present else set(),
        )
        monkeypatch.setattr("odoodev.core.database._cascade_closure", lambda tables, *a, **k: set(tables))
        monkeypatch.setattr("odoodev.core.database._is_superuser", lambda *a, **k: True)
        monkeypatch.setattr("odoodev.core.database._null_repair_targets", lambda closure, *a, **k: [])
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file",
            lambda sql, **k: (scripts.append(sql), (True, ""))[1],
        )
        ok, _ = purge_transactional_data("mydb")
        assert ok is True
        sql = scripts[0]
        assert 'DELETE FROM "stock_move";' in sql and 'DELETE FROM "account_move";' in sql
        assert "mrp_production" not in sql  # not present → skipped

    def test_no_tables_is_noop(self, monkeypatch):
        called: list = []
        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: set())
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_file", lambda sql, **k: (called.append(sql), (True, ""))[1]
        )
        ok, msg = purge_transactional_data("mydb")
        assert ok is True
        assert called == []  # nothing deleted
        assert "No transactional tables" in msg

    def test_aborts_when_cascade_hits_protected(self, monkeypatch):
        scripts: list[str] = []
        # A custom module CASCADE FK would drag res_partner into the closure.
        self._patch(monkeypatch, scripts, closure_extra={"res_partner"})
        ok, msg = purge_transactional_data("mydb")
        assert ok is False
        assert "res_partner" in msg
        assert scripts == []  # no deletion happened

    def test_aborts_when_not_superuser(self, monkeypatch):
        scripts: list[str] = []
        self._patch(monkeypatch, scripts, superuser=False)
        ok, msg = purge_transactional_data("mydb")
        assert ok is False
        assert "superuser" in msg
        assert scripts == []

    def test_returns_false_on_delete_failure(self, monkeypatch):
        scripts: list[str] = []
        self._patch(monkeypatch, scripts, run_ok=False)
        ok, msg = purge_transactional_data("mydb")
        assert ok is False
        assert "boom" in msg

    def test_resolve_purge_tables_filters_by_existence(self, monkeypatch):
        present = {"stock_move", "sale_order"}
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"id"} if table in present else set(),
        )
        tables = resolve_purge_tables("mydb")
        assert set(tables) == present

    def test_null_repair_targets_rejects_bad_identifier(self, monkeypatch):
        """F1: closure names (DB-sourced regclass::text) must be identifier-checked."""
        # A maliciously double-quoted table name smuggles a single quote past naive
        # f-string interpolation into the IN (...) clause.
        bad_closure = {"x'); DROP TABLE res_users; --"}
        with pytest.raises(ValueError, match="Unsafe SQL identifier"):
            _null_repair_targets(bad_closure, "mydb")

    def test_null_repair_targets_accepts_valid_identifiers(self, monkeypatch):
        """Well-formed closure names build the IN clause and run the query."""
        captured: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda query, **k: (captured.append(query), (True, "res_company|account_opening_move_id"))[1],
        )
        targets = _null_repair_targets({"account_move", "stock_move"}, "mydb")
        assert targets == [("res_company", "account_opening_move_id")]
        assert "'account_move'" in captured[0] and "'stock_move'" in captured[0]
        # No smuggled quote survived the guard.
        assert "DROP TABLE" not in captured[0]


class TestRunRecompute:
    """odoo-bin shell recompute of stored computed fields (v0.44.0)."""

    def test_builds_shell_command_and_pipes_script(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["input"] = kwargs.get("input")

            class _R:
                stdout = "odoodev-recompute: done"

            return _R()

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, out = run_recompute("mydb", "/venv/py", "/srv/odoo-bin", "/c.conf", {"A": "1"}, "/cwd")
        assert ok is True
        assert captured["cmd"] == [
            "/venv/py",
            "/srv/odoo-bin",
            "shell",
            "-c",
            "/c.conf",
            "-d",
            "mydb",
            "--no-http",
        ]
        # The recompute script is piped via stdin.
        assert "env.flush_all()" in captured["input"]
        assert "env.cr.commit()" in captured["input"]
        assert "modified" in captured["input"]

    def test_returns_false_on_error(self, monkeypatch):
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            raise sp.CalledProcessError(1, cmd, stderr="shell boom")

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, out = run_recompute("mydb", "/venv/py", "/srv/odoo-bin", "/c.conf", {}, "/cwd")
        assert ok is False
        assert "shell boom" in out

    def test_script_references_trigger_models(self):
        script = _build_recompute_script({"res.partner": ("name",), "crm.lead": ("email_from",)})
        assert "res.partner" in script
        assert "crm.lead" in script
        assert "invalidate_recordset" in script
        assert "env.flush_all()" in script
        assert "env.cr.commit()" in script


class TestParseModuleNames:
    """Normalization of module-list arguments (CLI string / playbook list)."""

    def test_comma_string_split_strip_dedupe(self):
        from odoodev.core.database import parse_module_names

        assert parse_module_names(" eq_a, eq_b ,eq_a,, eq_c ") == ["eq_a", "eq_b", "eq_c"]

    def test_list_passthrough_normalized(self):
        from odoodev.core.database import parse_module_names

        assert parse_module_names(["eq_a", " eq_b ", "eq_a", ""]) == ["eq_a", "eq_b"]

    def test_none_and_empty(self):
        from odoodev.core.database import parse_module_names

        assert parse_module_names(None) == []
        assert parse_module_names("") == []
        assert parse_module_names([]) == []
        assert parse_module_names(" , ,") == []


class TestBuildUninstallModulesScript:
    def test_script_contains_modules_and_uninstall_call(self):
        from odoodev.core.database import _build_uninstall_modules_script

        script = _build_uninstall_modules_script(["eq_a", "eq_b"])
        assert "['eq_a', 'eq_b']" in script
        assert "button_immediate_uninstall" in script
        assert "env.cr.commit()" in script
        assert 'state != "installed"' in script
        # stdout markers for CLI feedback
        assert "odoodev-uninstall: not-found" in script
        assert "odoodev-uninstall: not-installed" in script
        assert "odoodev-uninstall: uninstalled" in script
        assert "odoodev-uninstall: failed" in script

    def test_script_uninstalls_one_module_per_call(self):
        """Third-party overrides of button_immediate_uninstall assume a singleton
        (e.g. simplify_access_management reads self.name), so the script must
        never call the method on a multi-record set."""
        from odoodev.core.database import _build_uninstall_modules_script

        script = _build_uninstall_modules_script(["eq_b", "eq_a"])
        # singleton search per module inside the loop, no bulk uninstall call
        assert '("name", "=", _name)' in script
        assert "_rec.button_immediate_uninstall()" in script
        assert "_installed.button_immediate_uninstall" not in script
        # each uninstall rebuilds the registry → fresh env per iteration
        assert "odoo.api.Environment(_cr, _uid, _ctx)" in script
        # user-given order is preserved (dependency order is the caller's contract)
        assert "[m for m in MODULES if m in _found_names]" in script
        assert "['eq_b', 'eq_a']" in script
        # a failing module doesn't block the rest, but the script exits non-zero
        assert "traceback.print_exc" in script
        assert "raise SystemExit(1)" in script

    def test_script_is_valid_python(self):
        import ast

        from odoodev.core.database import _build_uninstall_modules_script

        ast.parse(_build_uninstall_modules_script(["eq_a", "eq_b"]))


class TestRunUninstallModules:
    """odoo-bin shell module uninstall before the sanitize pipeline (v0.45.0)."""

    def test_builds_shell_command_and_pipes_script(self, monkeypatch):
        from odoodev.core.database import run_uninstall_modules

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["input"] = kwargs.get("input")

            class _R:
                stdout = "odoodev-uninstall: uninstalled eq_a"

            return _R()

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, out = run_uninstall_modules("mydb", ["eq_a"], "/venv/py", "/srv/odoo-bin", "/c.conf", {"A": "1"}, "/cwd")
        assert ok is True
        assert "uninstalled eq_a" in out
        assert captured["cmd"] == [
            "/venv/py",
            "/srv/odoo-bin",
            "shell",
            "-c",
            "/c.conf",
            "-d",
            "mydb",
            "--no-http",
        ]
        assert "button_immediate_uninstall" in captured["input"]
        assert "'eq_a'" in captured["input"]

    def test_returns_false_on_error(self, monkeypatch):
        import subprocess as sp

        from odoodev.core.database import run_uninstall_modules

        def fake_run(cmd, **kwargs):
            raise sp.CalledProcessError(
                1,
                cmd,
                output="odoodev-uninstall: uninstalled eq_a\nodoodev-uninstall: failed eq_b\n",
                stderr="uninstall boom",
            )

        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, out = run_uninstall_modules("mydb", ["eq_a", "eq_b"], "/venv/py", "/srv/odoo-bin", "/c.conf", {}, "/cwd")
        assert ok is False
        # stdout markers are kept on failure — they tell which modules still succeeded
        assert "odoodev-uninstall: uninstalled eq_a" in out
        assert "odoodev-uninstall: failed eq_b" in out
        assert "uninstall boom" in out


class TestDbUninstallCommand:
    """CLI tests for the standalone 'db uninstall' command."""

    def _patch_cmd(self, monkeypatch, tmp_path, calls, inv=None, uninstall_result=(True, "")):
        from odoodev.commands import db as db_cmd
        from odoodev.commands import start as start_cmd

        cfg = types.SimpleNamespace(
            version="18",
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
        )
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(start_cmd, "resolve_odoo_invocation", lambda vc, ev: inv)
        monkeypatch.setattr(
            db_cmd,
            "run_uninstall_modules",
            lambda name, modules, **k: (
                calls.setdefault("uninstall", []).append((name, list(modules))),
                uninstall_result,
            )[1],
        )

    def test_yes_runs_uninstall(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        self._patch_cmd(monkeypatch, tmp_path, calls, inv={})
        result = CliRunner().invoke(cli, ["db", "uninstall", "18", "-n", "testdb", "-m", "eq_a,eq_b", "-y"])
        assert result.exit_code == 0, result.output
        assert calls.get("uninstall") == [("testdb", ["eq_a", "eq_b"])]

    def test_declined_confirm_aborts(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        self._patch_cmd(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "uninstall", "18", "-n", "testdb", "-m", "eq_a"])
        assert result.exit_code == 0, result.output
        assert "uninstall" not in calls
        assert "Aborted" in result.output

    def test_no_modules_errors(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        self._patch_cmd(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "text_input", lambda *a, **k: "")
        result = CliRunner().invoke(cli, ["db", "uninstall", "18", "-n", "testdb", "-y"])
        assert result.exit_code == 1
        assert "No module names" in result.output

    def test_env_not_ready_errors(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        self._patch_cmd(monkeypatch, tmp_path, calls, inv=None)
        result = CliRunner().invoke(cli, ["db", "uninstall", "18", "-n", "testdb", "-m", "eq_a", "-y"])
        assert result.exit_code == 1
        assert "Cannot uninstall" in result.output
        assert "uninstall" not in calls

    def test_failure_exits_nonzero(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        self._patch_cmd(monkeypatch, tmp_path, calls, inv={}, uninstall_result=(False, "boom"))
        result = CliRunner().invoke(cli, ["db", "uninstall", "18", "-n", "testdb", "-m", "eq_a", "-y"])
        assert result.exit_code == 1
        assert "boom" in result.output

    def test_help(self):
        result = CliRunner().invoke(cli, ["db", "uninstall", "--help"])
        assert result.exit_code == 0
        assert "button_immediate_uninstall" in result.output


class TestDbUsersCommand:
    """CLI tests for 'db users' — the TUI itself is covered in test_tui_users_app.py."""

    def _patch_cmd(self, monkeypatch, tmp_path, launched):
        from odoodev.commands import db as db_cmd

        cfg = types.SimpleNamespace(
            version="18",
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
        )
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)

        class _FakeApp:
            def __init__(self, **kwargs):
                launched.append(kwargs)

            def run(self):
                pass

        monkeypatch.setattr("odoodev.tui.users_app.UsersTuiApp", _FakeApp)

    def test_launches_tui_with_db_params(self, monkeypatch, tmp_path):
        launched: list[dict] = []
        self._patch_cmd(monkeypatch, tmp_path, launched)
        result = CliRunner().invoke(cli, ["db", "users", "18", "-n", "testdb"])
        assert result.exit_code == 0, result.output
        assert len(launched) == 1
        assert launched[0]["db_name"] == "testdb"
        assert launched[0]["port"] == 18432

    def test_no_name_launches_with_empty_db(self, monkeypatch, tmp_path):
        launched: list[dict] = []
        self._patch_cmd(monkeypatch, tmp_path, launched)
        result = CliRunner().invoke(cli, ["db", "users", "18"])
        assert result.exit_code == 0, result.output
        assert launched[0]["db_name"] == ""

    def test_invalid_name_errors(self, monkeypatch, tmp_path):
        launched: list[dict] = []
        self._patch_cmd(monkeypatch, tmp_path, launched)
        result = CliRunner().invoke(cli, ["db", "users", "18", "-n", "bad;name"])
        assert result.exit_code == 1
        assert launched == []

    def test_help(self):
        result = CliRunner().invoke(cli, ["db", "users", "--help"])
        assert result.exit_code == 0
        assert "2FA" in result.output


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
    """Post-restore processing is OFF by default (v0.43.0) — opt in per flag or via --sanitize."""

    def _patch_flow(self, monkeypatch, tmp_path, calls, inv=None):
        """Patch the restore flow; `calls` collects per-step invocations by key."""
        from odoodev.commands import db as db_cmd
        from odoodev.commands import start as start_cmd

        cfg = types.SimpleNamespace(
            version="18",
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
        monkeypatch.setattr(db_cmd, "cleanup_restore_temp", lambda e: None)
        # resolve_odoo_invocation is imported inside db_restore from the start module
        monkeypatch.setattr(start_cmd, "resolve_odoo_invocation", lambda vc, ev: inv)
        monkeypatch.setattr(
            db_cmd, "deactivate_cronjobs", lambda name, **k: (calls.setdefault("cron", []).append(name), True)[1]
        )
        monkeypatch.setattr(
            db_cmd, "run_neutralize", lambda name, **k: (calls.setdefault("neut", []).append(name), (True, ""))[1]
        )
        monkeypatch.setattr(
            db_cmd, "anonymize_database", lambda name, **k: (calls.setdefault("anon", []).append(name), True)[1]
        )
        monkeypatch.setattr(
            db_cmd, "wipe_database", lambda name, **k: (calls.setdefault("wipe", []).append(name), True)[1]
        )
        monkeypatch.setattr(
            db_cmd, "anonymize_users", lambda name, **k: (calls.setdefault("users", []).append(name), True)[1]
        )
        monkeypatch.setattr(
            db_cmd,
            "purge_transactional_data",
            lambda name, **k: (calls.setdefault("purge", []).append(name), (True, "ok"))[1],
        )
        monkeypatch.setattr(db_cmd, "count_deletable_partners", lambda name, **k: 3)
        monkeypatch.setattr(
            db_cmd,
            "purge_master_data",
            lambda name, **k: (calls.setdefault("master_purge", []).append(name), (True, "ok"))[1],
        )
        monkeypatch.setattr(
            db_cmd, "run_recompute", lambda name, **k: (calls.setdefault("recompute", []).append(name), (True, ""))[1]
        )
        monkeypatch.setattr(
            db_cmd,
            "run_uninstall_modules",
            lambda name, modules, **k: (calls.setdefault("uninstall", []).append(list(modules)), (True, ""))[1],
        )
        monkeypatch.setattr(db_cmd, "neutralize_bank_sync", lambda name, **k: True)
        # Disk-space check + delete-backup prompt — neutralized for deterministic flow.
        monkeypatch.setattr(db_cmd, "check_restore_space", lambda b, t, d: (True, "", 0))
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        # Uninstall-modules prompt (CliRunner has no TTY — questionary would return
        # None and text_input would raise SystemExit(0), truncating the flow).
        monkeypatch.setattr(db_cmd, "text_input", lambda *a, **k: "")

    def _restore(self, backup, *flags):
        return CliRunner().invoke(cli, ["db", "restore", "18", "-n", "testdb", "-z", str(backup), *flags])

    def test_help_lists_all_processing_flags(self):
        result = CliRunner().invoke(cli, ["db", "restore", "--help"])
        for flag in (
            "--sanitize",
            "--neutralize",
            "--no-neutralize",
            "--anonymize",
            "--wipe",
            "--deactivate-cron",
            "--purge-transactions",
            "--purge-master-data",
            "--no-purge-master-data",
            "--recompute",
            "--uninstall-modules",
        ):
            assert flag in result.output
        # removed cloud-integrations flag must be gone
        assert "deactivate-cloud-integrations" not in result.output

    def test_nothing_runs_by_default(self, monkeypatch, tmp_path):
        """The restored database is left completely untouched without explicit flags."""
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup)
        assert result.exit_code == 0, result.output
        assert calls == {}  # no cron/neutralize/anonymize/wipe/users
        assert "left untouched" in result.output

    def test_anonymize_opt_in(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls)
        result = self._restore(backup, "--anonymize")
        assert result.exit_code == 0, result.output
        assert calls.get("anon") == ["testdb"]
        assert "wipe" not in calls  # wipe is a separate decision now

    def test_wipe_opt_in(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls)
        result = self._restore(backup, "--wipe")
        assert result.exit_code == 0, result.output
        assert calls.get("wipe") == ["testdb"]
        assert "anon" not in calls

    def test_neutralize_opt_in_when_env_ready(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--neutralize")
        assert result.exit_code == 0, result.output
        assert calls.get("neut") == ["testdb"]

    def test_deactivate_cron_opt_in(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls)
        result = self._restore(backup, "--deactivate-cron")
        assert result.exit_code == 0, result.output
        assert calls.get("cron") == ["testdb"]

    def test_sanitize_enables_all_but_users(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--sanitize", "-y")
        assert result.exit_code == 0, result.output
        assert calls.get("cron") == ["testdb"]
        assert calls.get("neut") == ["testdb"]
        assert calls.get("anon") == ["testdb"]
        assert calls.get("wipe") == ["testdb"]
        assert calls.get("recompute") == ["testdb"]  # auto-runs after anonymize
        assert calls.get("master_purge") == ["testdb"]  # v0.48.0: master-data purge is in --sanitize
        assert "users" not in calls  # --anonymize-users stays a separate opt-in
        assert "purge" not in calls  # movement-only purge skipped (master purge includes it)

    def test_no_purge_master_data_escapes_sanitize(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--sanitize", "--no-purge-master-data", "-y")
        assert result.exit_code == 0, result.output
        assert "master_purge" not in calls  # explicit --no- wins
        assert calls.get("wipe") == ["testdb"]  # the anonymize-only sanitize still runs

    def test_master_purge_confirmation_declined_aborts(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        # _patch_flow patches confirm -> False, declining the purge y/N gate.
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--purge-master-data")
        assert result.exit_code == 0, result.output
        assert "master_purge" not in calls
        assert "Aborted master-data purge" in result.output

    def test_master_purge_confirmation_accepted_proceeds(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        # Approve only the purge gate; leave every other confirm (delete-backup, …) declined.
        monkeypatch.setattr(db_cmd, "confirm", lambda msg, **k: "partner(s)" in msg)
        result = self._restore(backup, "--purge-master-data")
        assert result.exit_code == 0, result.output
        assert calls.get("master_purge") == ["testdb"]

    def test_explicit_no_flag_wins_over_sanitize(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--sanitize", "--no-anonymize")
        assert result.exit_code == 0, result.output
        assert "anon" not in calls
        assert calls.get("wipe") == ["testdb"]  # the rest still runs

    def test_neutralize_graceful_skip_when_env_missing(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        # inv=None → env not ready → restore still succeeds, run_neutralize not called
        self._patch_flow(monkeypatch, tmp_path, calls, inv=None)
        result = self._restore(backup, "--neutralize")
        assert result.exit_code == 0, result.output
        assert "neut" not in calls

    def test_purge_transactions_opt_in(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls)
        result = self._restore(backup, "--purge-transactions")
        assert result.exit_code == 0, result.output
        assert calls.get("purge") == ["testdb"]
        assert "anon" not in calls  # purge does not imply anonymize

    def test_recompute_runs_after_anonymize(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--anonymize")
        assert result.exit_code == 0, result.output
        assert calls.get("anon") == ["testdb"]
        assert calls.get("recompute") == ["testdb"]

    def test_no_recompute_skips(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--anonymize", "--no-recompute")
        assert result.exit_code == 0, result.output
        assert calls.get("anon") == ["testdb"]
        assert "recompute" not in calls

    def test_recompute_not_run_without_anonymize(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        result = self._restore(backup, "--wipe")
        assert result.exit_code == 0, result.output
        assert "recompute" not in calls  # recompute is tied to anonymize

    def test_uninstall_modules_flag_runs_before_sanitize(self, monkeypatch, tmp_path):
        """--uninstall-modules runs before every sanitize step (cron first among them)."""
        order: list[str] = []
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(
            db_cmd,
            "run_uninstall_modules",
            lambda name, modules, **k: (order.append("uninstall"), (True, ""))[1],
        )
        monkeypatch.setattr(db_cmd, "deactivate_cronjobs", lambda name, **k: (order.append("cron"), True)[1])
        result = self._restore(backup, "--sanitize", "--uninstall-modules", "eq_x")
        assert result.exit_code == 0, result.output
        assert order[:2] == ["uninstall", "cron"]

    def test_uninstall_modules_graceful_skip_when_env_missing(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv=None)
        result = self._restore(backup, "--uninstall-modules", "eq_x")
        assert result.exit_code == 0, result.output
        assert "uninstall" not in calls
        assert "odoodev db uninstall" in result.output  # hint to run standalone later

    def test_uninstall_modules_not_prompted_without_sanitize_step(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(
            db_cmd,
            "text_input",
            lambda *a, **k: pytest.fail("must not prompt for modules without a sanitize step"),
        )
        result = self._restore(backup)
        assert result.exit_code == 0, result.output
        assert "uninstall" not in calls

    def test_uninstall_modules_prompted_when_interactive_and_sanitize(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "text_input", lambda *a, **k: "eq_foo, eq_bar")
        result = self._restore(backup, "--sanitize")
        assert result.exit_code == 0, result.output
        assert calls.get("uninstall") == [["eq_foo", "eq_bar"]]

    def test_uninstall_modules_flag_skips_prompt(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        def _no_uninstall_prompt(msg, *a, **k):
            if "uninstall" in msg.lower():
                pytest.fail("must not prompt for uninstall when --uninstall-modules is given")
            return ""  # other prompts (master-data confirmation) → empty, harmless here

        monkeypatch.setattr(db_cmd, "text_input", _no_uninstall_prompt)
        result = self._restore(backup, "--sanitize", "--uninstall-modules", "eq_x")
        assert result.exit_code == 0, result.output
        assert calls.get("uninstall") == [["eq_x"]]

    def test_uninstall_modules_yes_skips_prompt(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(
            db_cmd,
            "text_input",
            lambda *a, **k: pytest.fail("must not prompt with -y"),
        )
        result = self._restore(backup, "--sanitize", "-y")
        assert result.exit_code == 0, result.output
        assert "uninstall" not in calls

    def test_uninstall_modules_failure_nonfatal_with_yes(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "run_uninstall_modules", lambda name, modules, **k: (False, "boom"))
        result = self._restore(backup, "--sanitize", "-y", "--uninstall-modules", "eq_x")
        assert result.exit_code == 0, result.output
        assert "non-fatal" in result.output
        assert calls.get("cron") == ["testdb"]  # sanitize pipeline continued

    def test_uninstall_modules_failure_interactive_abort(self, monkeypatch, tmp_path):
        calls: dict[str, list] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "run_uninstall_modules", lambda name, modules, **k: (False, "boom"))
        # confirm stubbed to False in _patch_flow → decline "continue anyway" → abort
        result = self._restore(backup, "--sanitize", "--uninstall-modules", "eq_x")
        assert result.exit_code == 1
        assert "Aborted" in result.output
        assert "cron" not in calls  # sanitize pipeline never ran

    def test_purge_command_help(self):
        result = CliRunner().invoke(cli, ["db", "purge", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "keeping products" in result.output

    def test_recompute_command_help(self):
        result = CliRunner().invoke(cli, ["db", "recompute", "--help"])
        assert result.exit_code == 0
        assert "computed" in result.output

    def test_neutralize_command_help(self):
        result = CliRunner().invoke(cli, ["db", "neutralize", "--help"])
        assert result.exit_code == 0
        assert "--stdout" in result.output

    def test_anonymize_users_help_flag(self):
        result = CliRunner().invoke(cli, ["db", "restore", "--help"])
        assert "--anonymize-users" in result.output
        assert "--user-password" in result.output

    def test_anonymize_users_opt_in_works_standalone(self, monkeypatch, tmp_path):
        """--anonymize-users no longer requires --anonymize (v0.43.0)."""
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls)
        result = self._restore(backup, "--anonymize-users")
        assert result.exit_code == 0, result.output
        assert calls.get("users") == ["testdb"]
        assert "anon" not in calls

    def test_anonymize_users_off_by_default(self, monkeypatch, tmp_path):
        calls: dict[str, list[str]] = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        self._patch_flow(monkeypatch, tmp_path, calls)
        result = self._restore(backup, "--sanitize")
        assert result.exit_code == 0, result.output
        assert "users" not in calls  # res_users untouched unless explicitly requested


class TestDbPurgeCommand:
    """Standalone `odoodev db purge` command (v0.44.0)."""

    def _patch(self, monkeypatch, tmp_path, purge_result=(True, "ok")):
        from odoodev.commands import db as db_cmd

        cfg = types.SimpleNamespace(
            version="18",
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path)),
        )
        calls: dict[str, list] = {}
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(db_cmd, "_load_env_vars", lambda vc: {})
        monkeypatch.setattr(
            db_cmd, "_get_db_params", lambda vc, ev: {"host": "localhost", "port": 18432, "user": "ownerp"}
        )
        monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda version, params: None)
        monkeypatch.setattr(db_cmd, "resolve_purge_tables", lambda name, **k: ["stock_move", "account_move"])
        monkeypatch.setattr(
            db_cmd,
            "purge_transactional_data",
            lambda name, **k: (calls.setdefault("purge", []).append(name), purge_result)[1],
        )
        return calls

    def test_dry_run_deletes_nothing(self, monkeypatch, tmp_path):
        calls = self._patch(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["db", "purge", "18", "-n", "testdb", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "stock_move" in result.output
        assert "purge" not in calls  # nothing deleted

    def test_yes_skips_confirm_and_purges(self, monkeypatch, tmp_path):
        calls = self._patch(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["db", "purge", "18", "-n", "testdb", "--yes"])
        assert result.exit_code == 0, result.output
        assert calls.get("purge") == ["testdb"]

    def test_confirm_declined_aborts(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        calls = self._patch(monkeypatch, tmp_path)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "purge", "18", "-n", "testdb"])
        assert result.exit_code == 0
        assert "Aborted" in result.output
        assert "purge" not in calls

    def test_no_tables_is_noop(self, monkeypatch, tmp_path):
        from odoodev.commands import db as db_cmd

        calls = self._patch(monkeypatch, tmp_path)
        monkeypatch.setattr(db_cmd, "resolve_purge_tables", lambda name, **k: [])
        result = CliRunner().invoke(cli, ["db", "purge", "18", "-n", "testdb", "--yes"])
        assert result.exit_code == 0
        assert "Nothing to purge" in result.output
        assert "purge" not in calls

    def test_purge_failure_exits_nonzero(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path, purge_result=(False, "Aborted — protected table"))
        result = CliRunner().invoke(cli, ["db", "purge", "18", "-n", "testdb", "--yes"])
        assert result.exit_code == 1
        assert "protected table" in result.output


class TestHandleDbPurge:
    """Playbook handler for db.purge (v0.44.0)."""

    def test_purges_via_handler(self, monkeypatch, tmp_path):
        from odoodev.core import automation

        cfg = types.SimpleNamespace(version="18", paths=types.SimpleNamespace(native_dir=str(tmp_path)))
        monkeypatch.setattr(automation, "_load_env_vars", lambda vc: {})
        monkeypatch.setattr(
            automation, "_get_db_params", lambda vc, ev: {"host": "localhost", "port": 18432, "user": "ownerp"}
        )
        monkeypatch.setattr(
            "odoodev.core.database.purge_transactional_data", lambda name, **k: (True, "2 tables emptied")
        )
        result = automation.handle_db_purge(cfg, {"name": "testdb"})
        assert result.status == "ok"

    def test_missing_name_errors(self, monkeypatch, tmp_path):
        from odoodev.core import automation

        cfg = types.SimpleNamespace(version="18", paths=types.SimpleNamespace(native_dir=str(tmp_path)))
        result = automation.handle_db_purge(cfg, {})
        assert result.status == "error"


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


class TestRunPsqlTuples:
    """Tuples-only unaligned psql execution (-t -A -F tab)."""

    def test_uses_unaligned_tab_separated_flags(self, monkeypatch):
        """Regression: psql's default aligned format renders embedded tabs as
        SPACES and booleans cast via ::text as 'true'/'false' — tab-splitting
        aligned output silently yields zero rows. Row queries must run
        tuples-only + unaligned with an explicit tab field separator."""
        from odoodev.core.database import PG_EXEC_HOST, PgExecMode, _run_psql_tuples

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd

            class _R:
                stdout = "1\tadmin\tt\n2\tjweber\tf\n"

            return _R()

        monkeypatch.setattr("odoodev.core.database.resolve_pg_exec_mode", lambda port: PgExecMode(kind=PG_EXEC_HOST))
        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, rows = _run_psql_tuples("SELECT id, login, active FROM res_users;", db="db")
        assert ok is True
        assert rows == [["1", "admin", "t"], ["2", "jweber", "f"]]
        cmd = captured["cmd"]
        assert "-t" in cmd and "-A" in cmd
        assert cmd[cmd.index("-F") + 1] == "\t"

    def test_returns_false_on_error(self, monkeypatch):
        import subprocess as sp

        from odoodev.core.database import PG_EXEC_HOST, PgExecMode, _run_psql_tuples

        def fake_run(cmd, **kwargs):
            raise sp.CalledProcessError(1, cmd, stderr="boom")

        monkeypatch.setattr("odoodev.core.database.resolve_pg_exec_mode", lambda port: PgExecMode(kind=PG_EXEC_HOST))
        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        ok, rows = _run_psql_tuples("SELECT 1;", db="db")
        assert ok is False
        assert rows == []


class TestListUsers:
    """User listing for the db users TUI."""

    # Real `psql -t -A -F $'\t'` output: one line per row, literal tab bytes,
    # booleans as t/f (verified against a live v18 database).
    _PSQL_ROWS = [
        ["1", "admin", "Administrator", "t", "t", "f"],
        ["5", "jweber", "Jörg Weber", "f", "t", "f"],
        ["7", "mmueller", "Max Müller", "t", "f", "f"],
    ]

    def test_parses_users_from_psql_output(self, monkeypatch):
        from odoodev.core.database import list_users

        queries: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"id", "login", "active", "totp_secret", "share", "partner_id"},
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_tuples",
            lambda q, **k: (queries.append(q), (True, self._PSQL_ROWS))[1],
        )
        users = list_users("db")
        assert [u.login for u in users] == ["admin", "jweber", "mmueller"]
        admin, jweber, mmueller = users
        assert admin.id == 1 and admin.totp_enabled and admin.active
        assert jweber.id == 5 and not jweber.active and jweber.totp_enabled
        assert mmueller.id == 7 and mmueller.active and not mmueller.totp_enabled
        # portal users excluded by default, technical logins always excluded, admin kept
        assert "share, false) = false" in queries[0]
        assert "'__system__'" in queries[0]
        assert "'admin'" not in queries[0]
        # no ::text boolean casts — unaligned psql prints booleans as t/f natively
        assert "active::text" not in queries[0]

    def test_end_to_end_against_real_psql_output_format(self, monkeypatch):
        """Full pipeline against verbatim subprocess output as psql -t -A -F
        emits it — guards the tab/boolean format contract end-to-end."""
        from odoodev.core.database import PG_EXEC_HOST, PgExecMode, list_users

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd

            class _R:
                stdout = "2\tadmin\tAdministrator\tt\tf\tf\n"

            return _R()

        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"id", "login", "active", "totp_secret", "share", "partner_id"},
        )
        monkeypatch.setattr("odoodev.core.database.resolve_pg_exec_mode", lambda port: PgExecMode(kind=PG_EXEC_HOST))
        monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
        users = list_users("db")
        assert len(users) == 1
        assert users[0].login == "admin" and users[0].active and not users[0].totp_enabled
        # the row query must run unaligned — aligned mode swallows the tabs
        assert "-A" in captured["cmd"] and "-t" in captured["cmd"]

    def test_include_portal_drops_share_filter(self, monkeypatch):
        from odoodev.core.database import list_users

        queries: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"totp_secret", "share"},
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_tuples",
            lambda q, **k: (queries.append(q), (True, []))[1],
        )
        list_users("db", include_portal=True)
        assert "= false" not in queries[0].split("WHERE", 1)[1].split("ORDER")[0].replace("share, false)", "")

    def test_totp_column_guard(self, monkeypatch):
        from odoodev.core.database import list_users

        queries: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"id", "login", "share"},  # no totp_secret
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql_tuples",
            lambda q, **k: (queries.append(q), (True, [["1", "admin", "Administrator", "t", "f", "f"]]))[1],
        )
        users = list_users("db")
        assert "totp_secret" not in queries[0]
        assert users[0].totp_enabled is False

    def test_missing_table_returns_empty(self, monkeypatch):
        from odoodev.core.database import list_users

        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: set())
        assert list_users("db") == []


class TestSetUserPassword:
    def test_updates_password_with_hash_only(self, monkeypatch):
        from odoodev.core.database import set_user_password

        psql: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (psql.append(q), (True, "UPDATE 1"))[1],
        )
        ok, _ = set_user_password("db", 7, "sup3r-secret")
        assert ok is True
        assert len(psql) == 1
        assert "UPDATE res_users SET password = " in psql[0]
        assert "WHERE id = 7;" in psql[0]
        assert "pbkdf2-sha512" in psql[0]
        # the plaintext must never reach the SQL
        assert "sup3r-secret" not in psql[0]


class TestDisableUser2fa:
    def test_clears_secret_and_devices(self, monkeypatch):
        from odoodev.core.database import disable_user_2fa

        psql: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"totp_secret"} if table == "res_users" else {"id", "user_id"},
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (psql.append(q), (True, ""))[1],
        )
        ok, msg = disable_user_2fa("db", 7)
        assert ok is True
        assert psql == [
            "UPDATE res_users SET totp_secret = NULL WHERE id = 7;",
            "DELETE FROM auth_totp_device WHERE user_id = 7;",
        ]

    def test_no_device_table_only_clears_secret(self, monkeypatch):
        from odoodev.core.database import disable_user_2fa

        psql: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"totp_secret"} if table == "res_users" else set(),
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (psql.append(q), (True, ""))[1],
        )
        ok, _ = disable_user_2fa("db", 7)
        assert ok is True
        assert psql == ["UPDATE res_users SET totp_secret = NULL WHERE id = 7;"]

    def test_no_totp_column_is_successful_noop(self, monkeypatch):
        from odoodev.core.database import disable_user_2fa

        monkeypatch.setattr("odoodev.core.database._existing_columns", lambda table, *a, **k: {"id", "login"})
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: pytest.fail("no SQL must run without a totp_secret column"),
        )
        ok, msg = disable_user_2fa("db", 7)
        assert ok is True
        assert "not installed" in msg

    def test_failure_propagates(self, monkeypatch):
        from odoodev.core.database import disable_user_2fa

        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: {"totp_secret"} if table == "res_users" else set(),
        )
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (False, "boom"))
        ok, msg = disable_user_2fa("db", 7)
        assert ok is False
        assert "boom" in msg


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
                version="18",
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
        # Normalize: strip ANSI colour codes and collapse whitespace so the
        # assertion is robust to Rich line-wrapping (which may break the phrase
        # "active connection(s)" across lines depending on console width).
        clean = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
        assert "active connection" in clean

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
            version="18",
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


class TestDbDropMulti:
    """`db drop` multi-select / bulk deletion (-m / --all / --filter, v0.47.0)."""

    def _patch(self, monkeypatch, tmp_path, available, dropped, *, drop_ok=True, exists=None):
        """Patch the drop command; `dropped` collects names actually dropped."""
        from odoodev.commands import db as db_cmd

        cfg = types.SimpleNamespace(
            version="18",
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
        )
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
        monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda v, p: None)
        monkeypatch.setattr(db_cmd, "list_databases", lambda **k: list(available))
        monkeypatch.setattr(db_cmd, "database_exists", lambda n, **k: (exists or available).__contains__(n))

        def _drop(n, **k):
            if drop_ok:
                dropped.append(n)
            return drop_ok

        monkeypatch.setattr(db_cmd, "drop_database", _drop)
        monkeypatch.setattr(db_cmd, "get_filestore_path", lambda v, db_name: str(tmp_path / "nofs" / db_name))
        return db_cmd

    def test_all_drops_every_candidate(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b", "v18_c"], dropped)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "--all", "-y"])
        assert result.exit_code == 0, result.output
        assert sorted(dropped) == ["v18_a", "v18_b", "v18_c"]

    def test_filter_narrows_all(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a", "test_x", "test_y"], dropped)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "--all", "--filter", "test_", "-y"])
        assert result.exit_code == 0, result.output
        assert sorted(dropped) == ["test_x", "test_y"]

    def test_multiple_explicit_names(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b"], dropped)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "-n", "v18_a", "-n", "v18_b", "-y"])
        assert result.exit_code == 0, result.output
        assert sorted(dropped) == ["v18_a", "v18_b"]

    def test_system_db_guard_rejects_explicit(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a"], dropped, exists=["v18_a", "postgres"])
        result = CliRunner().invoke(cli, ["db", "drop", "18", "-n", "postgres", "-y"])
        assert result.exit_code == 1
        assert dropped == []
        assert "system database" in result.output.lower()

    def test_multi_checkbox_selection(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        db_cmd = self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b", "v18_c"], dropped)
        monkeypatch.setattr(db_cmd, "checkbox", lambda msg, choices: ["v18_a", "v18_c"])
        result = CliRunner().invoke(cli, ["db", "drop", "18", "-m", "-y"])
        assert result.exit_code == 0, result.output
        assert sorted(dropped) == ["v18_a", "v18_c"]

    def test_empty_filter_match_aborts(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b"], dropped)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "--all", "--filter", "nomatch", "-y"])
        assert result.exit_code == 1
        assert dropped == []

    def test_bulk_confirmation_declined_aborts(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        db_cmd = self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b"], dropped)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "--all"])
        assert result.exit_code == 0, result.output
        assert dropped == []
        assert "Aborted" in result.output

    def test_bulk_confirmation_accepted_proceeds(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        db_cmd = self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b"], dropped)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: True)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "--all"])
        assert result.exit_code == 0, result.output
        assert sorted(dropped) == ["v18_a", "v18_b"]

    def test_mutually_exclusive_modes(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a"], dropped)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "-n", "v18_a", "--all", "-y"])
        assert result.exit_code == 1
        assert dropped == []

    def test_failure_exits_nonzero_and_tallies(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        self._patch(monkeypatch, tmp_path, ["v18_a", "v18_b"], dropped, drop_ok=False)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "--all", "-y"])
        assert result.exit_code == 1
        assert "failed" in result.output.lower()

    def test_single_name_backward_compatible(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        db_cmd = self._patch(monkeypatch, tmp_path, ["v18_a"], dropped)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: True)
        result = CliRunner().invoke(cli, ["db", "drop", "18", "-n", "v18_a"])
        assert result.exit_code == 0, result.output
        assert dropped == ["v18_a"]

    def test_terminate_connections_flag(self, monkeypatch, tmp_path):
        dropped: list[str] = []
        db_cmd = self._patch(monkeypatch, tmp_path, ["v18_a"], dropped)
        term: list[str] = []
        monkeypatch.setattr(db_cmd, "get_active_connection_count", lambda n, **k: 3)
        monkeypatch.setattr(db_cmd, "terminate_connections", lambda n, **k: (term.append(n), True)[1])
        result = CliRunner().invoke(cli, ["db", "drop", "18", "-n", "v18_a", "-y", "--terminate-connections"])
        assert result.exit_code == 0, result.output
        assert term == ["v18_a"] and dropped == ["v18_a"]

    def test_help_lists_new_options(self):
        result = CliRunner().invoke(cli, ["db", "drop", "--help"])
        assert result.exit_code == 0
        for token in ("--multi", "--all", "--filter", "--terminate-connections"):
            assert token in result.output


class TestPurgeMasterData:
    """Full template-DB reset: movement + content + customer/partner deletion (v0.48.0)."""

    def test_keep_temp_table_sql_covers_users_companies_and_ancestors(self):
        from odoodev.core.database import _keep_partner_temp_table_sql

        sql = _keep_partner_temp_table_sql()
        assert "res_partner_keep" in sql and "ON COMMIT DROP" in sql
        assert "partner_id FROM res_users" in sql
        assert "partner_id FROM res_company" in sql
        assert "parent_id" in sql and "commercial_partner_id" in sql

    def test_purge_model_names_exclude_kept_models(self):
        """Product/view/module/company/user attachments must never be delete targets."""
        from odoodev.core.database import PURGE_MODEL_NAMES

        kept = {"product.template", "product.product", "product.pricelist", "ir.ui.view", "res.company", "res.users"}
        assert not (set(PURGE_MODEL_NAMES.values()) & kept)
        # movement + content roots are covered
        for tbl in ("sale_order", "account_move", "crm_lead", "hr_employee", "mail_message", "helpdesk_ticket"):
            assert tbl in PURGE_MODEL_NAMES

    def test_attachment_sql_keeps_products_deletes_removed(self):
        from odoodev.core.database import _attachment_delete_sql

        sql = _attachment_delete_sql(["sale.order", "crm.lead"])
        assert "'sale.order'" in sql and "'crm.lead'" in sql
        assert "product.template" not in sql and "product.product" not in sql
        assert "res_model = 'res.partner' AND res_id" in sql

    def test_cascade_delete_plan_orders_deepest_first(self, monkeypatch):
        """Multi-hop cascade children must be deleted before their parents, and
        res_partner itself last, so no orphans remain."""
        from odoodev.core import database as d

        graph = {
            ("res_partner",): [("child_a", "cola", "res_partner"), ("link1", "colL", "res_partner")],
            ("child_a", "link1"): [("child_b", "colb", "child_a")],
            ("child_b",): [],
        }
        monkeypatch.setattr(d, "_cascade_child_edges", lambda parents, *a, **k: graph.get(tuple(parents), []))
        plan = d._partner_cascade_delete_plan("db")
        joined = "\n".join(plan)
        assert plan[-1] == "DELETE FROM res_partner WHERE id NOT IN (SELECT id FROM res_partner_keep);"
        # deepest (child_b) before its parent (child_a), which is before res_partner
        assert joined.index("child_b") < joined.index('"child_a"')
        assert joined.index('"child_a"') < joined.index("DELETE FROM res_partner ")
        # row-scoped, not whole-table
        assert 'WHERE "cola" IN (SELECT id FROM "res_partner"' in joined

    def test_cascade_plan_bounded_against_cycles(self, monkeypatch):
        """A cyclic/self-feeding graph must terminate (seen-guard + depth bound)."""
        from odoodev.core import database as d

        monkeypatch.setattr(
            d,
            "_cascade_child_edges",
            lambda parents, *a, **k: [("t", "c", parents[0])] if "res_partner" in parents else [],
        )
        plan = d._partner_cascade_delete_plan("db")
        assert plan[-1].startswith("DELETE FROM res_partner")

    def _patch_intro(
        self, monkeypatch, *, movement, content, closure, edges, superuser=True, count=(10, 7), transient=()
    ):
        """Patch all introspection helpers purge_master_data depends on."""
        from odoodev.core import database as d

        monkeypatch.setattr(d, "resolve_purge_tables", lambda *a, **k: list(movement))
        monkeypatch.setattr(d, "_resolve_content_purge_tables", lambda *a, **k: list(content))
        monkeypatch.setattr(d, "_cascade_closure", lambda tables, *a, **k: set(closure))
        monkeypatch.setattr(d, "_fk_edges_into", lambda t, *a, **k: list(edges))
        monkeypatch.setattr(d, "_transient_tables", lambda *a, **k: set(transient))
        monkeypatch.setattr(d, "_null_repair_targets", lambda *a, **k: [])
        monkeypatch.setattr(
            d,
            "_partner_cascade_delete_plan",
            lambda *a, **k: ["DELETE FROM res_partner WHERE id NOT IN (SELECT id FROM res_partner_keep);"],
        )
        monkeypatch.setattr(d, "_is_superuser", lambda *a, **k: superuser)
        monkeypatch.setattr(d, "count_deletable_partners", lambda *a, **k: count[1])
        monkeypatch.setattr(d, "_run_psql_tuples", lambda q, **k: (True, [[str(count[0]), str(count[1])]]))
        return d

    def test_dry_run_deletes_nothing(self, monkeypatch):
        d = self._patch_intro(
            monkeypatch, movement=["sale_order"], content=["crm_lead"], closure={"sale_order", "crm_lead"}, edges=[]
        )
        called = {"file": False}
        monkeypatch.setattr(d, "_run_psql_file", lambda *a, **k: (called.__setitem__("file", True), (True, ""))[1])
        ok, msg = d.purge_master_data("db", dry_run=True)
        assert ok is True and called["file"] is False
        assert "dry-run" in msg and "7" in msg

    def test_aborts_when_closure_hits_protected(self, monkeypatch):
        d = self._patch_intro(
            monkeypatch, movement=["sale_order"], content=[], closure={"sale_order", "res_partner"}, edges=[]
        )
        called = {"file": False}
        monkeypatch.setattr(d, "_run_psql_file", lambda *a, **k: (called.__setitem__("file", True), (True, ""))[1])
        ok, msg = d.purge_master_data("db")
        assert ok is False and called["file"] is False
        assert "protected" in msg and "res_partner" in msg

    def test_aborts_without_superuser(self, monkeypatch):
        d = self._patch_intro(
            monkeypatch, movement=["sale_order"], content=[], closure={"sale_order"}, edges=[], superuser=False
        )
        called = {"file": False}
        monkeypatch.setattr(d, "_run_psql_file", lambda *a, **k: (called.__setitem__("file", True), (True, ""))[1])
        ok, msg = d.purge_master_data("db")
        assert ok is False and called["file"] is False
        assert "superuser" in msg

    def test_happy_path_builds_single_transaction(self, monkeypatch):
        d = self._patch_intro(
            monkeypatch,
            movement=["sale_order"],
            content=["crm_lead"],
            closure={"sale_order", "crm_lead"},
            edges=[("mail_push_device", "partner_id", "r"), ("website_visitor", "partner_id", "n")],
        )
        captured = {}
        monkeypatch.setattr(d, "_run_psql_file", lambda sql, **k: (captured.__setitem__("sql", sql), (True, ""))[1])
        ok, msg = d.purge_master_data("db")
        assert ok is True
        sql = captured["sql"]
        assert sql.startswith("BEGIN;") and sql.strip().endswith("COMMIT;")
        assert "session_replication_role = replica" in sql
        assert 'DELETE FROM "sale_order";' in sql and 'DELETE FROM "crm_lead";' in sql
        assert "res_partner_keep" in sql
        # unhandled restrict edge → drift-guard DO block; set-null edge → repair UPDATE
        assert "odoodev-purge-abort: unhandled FK mail_push_device.partner_id" in sql
        assert 'UPDATE "website_visitor" SET "partner_id" = NULL' in sql
        assert "DELETE FROM ir_attachment" in sql

    def test_abort_marker_surfaced_as_clean_error(self, monkeypatch):
        d = self._patch_intro(monkeypatch, movement=["sale_order"], content=[], closure={"sale_order"}, edges=[])
        monkeypatch.setattr(
            d, "_run_psql_file", lambda *a, **k: (False, "ERROR:  odoodev-purge-abort: unhandled FK x.y ...")
        )
        ok, msg = d.purge_master_data("db")
        assert ok is False and "Aborted (no data deleted)" in msg

    def test_transient_wizard_table_auto_cleared(self, monkeypatch):
        # A transient wizard table (account_payment_register) with an unhandled NO-ACTION FK
        # is cleared wholesale before the partner delete — no drift-guard abort.
        d = self._patch_intro(
            monkeypatch,
            movement=["sale_order"],
            content=[],
            closure={"sale_order"},
            edges=[("account_payment_register", "partner_id", "a")],
            transient={"account_payment_register"},
        )
        captured = {}
        monkeypatch.setattr(d, "_run_psql_file", lambda sql, **k: (captured.__setitem__("sql", sql), (True, ""))[1])
        ok, _ = d.purge_master_data("db")
        assert ok is True
        sql = captured["sql"]
        assert 'DELETE FROM "account_payment_register";' in sql
        # no drift-guard block for the transient table
        assert "unhandled FK account_payment_register" not in sql

    def test_non_transient_unhandled_still_aborts(self, monkeypatch):
        # Same edge, but NOT flagged transient → the drift guard still fires (protects real
        # master data in custom/OCA modules).
        d = self._patch_intro(
            monkeypatch,
            movement=["sale_order"],
            content=[],
            closure={"sale_order"},
            edges=[("account_payment_register", "partner_id", "a")],
            transient=set(),
        )
        captured = {}
        monkeypatch.setattr(d, "_run_psql_file", lambda sql, **k: (captured.__setitem__("sql", sql), (True, ""))[1])
        ok, _ = d.purge_master_data("db")
        assert ok is True
        sql = captured["sql"]
        assert 'DELETE FROM "account_payment_register";' not in sql
        assert "odoodev-purge-abort: unhandled FK account_payment_register.partner_id" in sql

    def test_transient_tables_maps_model_to_table(self, monkeypatch):
        from odoodev.core import database as d

        monkeypatch.setattr(
            d, "_run_psql_tuples", lambda q, **k: (True, [["account.payment.register"], ["base.language.install"]])
        )
        assert d._transient_tables("db") == {"account_payment_register", "base_language_install"}

    def test_transient_tables_empty_on_error(self, monkeypatch):
        from odoodev.core import database as d

        monkeypatch.setattr(d, "_run_psql_tuples", lambda q, **k: (False, []))
        assert d._transient_tables("db") == set()


class TestDbPurgeMasterDataCommand:
    """Standalone `db purge-master-data` CLI command (v0.48.0)."""

    def _patch(self, monkeypatch, spy):
        from odoodev.commands import db as db_cmd

        cfg = types.SimpleNamespace(version="18", ports=types.SimpleNamespace(db=18432), paths=types.SimpleNamespace())
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(db_cmd, "_load_env_vars", lambda cfg: {})
        monkeypatch.setattr(db_cmd, "_get_db_params", lambda cfg, ev: {"host": "h", "port": 1, "user": "u"})
        monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda v, p: None)
        monkeypatch.setattr(db_cmd, "count_deletable_partners", lambda name, **k: 4)
        monkeypatch.setattr(
            db_cmd,
            "purge_master_data",
            lambda name, dry_run=False, **k: (spy.append((name, dry_run)), (True, "done"))[1],
        )

    def test_dry_run_deletes_nothing(self, monkeypatch):
        spy: list = []
        self._patch(monkeypatch, spy)
        result = CliRunner().invoke(cli, ["db", "purge-master-data", "18", "-n", "db", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert spy == [("db", True)]

    def test_yes_runs_purge(self, monkeypatch):
        spy: list = []
        self._patch(monkeypatch, spy)
        result = CliRunner().invoke(cli, ["db", "purge-master-data", "18", "-n", "db", "-y"])
        assert result.exit_code == 0, result.output
        assert spy == [("db", False)]

    def test_confirmation_declined_aborts(self, monkeypatch):
        from odoodev.commands import db as db_cmd

        spy: list = []
        self._patch(monkeypatch, spy)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "purge-master-data", "18", "-n", "db"])
        assert result.exit_code == 0, result.output
        assert spy == []
        assert "Aborted" in result.output

    def test_confirmation_accepted_proceeds(self, monkeypatch):
        from odoodev.commands import db as db_cmd

        spy: list = []
        self._patch(monkeypatch, spy)
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: True)
        result = CliRunner().invoke(cli, ["db", "purge-master-data", "18", "-n", "db"])
        assert result.exit_code == 0, result.output
        assert spy == [("db", False)]

    def test_help(self):
        result = CliRunner().invoke(cli, ["db", "purge-master-data", "--help"])
        assert result.exit_code == 0
        assert "template-DB reset" in result.output.lower() or "master" in result.output.lower()
