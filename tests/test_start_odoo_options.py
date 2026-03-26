"""Tests for explicit Odoo options (-d, -u, -i) on the start command."""

from __future__ import annotations

from click.testing import CliRunner

import odoodev.cli  # noqa: F401
from odoodev.commands.start import _build_odoo_extra_args, start


class TestBuildOdooExtraArgs:
    """Unit tests for _build_odoo_extra_args helper."""

    def test_no_options(self):
        result = _build_odoo_extra_args(None, None, None, ())
        assert result == ()

    def test_database_only(self):
        result = _build_odoo_extra_args("v18_exam", None, None, ())
        assert result == ("-d", "v18_exam")

    def test_update_only(self):
        result = _build_odoo_extra_args(None, "all", None, ())
        assert result == ("-u", "all")

    def test_init_only(self):
        result = _build_odoo_extra_args(None, None, "eq_sale", ())
        assert result == ("-i", "eq_sale")

    def test_all_options(self):
        result = _build_odoo_extra_args("v18_exam", "eq_sale,eq_stock", "eq_new", ())
        assert result == ("-d", "v18_exam", "-u", "eq_sale,eq_stock", "-i", "eq_new")

    def test_preserves_existing_extra_args(self):
        result = _build_odoo_extra_args("v18_exam", None, None, ("--workers=4",))
        assert result == ("--workers=4", "-d", "v18_exam")

    def test_merges_with_extra_args(self):
        result = _build_odoo_extra_args("v18_exam", "all", None, ("--log-level=debug",))
        assert result == ("--log-level=debug", "-d", "v18_exam", "-u", "all")

    def test_empty_strings_ignored(self):
        """Empty string values should not be treated as options."""
        result = _build_odoo_extra_args("", None, None, ())
        assert result == ()

    def test_u_flag_present_for_i18n_check(self):
        """When update is set, '-u' must be in result for i18n logic."""
        result = _build_odoo_extra_args(None, "custom_module", None, ())
        assert "-u" in result


class TestStartCommandCliParsing:
    """Test that Click parses -d, -u, -i correctly on the start command."""

    def test_help_shows_database_option(self):
        runner = CliRunner()
        result = runner.invoke(start, ["--help"])
        assert "-d, --database" in result.output
        assert "-u, --update" in result.output
        assert "-i, --init" in result.output

    def test_help_shows_odoo_examples(self):
        runner = CliRunner()
        result = runner.invoke(start, ["--help"])
        assert "-d v18_exam -u eq_sale" in result.output

    def test_d_flag_not_rejected(self):
        """Click must not reject -d as unknown option."""
        runner = CliRunner()
        result = runner.invoke(start, ["18", "-d", "v18_exam"])
        assert "No such option: -d" not in (result.output or "")

    def test_u_flag_not_rejected(self):
        """Click must not reject -u as unknown option."""
        runner = CliRunner()
        result = runner.invoke(start, ["18", "-u", "all"])
        assert "No such option: -u" not in (result.output or "")

    def test_i_flag_not_rejected(self):
        """Click must not reject -i as unknown option."""
        runner = CliRunner()
        result = runner.invoke(start, ["18", "-i", "eq_sale"])
        assert "No such option: -i" not in (result.output or "")

    def test_combined_flags_not_rejected(self):
        """Click must not reject combined -d -u flags."""
        runner = CliRunner()
        result = runner.invoke(start, ["18", "--dev", "-d", "v18_exam", "-u", "all"])
        assert "No such option" not in (result.output or "")

    def test_typo_in_odoodev_flag_rejected(self):
        """Typos in odoodev's own flags must still be caught by Click."""
        runner = CliRunner()
        result = runner.invoke(start, ["18", "--tiu"])
        assert result.exit_code != 0
        assert "No such option: --tiu" in result.output
