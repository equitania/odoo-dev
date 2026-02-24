"""Tests for global configuration module."""

import os
from pathlib import Path

import pytest
import yaml

from odoodev.core.global_config import (
    DEFAULT_ACTIVE_VERSIONS,
    DEFAULT_BASE_DIR,
    DEFAULT_DB_PASSWORD,
    DEFAULT_DB_USER,
    DatabaseConfig,
    GlobalConfig,
    clear_config_cache,
    config_exists,
    load_global_config,
    save_global_config,
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


class TestGlobalConfigDefaults:
    """Test default values."""

    def test_default_base_dir(self):
        cfg = GlobalConfig()
        assert cfg.base_dir == DEFAULT_BASE_DIR

    def test_default_database(self):
        cfg = GlobalConfig()
        assert cfg.database.user == DEFAULT_DB_USER
        assert cfg.database.password == DEFAULT_DB_PASSWORD

    def test_default_active_versions(self):
        cfg = GlobalConfig()
        assert cfg.active_versions == list(DEFAULT_ACTIVE_VERSIONS)

    def test_base_dir_expanded(self):
        cfg = GlobalConfig(base_dir="~/projects")
        assert "~" not in cfg.base_dir_expanded
        assert cfg.base_dir_expanded == os.path.expanduser("~/projects")

    def test_frozen_dataclass(self):
        cfg = GlobalConfig()
        with pytest.raises(AttributeError):
            cfg.base_dir = "/other"  # type: ignore[misc]


class TestConfigExists:
    """Test config_exists function."""

    def test_no_config(self, config_dir):
        assert config_exists() is False

    def test_config_present(self, config_dir):
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        config_dir.write_text("base_dir: ~/test\n")
        assert config_exists() is True


class TestLoadGlobalConfig:
    """Test loading global configuration."""

    def test_load_defaults_when_no_file(self, config_dir):
        cfg = load_global_config()
        assert cfg.base_dir == DEFAULT_BASE_DIR
        assert cfg.database.user == DEFAULT_DB_USER

    def test_load_from_file(self, config_dir):
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "base_dir": "~/projects/odoo",
            "database": {"user": "admin", "password": "secret"},
            "active_versions": ["18", "19"],
        }
        with open(config_dir, "w") as f:
            yaml.dump(data, f)

        cfg = load_global_config()
        assert cfg.base_dir == "~/projects/odoo"
        assert cfg.database.user == "admin"
        assert cfg.database.password == "secret"
        assert cfg.active_versions == ["18", "19"]

    def test_load_partial_config(self, config_dir):
        """Missing keys should use defaults."""
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        data = {"base_dir": "~/custom"}
        with open(config_dir, "w") as f:
            yaml.dump(data, f)

        cfg = load_global_config()
        assert cfg.base_dir == "~/custom"
        assert cfg.database.user == DEFAULT_DB_USER
        assert cfg.active_versions == list(DEFAULT_ACTIVE_VERSIONS)

    def test_load_empty_file(self, config_dir):
        """Empty YAML file should return defaults."""
        config_dir.parent.mkdir(parents=True, exist_ok=True)
        config_dir.write_text("")

        cfg = load_global_config()
        assert cfg.base_dir == DEFAULT_BASE_DIR

    def test_caching(self, config_dir):
        """Second call returns cached instance."""
        cfg1 = load_global_config()
        cfg2 = load_global_config()
        assert cfg1 is cfg2


class TestSaveGlobalConfig:
    """Test saving global configuration."""

    def test_save_creates_file(self, config_dir):
        cfg = GlobalConfig(base_dir="~/projects/odoo")
        path = save_global_config(cfg)
        assert path.is_file()

    def test_save_creates_directories(self, config_dir):
        cfg = GlobalConfig()
        save_global_config(cfg)
        assert config_dir.parent.is_dir()

    def test_roundtrip(self, config_dir):
        """Save then load should return equivalent config."""
        original = GlobalConfig(
            base_dir="~/my-odoo",
            database=DatabaseConfig(user="testuser", password="testpass"),
            active_versions=["18"],
        )
        save_global_config(original)
        clear_config_cache()
        loaded = load_global_config()

        assert loaded.base_dir == original.base_dir
        assert loaded.database.user == original.database.user
        assert loaded.database.password == original.database.password
        assert loaded.active_versions == original.active_versions

    def test_save_updates_cache(self, config_dir):
        cfg = GlobalConfig(base_dir="~/cached-test")
        save_global_config(cfg)
        loaded = load_global_config()
        assert loaded.base_dir == "~/cached-test"

    def test_saved_yaml_has_comment(self, config_dir):
        """Saved file starts with a comment header."""
        save_global_config(GlobalConfig())
        content = config_dir.read_text()
        assert content.startswith("# Generated by: odoodev setup")
