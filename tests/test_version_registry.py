"""Tests for version registry module."""

import os
from pathlib import Path

import pytest

from odoodev.core.version_registry import (
    VersionConfig,
    available_versions,
    detect_version_from_cwd,
    get_version,
    load_versions,
)


class TestLoadVersions:
    """Test loading versions from bundled YAML."""

    def test_load_bundled_versions(self):
        """Load versions from the bundled versions.yaml."""
        versions = load_versions()
        assert isinstance(versions, dict)
        assert len(versions) >= 4  # v16, v17, v18, v19

    def test_version_16_exists(self):
        versions = load_versions()
        assert "16" in versions

    def test_version_18_exists(self):
        versions = load_versions()
        assert "18" in versions

    def test_version_19_exists(self):
        versions = load_versions()
        assert "19" in versions

    def test_version_config_type(self):
        versions = load_versions()
        for ver, cfg in versions.items():
            assert isinstance(cfg, VersionConfig)
            assert cfg.version == ver

    def test_version_18_config(self):
        versions = load_versions()
        v18 = versions["18"]
        assert v18.python == "3.12"
        assert v18.postgres == "16.11-alpine"
        assert v18.ports.db == 18432
        assert v18.ports.odoo == 18069
        assert v18.ports.gevent == 18072
        assert v18.paths.server_subdir == "v18-server"
        assert v18.git.branch == "develop"

    def test_version_19_python(self):
        versions = load_versions()
        v19 = versions["19"]
        assert v19.python == "3.13"
        assert v19.postgres == "17.4-alpine"

    def test_user_override(self, tmp_dir):
        """Test loading user override file."""
        import yaml

        override_data = {
            "versions": {
                "20": {
                    "python": "3.14",
                    "postgres": "18.0-alpine",
                    "ports": {"db": 20432, "odoo": 20069, "gevent": 20072, "mailpit": 20025, "smtp": 2025},
                    "paths": {
                        "base": "~/gitbase/v20",
                        "server_subdir": "v20-server",
                        "dev_subdir": "v20-dev",
                        "native_subdir": "dev20_native",
                        "conf_subdir": "conf",
                    },
                    "git": {
                        "server_url": "git@example.com:v20/v20-server.git",
                        "branch": "develop",
                    },
                }
            }
        }
        override_path = Path(tmp_dir) / "override.yaml"
        with open(override_path, "w") as f:
            yaml.dump(override_data, f)

        versions = load_versions(override_path=override_path)
        assert "20" in versions
        assert versions["20"].python == "3.14"


class TestGetVersion:
    """Test getting a specific version."""

    def test_get_existing(self):
        cfg = get_version("18")
        assert cfg.version == "18"

    def test_get_nonexistent(self):
        with pytest.raises(KeyError, match="Unknown Odoo version"):
            get_version("99")


class TestVersionConfig:
    """Test VersionConfig properties."""

    def test_env_name(self):
        cfg = get_version("18")
        assert cfg.env_name == "dev18_native"

    def test_version_prefix(self):
        cfg = get_version("18")
        assert cfg.version_prefix == "v18"

    def test_paths_expanded(self):
        cfg = get_version("18")
        assert "~" not in cfg.paths.base_expanded
        assert os.path.expanduser("~") in cfg.paths.base_expanded

    def test_server_dir(self):
        cfg = get_version("18")
        assert cfg.paths.server_dir.endswith("v18-server")

    def test_native_dir(self):
        cfg = get_version("18")
        assert cfg.paths.native_dir.endswith("dev18_native")


class TestDetectVersion:
    """Test auto-detection of version from CWD."""

    def test_detect_from_v18_path(self, monkeypatch, tmp_dir):
        home = os.path.expanduser("~")
        v18_dir = os.path.join(home, "gitbase", "v18", "something")
        os.makedirs(v18_dir, exist_ok=True)
        monkeypatch.chdir(v18_dir)
        result = detect_version_from_cwd()
        assert result == "18"

    def test_detect_from_non_version_path(self, monkeypatch, tmp_dir):
        monkeypatch.chdir(tmp_dir)
        result = detect_version_from_cwd()
        assert result is None


class TestAvailableVersions:
    """Test available versions listing."""

    def test_returns_sorted_list(self):
        versions = available_versions()
        assert isinstance(versions, list)
        assert versions == sorted(versions)
        assert "18" in versions


class TestApplyGlobalBaseDir:
    """Test that global config base_dir rebases version paths."""

    def test_custom_base_dir_rebases_paths(self, monkeypatch):
        """When global config has custom base_dir, default paths are rebased."""
        from odoodev.core.global_config import GlobalConfig, clear_config_cache

        clear_config_cache()
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: GlobalConfig(base_dir="~/projects/odoo"),
        )

        versions = load_versions()
        v18 = versions["18"]
        assert "projects/odoo/v18" in v18.paths.base
        assert v18.paths.base.startswith("~/projects/odoo/")
        clear_config_cache()

    def test_default_base_dir_no_change(self, monkeypatch):
        """When global config uses default base_dir, paths stay unchanged."""
        from odoodev.core.global_config import GlobalConfig, clear_config_cache

        clear_config_cache()
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: GlobalConfig(base_dir="~/gitbase"),
        )

        versions = load_versions()
        v18 = versions["18"]
        assert v18.paths.base == "~/gitbase/v18"
        clear_config_cache()

    def test_overridden_version_not_rebased(self, tmp_dir, monkeypatch):
        """Versions with explicit path overrides should not be rebased."""
        import yaml

        from odoodev.core.global_config import GlobalConfig, clear_config_cache

        clear_config_cache()
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: GlobalConfig(base_dir="~/projects/odoo"),
        )

        # Create override that sets explicit path for v18
        override_data = {
            "versions": {
                "18": {
                    "python": "3.12",
                    "postgres": "16.11-alpine",
                    "ports": {"db": 18432, "odoo": 18069, "gevent": 18072, "mailpit": 18025, "smtp": 1025},
                    "paths": {
                        "base": "~/custom/v18",
                        "server_subdir": "v18-server",
                        "dev_subdir": "v18-dev",
                        "native_subdir": "dev18_native",
                        "conf_subdir": "conf",
                    },
                    "git": {
                        "server_url": "git@example.com:v18/v18-server.git",
                        "branch": "develop",
                    },
                }
            }
        }
        override_path = Path(tmp_dir) / "override.yaml"
        with open(override_path, "w") as f:
            yaml.dump(override_data, f)

        versions = load_versions(override_path=override_path)
        v18 = versions["18"]
        # Should keep the explicit override, not rebase
        assert v18.paths.base == "~/custom/v18"
        clear_config_cache()

    def test_detect_version_uses_custom_base_dir(self, monkeypatch, tmp_dir):
        """detect_version_from_cwd should use base_dir from global config."""
        from odoodev.core.global_config import GlobalConfig, clear_config_cache

        clear_config_cache()

        # Use realpath to resolve macOS /private/var symlinks
        real_tmp = os.path.realpath(tmp_dir)
        custom_base = os.path.join(real_tmp, "projects")
        v18_dir = os.path.join(custom_base, "v18", "something")
        os.makedirs(v18_dir, exist_ok=True)
        monkeypatch.chdir(v18_dir)

        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: GlobalConfig(base_dir=custom_base),
        )

        result = detect_version_from_cwd()
        assert result == "18"
        clear_config_cache()
