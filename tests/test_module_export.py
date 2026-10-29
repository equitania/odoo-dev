"""Tests for odoodev.core.module_export."""

from datetime import datetime

from odoodev.core.module_export import (
    EXPORT_FIELDS,
    EXPORT_HEADER,
    EXPORT_SCOPES,
    build_export_path,
    is_exportable_module,
    write_modules_csv,
)


class TestIsExportableModule:
    """Test the module inclusion/exclusion predicate."""

    def test_normal_module_included(self):
        assert is_exportable_module("eq_sale") is True
        assert is_exportable_module("base") is True

    def test_theme_module_included(self):
        """Themes are always kept."""
        assert is_exportable_module("theme_clean") is True
        assert is_exportable_module("theme_bootswatch") is True

    def test_test_module_excluded(self):
        assert is_exportable_module("test_base") is False
        assert is_exportable_module("test_lint") is False

    def test_hardware_module_excluded(self):
        assert is_exportable_module("hw_escpos") is False
        assert is_exportable_module("hw_drivers") is False

    def test_hw_substring_anywhere_excluded(self):
        """'hw_' is matched as a substring, not only as a prefix."""
        assert is_exportable_module("pos_hw_proxy") is False

    def test_module_named_with_test_inside_kept(self):
        """Only the test_ prefix excludes — 'test' elsewhere is fine."""
        assert is_exportable_module("eq_test_helper") is True
        assert is_exportable_module("attest_management") is True


class TestExportScopes:
    """Test the scope -> flag mapping consumed by the TUI."""

    def test_scope_keys(self):
        assert set(EXPORT_SCOPES) == {"all", "all_no_enterprise", "installed"}

    def test_scope_flags(self):
        assert EXPORT_SCOPES["all"] == (False, False)
        assert EXPORT_SCOPES["all_no_enterprise"] == (False, True)
        assert EXPORT_SCOPES["installed"] == (True, False)


