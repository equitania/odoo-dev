"""Tests for example template management."""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from odoodev.core.example_templates import copy_example_templates, get_example_dir, replace_example_template
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
        expected = ["repos.yaml", "requirements.txt", "postgresql.conf", f"odoo{version}_template.conf"]
        for filename in expected:
            assert (d / filename).is_file(), f"Missing {filename} in v{version} examples"


class TestCopyExampleTemplates:
    """Tests for copy_example_templates()."""

    def test_copy_templates_to_empty_dir(self) -> None:
        """Copies all 3 files when target is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            copied, outdated = copy_example_templates("18", cfg)
            assert len(copied) == 4
            assert "repos.yaml" in copied
            assert "requirements.txt" in copied
            assert "postgresql.conf" in copied
            assert "odoo18_template.conf" in copied
            assert len(outdated) == 0
            # Verify files actually exist at targets
            for target_path in copied.values():
                assert os.path.isfile(target_path)

    def test_copy_templates_skips_existing(self) -> None:
        """Does not overwrite existing files, detects outdated ones."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            # Create repos.yaml manually first (now in native_dir)
            native_dir = cfg.paths.native_dir
            os.makedirs(native_dir, exist_ok=True)
            existing = os.path.join(native_dir, "repos.yaml")
            with open(existing, "w") as f:
                f.write("# custom content\n")

            copied, outdated = copy_example_templates("18", cfg)
            # repos.yaml should NOT be in copied (it already existed)
            assert "repos.yaml" not in copied
            # But repos.yaml should be in outdated (content differs)
            assert "repos.yaml" in outdated
            # Other three should be copied
            assert "requirements.txt" in copied
            assert "postgresql.conf" in copied
            assert "odoo18_template.conf" in copied
            # Verify existing file was not overwritten
            with open(existing) as f:
                assert f.read() == "# custom content\n"

    def test_copy_creates_subdirectories(self) -> None:
        """Creates native_dir/ and conf/ directories if missing."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            native_dir = cfg.paths.native_dir
            conf_dir = cfg.paths.conf_dir
            assert not os.path.exists(native_dir)
            assert not os.path.exists(conf_dir)

            copy_example_templates("18", cfg)
            assert os.path.isdir(native_dir)
            assert os.path.isdir(conf_dir)

    def test_nonexistent_version_returns_empty(self) -> None:
        """Returns empty tuples for a version without example templates."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("99", tmp)
            copied, outdated = copy_example_templates("99", cfg)
            assert copied == {}
            assert outdated == {}

    def test_identical_file_not_in_outdated(self) -> None:
        """Identical existing file appears in neither copied nor outdated."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            # First copy: populate targets
            copy_example_templates("18", cfg)
            # Second call: all files exist and are identical
            copied, outdated = copy_example_templates("18", cfg)
            assert len(copied) == 0
            assert len(outdated) == 0

    def test_outdated_detection_modified_content(self) -> None:
        """Modified file is detected as outdated."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            # First copy: populate targets
            copy_example_templates("18", cfg)
            # Modify one file
            target = os.path.join(cfg.paths.native_dir, "repos.yaml")
            with open(target, "w") as f:
                f.write("# modified by user\n")

            copied, outdated = copy_example_templates("18", cfg)
            assert len(copied) == 0
            assert "repos.yaml" in outdated
            # Unmodified files should not be outdated
            assert "requirements.txt" not in outdated
            assert "odoo18_template.conf" not in outdated


class TestReplaceExampleTemplate:
    """Tests for replace_example_template()."""

    def test_replace_overwrites_existing(self) -> None:
        """replace_example_template overwrites the target file."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            # First copy: populate targets
            copy_example_templates("18", cfg)
            target = os.path.join(cfg.paths.native_dir, "repos.yaml")
            # Modify the file
            with open(target, "w") as f:
                f.write("# user modified\n")

            result = replace_example_template("18", cfg, "repos.yaml")
            assert result == target
            # Content should now match bundled version
            bundled = get_example_dir("18") / "repos.yaml"
            with open(target) as f:
                actual = f.read()
            with open(bundled) as f:
                expected = f.read()
            assert actual == expected

    def test_replace_nonexistent_template_returns_none(self) -> None:
        """Returns None for a template that does not exist in bundled data."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("18", tmp)
            result = replace_example_template("18", cfg, "nonexistent.txt")
            assert result is None

    def test_replace_invalid_version_returns_none(self) -> None:
        """Returns None for a version without example templates."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_version_cfg("99", tmp)
            result = replace_example_template("99", cfg, "repos.yaml")
            assert result is None


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
        assert "db_user = ownerp" in content
        assert "admin_passwd = CHANGE_AT_FIRST" in content

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

    @pytest.mark.parametrize("version", SUPPORTED_VERSIONS)
    def test_postgresql_conf_valid(self, version: str) -> None:
        """postgresql.conf contains expected optimization parameters."""
        d = get_example_dir(version)
        content = (d / "postgresql.conf").read_text()
        assert "shared_buffers" in content
        assert "work_mem" in content
        assert "effective_cache_size" in content
        assert "wal_compression" in content
        assert "autovacuum" in content

    def test_v19_postgresql_conf_pg17(self) -> None:
        """v19 postgresql.conf references PostgreSQL 17."""
        d = get_example_dir("19")
        content = (d / "postgresql.conf").read_text()
        assert "PostgreSQL 17" in content

    @pytest.mark.parametrize("version", ["16", "17", "18"])
    def test_v16_v18_postgresql_conf_pg16(self, version: str) -> None:
        """v16-v18 postgresql.conf references PostgreSQL 16."""
        d = get_example_dir(version)
        content = (d / "postgresql.conf").read_text()
        assert "PostgreSQL 16" in content
