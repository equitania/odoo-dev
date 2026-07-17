"""Tests for CLI config commands."""

from click.testing import CliRunner

from odoodev.cli import cli


class TestConfigVersions:
    def test_versions_command(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "versions"])
        assert result.exit_code == 0
        assert "v18" in result.output
        assert "v16" in result.output
        assert "v19" in result.output

    def test_config_show(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show"])
        assert result.exit_code == 0


class TestVersion:
    def test_version_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "odoodev" in result.output


class TestHelp:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "repos" in result.output
        assert "db" in result.output
        assert "init" in result.output
        assert "config" in result.output


class TestYesFlagUnification:
    """All confirmation-skipping flags expose -y as short form."""

    def test_db_drop_has_short_y(self):
        from odoodev.commands.db import db_drop

        opt = next(p for p in db_drop.params if p.name == "yes")
        assert "-y" in opt.opts

    def test_migrate_remove_has_short_y(self):
        from odoodev.commands.migrate import migrate_remove

        opt = next(p for p in migrate_remove.params if p.name == "yes")
        assert "-y" in opt.opts

    def test_venv_remove_has_short_y(self):
        from odoodev.commands.venv import venv_remove

        opt = next(p for p in venv_remove.params if p.name == "yes")
        assert "-y" in opt.opts

    def test_start_accepts_yes_alias(self):
        from odoodev.commands.start import start

        opt = next(p for p in start.params if p.name == "yes_flag")
        assert "-y" in opt.opts and "--yes" in opt.opts
        # Documented (un-hidden) since v0.59.0 — it is the primary skip flag.
        assert opt.hidden is False