class TestWriteModulesCsv:
    """Test the import-compatible CSV writer."""

    def test_header_matches_rm_template(self, tmp_path):
        path = tmp_path / "out.csv"
        write_modules_csv([], path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ".id,name,installed_version,display_name"
        assert EXPORT_HEADER == (".id", "name", "installed_version", "display_name")
        assert EXPORT_FIELDS == ("id", "name", "installed_version", "display_name")

    def test_rows_written_in_order(self, tmp_path):
        path = tmp_path / "out.csv"
        records = [
            {"id": 1, "name": "base", "installed_version": "18.0.1.0", "display_name": "Base"},
            {"id": 2, "name": "sale", "installed_version": "18.0.1.2", "display_name": "Sales"},
        ]
        write_modules_csv(records, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[1] == "1,base,18.0.1.0,Base"
        assert lines[2] == "2,sale,18.0.1.2,Sales"

    def test_false_installed_version_becomes_empty(self, tmp_path):
        """Uninstalled modules report installed_version=False -> empty cell."""
        path = tmp_path / "out.csv"
        records = [{"id": 7, "name": "crm", "installed_version": False, "display_name": "CRM"}]
        write_modules_csv(records, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[1] == "7,crm,,CRM"

    def test_utf8_and_comma_quoting(self, tmp_path):
        """Umlauts survive and display names with commas are quoted."""
        path = tmp_path / "out.csv"
        records = [{"id": 3, "name": "eq_de", "installed_version": "18.0", "display_name": "Größe, Maße"}]
        write_modules_csv(records, path)
        content = path.read_text(encoding="utf-8")
        assert "Größe" in content
        assert '"Größe, Maße"' in content

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "out.csv"
        write_modules_csv([], path)
        assert path.exists()


class TestBuildExportPath:
    """Test the Downloads target-path builder."""

    def test_filename_pattern(self, tmp_path):
        when = datetime(2026, 6, 15, 16, 25, 55)
        path = build_export_path("v18_exam", "installed", when, base_dir=tmp_path)
        assert path == tmp_path / "modules_v18_exam_installed_20260615_162555.csv"

    def test_default_base_dir_is_downloads(self):
        when = datetime(2026, 6, 15, 16, 25, 55)
        path = build_export_path("v18_exam", "all", when)
        assert path.parent.name == "Downloads"

    def test_empty_db_name_fallback(self, tmp_path):
        when = datetime(2026, 6, 15, 16, 25, 55)
        path = build_export_path("", "all", when, base_dir=tmp_path)
        assert path.name == "modules_nodb_all_20260615_162555.csv"

    def test_slash_in_db_name_sanitized(self, tmp_path):
        when = datetime(2026, 6, 15, 16, 25, 55)
        path = build_export_path("a/b", "all", when, base_dir=tmp_path)
        assert path.name == "modules_a-b_all_20260615_162555.csv"

    def test_no_side_effects(self, tmp_path):
        """build_export_path must not create the directory itself."""
        target = tmp_path / "does-not-exist-yet"
        build_export_path("db", "all", datetime(2026, 1, 1), base_dir=target)
        assert not target.exists()


class TestShellExportScript:
    """Test the login-free ``odoo-bin shell`` export script and its output parser."""

    def _run(self, script, records, update_result=(0, 4)):
        """Execute the script against a fake ``env`` and capture its stdout."""
        import contextlib
        import io
        from unittest.mock import MagicMock

        model = MagicMock()
        stale = MagicMock()
        stale.__len__.return_value = 2
        model.search.return_value = stale
        model.update_list.return_value = list(update_result)
        model.search_read.return_value = records
        env = MagicMock()
        env.__getitem__.return_value = model
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(script, {"env": env})  # noqa: S102 — test executes the generated script
        return out.getvalue(), model, stale, env

    def test_installed_scope_domain_and_no_maintenance(self):
        from odoodev.core.module_export import build_shell_export_script, parse_shell_export_output

        script = build_shell_export_script(True, False, False, False)
        stdout, model, stale, env = self._run(script, [{"id": 1, "name": "base"}])
        args, kwargs = model.search_read.call_args
        assert args[0] == [("state", "=", "installed")]
        assert args[1] == list(EXPORT_FIELDS)
        assert kwargs == {"order": "name asc"}
        stale.unlink.assert_not_called()
        model.update_list.assert_not_called()
        env.cr.commit.assert_not_called()
        result = parse_shell_export_output("INFO noise\n" + stdout)
        assert result == {"records": [{"id": 1, "name": "base"}], "cleaned": None, "updated": None}

    def test_cleanup_and_update_commit(self):
        from odoodev.core.module_export import build_shell_export_script, parse_shell_export_output

        script = build_shell_export_script(False, True, True, True)
        stdout, model, stale, env = self._run(script, [])
        assert model.search_read.call_args[0][0] == [("state", "!=", "uninstallable"), ("license", "!=", "OEEL-1")]
        stale.unlink.assert_called_once()
        assert env.cr.commit.call_count == 2
        result = parse_shell_export_output(stdout)
        assert result["cleaned"] == 2
        assert result["updated"] == 4

    def test_parser_filters_test_and_hw_modules(self):
        from odoodev.core.module_export import SHELL_EXPORT_MARKER, parse_shell_export_output

        line = SHELL_EXPORT_MARKER + '{"records": [{"name": "test_x"}, {"name": "hw_drv"}, {"name": "sale"}]}'
        assert parse_shell_export_output(line)["records"] == [{"name": "sale"}]

    def test_parser_without_marker_raises(self):
        import pytest

        from odoodev.core.module_export import parse_shell_export_output

        with pytest.raises(ValueError):
            parse_shell_export_output("Traceback ...\n")

    def test_without_records_skips_listing(self):
        from odoodev.core.module_export import build_shell_export_script, parse_shell_export_output

        script = build_shell_export_script(False, False, True, False, with_records=False)
        stdout, model, stale, _env = self._run(script, [{"id": 1, "name": "base"}])
        model.search_read.assert_not_called()
        stale.unlink.assert_called_once()
        assert parse_shell_export_output(stdout) == {"records": [], "cleaned": 2, "updated": None}
