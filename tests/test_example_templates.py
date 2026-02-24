"""Tests for example template management."""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from odoodev.core.example_templates import copy_example_templates, get_example_dir
from odoodev.core.version_registry import GitConfig, PathConfig, PortConfig, VersionConfig

SUPPORTED_VERSIONS = ["16", "17", "18", "19"]


def _make_version_cfg(version: str, base: str) -> VersionConfig:
    """Create a VersionConfig pointing at a temp directory."""
    return VersionConfig(
        version=version,
        python="3.12",
        postgres="16.11-alpine",
        ports=PortConfig(db=18432, odoo=18069, gevent=18072, mailpit=18025, smtp=1025),
        paths=PathConfig(
            base=base,
            server_subdir=f"v{version}-server",
            dev_subdir=f"v{version}-dev",
            native_subdir=f"dev{version}_native",
            conf_subdir="conf",
        ),
        git=GitConfig(server_url="https://github.com/odoo/odoo.git", branch=f"{version}.0"),
    )


class TestGetExampleDir:
    """Tests for get_example_dir()."""

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_example_dir_exists(self, version: str) -> None:
        """Example directory exists for each supported version."""
        d = get_example_dir(version)
        assert d.is_dir(), f"Missing example dir for v{version}: {d}"

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_all_template_files_exist(self, version: str) -> None:
        """All three template files exist for each version."""
        d = get_example_dir(version)
        expected = ["repos.yaml", "requirements.txt", f"odoo{version}_template.conf"]
        for filename in expected:
            assert (d / filename).is_file(), f"Missing {filename} in v{version} examples"


class TestCopyExampleTemplates:
    """Tests for copy_example_templates()."""

    def test_copy_templates_to_empty_dir(self) -> None:
        """Copies all 3 files when target is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            copied = copy_example_templates("18", cfg)
            assert len(copied) == 3
            assert "repos.yaml" in copied
            assert "requirements.txt" in copied
            assert "odoo18_template.conf" in copied
            # Verify files actually exist at targets
            for target_path in copied.values():
                assert os.path.isfile(target_path)

    def test_copy_templates_skips_existing(self) -> None:
        """Does not overwrite existing files."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            # Create repos.yaml manually first
            scripts_dir = os.path.join(cfg.paths.dev_dir, "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            existing = os.path.join(scripts_dir, "repos.yaml")
            with open(existing, "w") as f:
                f.write("# custom content\n")

            copied = copy_example_templates("18", cfg)
            # repos.yaml should NOT be in copied (it already existed)
            assert "repos.yaml" not in copied
            # But other two should be copied
            assert "requirements.txt" in copied
            assert "odoo18_template.conf" in copied
            # Verify existing file was not overwritten
            with open(existing) as f:
                assert f.read() == "# custom content\n"

    def test_copy_creates_subdirectories(self) -> None:
        """Creates scripts/ and conf/ directories if missing."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            scripts_dir = os.path.join(cfg.paths.dev_dir, "scripts")
            conf_dir = cfg.paths.conf_dir
            assert not os.path.exists(scripts_dir)
            assert not os.path.exists(conf_dir)

            copy_example_templates("18", cfg)
            assert os.path.isdir(scripts_dir)
            assert os.path.isdir(conf_dir)

    def test_nonexistent_version_returns_empty(self) -> None:
        """Returns empty dict for a version without example templates."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("99", tmp)
            copied = copy_example_templates("99", cfg)
            assert copied == {}


class TestTemplateContent:
    """Tests for template file content validity."""

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_repos_yaml_valid(self, version: str) -> None:
        """repos.yaml is valid YAML with expected keys."""
        d = get_example_dir(version)
        with open(d / "repos.yaml") as f:
            data = yaml.safe_load(f)
        assert data["version"] == version
        assert "branch" in data
        assert "paths" in data
        assert "base_addons" in data
        assert "server" in data
        assert "addons" in data

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_requirements_txt_not_empty(self, version: str) -> None:
        """requirements.txt is not empty and contains key packages."""
        d = get_example_dir(version)
        content = (d / "requirements.txt").read_text()
        assert len(content) > 100
        # Key packages expected in all versions
        assert "psycopg2-binary" in content
        assert "Werkzeug" in content
        assert "lxml" in content
        assert "Pillow" in content

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_requirements_no_plain_psycopg2(self, version: str) -> None:
        """requirements.txt uses psycopg2-binary, not plain psycopg2."""
        d = get_example_dir(version)
        content = (d / "requirements.txt").read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if "psycopg2" in stripped and "psycopg2-binary" not in stripped:
                pytest.fail(f"Found plain psycopg2 in v{version}: {stripped}")

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_odoo_template_conf_exists_and_valid(self, version: str) -> None:
        """odoo_template.conf exists and contains expected sections."""
        d = get_example_dir(version)
        conf_file = d / f"odoo{version}_template.conf"
        content = conf_file.read_text()
        assert "[options]" in content
        assert "addons_path" in content
        assert "db_host" in content
        assert "db_user = odoo" in content
        assert "admin_passwd = admin" in content

    def test_v19_has_new_fields(self) -> None:
        """v19 config contains v19-specific fields."""
        d = get_example_dir("19")
        content = (d / "odoo19_template.conf").read_text()
        assert "bin_path" in content
        assert "db_app_name" in content
        assert "limit_time_worker_cron" in content
        assert "pre_upgrade_scripts" in content
        assert "proxy_access_token" in content
        assert "server_wide_modules = base,rpc,web" in content

    def test_v19_repos_yaml_uses_master_branch(self) -> None:
        """v19 repos.yaml uses 'master' branch (Odoo convention for dev)."""
        d = get_example_dir("19")
        with open(d / "repos.yaml") as f:
            data = yaml.safe_load(f)
        assert data["branch"] == "master"
