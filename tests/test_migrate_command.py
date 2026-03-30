"""Tests for odoodev migrate CLI command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.migration_config import clear_migration_cache


@pytest.fixture(autouse=True)
def clean_cache():
    """Clear migration config cache before and after each test."""
    clear_migration_cache()
    yield
    clear_migration_cache()


@pytest.fixture
def migration_dir(tmp_dir, monkeypatch):
    """Set up temporary migration config directory."""
    config_dir = Path(tmp_dir) / ".config" / "odoodev"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "odoodev.core.migration_config.get_migration_config_path",
        lambda: config_dir / "migration.yaml",
    )
    # Also create a filestore base dir for tests
    (Path(tmp_dir) / "odoo-share" / "migration").mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_versions(versions_yaml, monkeypatch):
    """Mock load_versions to use test versions.yaml."""
    from odoodev.core.version_registry import load_versions

    def _mock_load():
        return load_versions(override_path=versions_yaml)

    monkeypatch.setattr("odoodev.commands.migrate.load_versions", _mock_load)


class TestMigrateCreate:
    """Tests for odoodev migrate create."""

    def test_create_basic(self, runner, migration_dir, mock_versions, tmp_dir):
        result = runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        assert result.exit_code == 0
        assert "18-to-19" in result.output
        assert "created" in result.output.lower()

    def test_create_with_custom_name(self, runner, migration_dir, mock_versions, tmp_dir):
        result = runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19", "--name", "my-test"])
        assert result.exit_code == 0
        assert "my-test" in result.output

    def test_create_same_version_fails(self, runner, migration_dir, mock_versions):
        result = runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "18"])
        assert result.exit_code != 0
        assert "different" in result.output.lower()

    def test_create_invalid_version_fails(self, runner, migration_dir, mock_versions):
        result = runner.invoke(cli, ["migrate", "create", "--from", "99", "--to", "18"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_create_duplicate_fails(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_create_pg_version_warning(self, runner, migration_dir, mock_versions, tmp_dir):
        """v18 uses pg 16.11, v19 uses pg 17.4 — should warn."""
        result = runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        assert result.exit_code == 0
        assert "conflict" in result.output.lower() or "WARN" in result.output


class TestMigrateActivate:
    """Tests for odoodev migrate activate."""

    def test_activate(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "activate", "18-to-19"])
        assert result.exit_code == 0
        assert "activated" in result.output.lower()

    def test_activate_nonexistent_fails(self, runner, migration_dir, mock_versions):
        result = runner.invoke(cli, ["migrate", "activate", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestMigrateDeactivate:
    """Tests for odoodev migrate deactivate."""

    def test_deactivate(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        runner.invoke(cli, ["migrate", "activate", "18-to-19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "deactivate"])
        assert result.exit_code == 0
        assert "deactivated" in result.output.lower()

    def test_deactivate_when_none_active(self, runner, migration_dir):
        result = runner.invoke(cli, ["migrate", "deactivate"])
        assert result.exit_code == 0
        assert "no migration" in result.output.lower()


class TestMigrateStatus:
    """Tests for odoodev migrate status."""

    def test_status_no_active(self, runner, migration_dir):
        result = runner.invoke(cli, ["migrate", "status"])
        assert result.exit_code == 0
        assert "no migration" in result.output.lower()

    def test_status_with_active(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        runner.invoke(cli, ["migrate", "activate", "18-to-19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "status"])
        assert result.exit_code == 0
        assert "18-to-19" in result.output
        assert "ACTIVE" in result.output


class TestMigrateList:
    """Tests for odoodev migrate list."""

    def test_list_empty(self, runner, migration_dir):
        result = runner.invoke(cli, ["migrate", "list"])
        assert result.exit_code == 0
        assert "no migration" in result.output.lower()

    def test_list_with_groups(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "list"])
        assert result.exit_code == 0
        assert "18-to-19" in result.output


class TestMigrateRemove:
    """Tests for odoodev migrate remove."""

    def test_remove(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "remove", "18-to-19"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

    def test_remove_nonexistent_fails(self, runner, migration_dir):
        result = runner.invoke(cli, ["migrate", "remove", "nonexistent"])
        assert result.exit_code != 0

    def test_remove_active_without_yes_fails(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        runner.invoke(cli, ["migrate", "activate", "18-to-19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "remove", "18-to-19"])
        assert result.exit_code != 0
        assert "active" in result.output.lower()

    def test_remove_active_with_yes(self, runner, migration_dir, mock_versions, tmp_dir):
        runner.invoke(cli, ["migrate", "create", "--from", "18", "--to", "19"])
        clear_migration_cache()
        runner.invoke(cli, ["migrate", "activate", "18-to-19"])
        clear_migration_cache()
        result = runner.invoke(cli, ["migrate", "remove", "18-to-19", "--yes"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()


class TestMigrateHelp:
    """Tests for help output."""

    def test_migrate_help(self, runner):
        result = runner.invoke(cli, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "migration" in result.output.lower()

    def test_migrate_create_help(self, runner):
        result = runner.invoke(cli, ["migrate", "create", "--help"])
        assert result.exit_code == 0
        assert "--from" in result.output
        assert "--to" in result.output
