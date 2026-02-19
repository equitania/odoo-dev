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
        assert "repos" in result.output
        assert "db" in result.output
        assert "init" in result.output
        assert "config" in result.output
