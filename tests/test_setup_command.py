"""Tests for setup command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.global_config import (
    DEFAULT_BASE_DIR,
    DEFAULT_DB_USER,
    GlobalConfig,
    clear_config_cache,
    load_global_config,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear config cache before and after each test."""
    clear_config_cache()
    yield
    clear_config_cache()


@pytest.fixture()
def config_dir(tmp_dir, monkeypatch):
    """Redirect config path to a temp directory."""
    config_path = Path(tmp_dir) / ".config" / "odoodev" / "config.yaml"
    monkeypatch.setattr(
        "odoodev.core.global_config.get_config_path",
        lambda: config_path,
    )
    return config_path


class TestSetupNonInteractive:
    """Test non-interactive setup."""

    def test_creates_default_config(self, config_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--non-interactive"])
        assert result.exit_code == 0
        assert "Default configuration saved" in result.output
        assert config_dir.is_file()

    def test_non_interactive_skips_if_exists(self, config_dir):
        """Second run with --non-interactive should not overwrite."""
        runner = CliRunner()
        runner.invoke(cli, ["setup", "--non-interactive"])
        result = runner.invoke(cli, ["setup", "--non-interactive"])
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_default_values_saved(self, config_dir):
        runner = CliRunner()
        runner.invoke(cli, ["setup", "--non-interactive"])
        clear_config_cache()
        cfg = load_global_config()
        assert cfg.base_dir == DEFAULT_BASE_DIR
        assert cfg.database.user == DEFAULT_DB_USER


class TestSetupReset:
    """Test --reset flag."""

    def test_reset_creates_default_config(self, config_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--reset"])
        assert result.exit_code == 0
        assert "reset to defaults" in result.output
        assert config_dir.is_file()

    def test_reset_overwrites_existing(self, config_dir):
        """--reset should overwrite existing custom config."""
        from odoodev.core.global_config import DatabaseConfig, save_global_config

        custom = GlobalConfig(
            base_dir="~/custom",
            database=DatabaseConfig(user="custom", password="custom"),
        )
        save_global_config(custom)
        clear_config_cache()

        runner = CliRunner()
        runner.invoke(cli, ["setup", "--reset"])
        clear_config_cache()

        cfg = load_global_config()
        assert cfg.base_dir == DEFAULT_BASE_DIR
        assert cfg.database.user == DEFAULT_DB_USER


class TestSetupHelp:
    """Test setup help output."""

    def test_setup_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "setup" in result.output

    def test_setup_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "--non-interactive" in result.output
        assert "--reset" in result.output


class TestFirstRunHint:
    """Test first-run hint in CLI."""

    def test_hint_shown_when_no_config(self, config_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "versions"])
        assert "No configuration found" in result.output

    def test_no_hint_for_setup_command(self, config_dir):
        """setup command itself should not show the hint."""
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--non-interactive"])
        # The hint should not appear before the setup output
        lines = result.output.strip().split("\n")
        # First meaningful line should not be the hint
        assert not any("No configuration found" in line for line in lines)

    def test_no_hint_when_config_exists(self, config_dir):
        """After setup, hint should not appear."""
        runner = CliRunner()
        runner.invoke(cli, ["setup", "--non-interactive"])
        clear_config_cache()
        result = runner.invoke(cli, ["config", "versions"])
        assert "No configuration found" not in result.output
