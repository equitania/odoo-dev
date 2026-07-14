"""Tests for `odoodev config paths` and its path-resolution helpers."""

from __future__ import annotations

import json
import os

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.commands.config import _version_paths
from odoodev.core.odoo_config import latest_generated_conf, resolve_config_paths
from odoodev.core.version_registry import GitConfig, PathConfig, PortConfig, VersionConfig

ROLES = ("env", "compose", "requirements", "repos_yaml", "postgresql_conf", "template_conf", "generated_conf")


def _make_version_cfg(version: str, base: str) -> VersionConfig:
    """Create a VersionConfig pointing at a temp directory."""
    return VersionConfig(
        version=version,
        python="3.13",
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


class TestResolveConfigPaths:
    def test_defaults_without_repos_config(self, tmp_dir):
        cfg = _make_version_cfg("18", tmp_dir)
        template, config_dir = resolve_config_paths(cfg, None)
        assert template == os.path.join(cfg.paths.conf_dir, "odoo18_template.conf")
        assert config_dir == cfg.paths.myconfs_dir

    def test_repos_yaml_overrides(self, tmp_dir):
        cfg = _make_version_cfg("18", tmp_dir)
        repos_config = {"paths": {"template": "~/custom/tpl.conf", "config_dir": "~/custom/confs"}}
        template, config_dir = resolve_config_paths(cfg, repos_config)
        assert template == os.path.expanduser("~/custom/tpl.conf")
        assert config_dir == os.path.expanduser("~/custom/confs")

    def test_empty_paths_section(self, tmp_dir):
        cfg = _make_version_cfg("18", tmp_dir)
        template, config_dir = resolve_config_paths(cfg, {"paths": None})
        assert template.endswith("odoo18_template.conf")
        assert config_dir == cfg.paths.myconfs_dir


class TestLatestGeneratedConf:
    def test_missing_dir(self, tmp_dir):
        assert latest_generated_conf(os.path.join(tmp_dir, "nope")) is None

    def test_empty_dir(self, tmp_dir):
        assert latest_generated_conf(tmp_dir) is None

    def test_latest_wins(self, tmp_dir):
        for name in ("odoo_250101.conf", "odoo_260714.conf", "odoo_251231.conf"):
            open(os.path.join(tmp_dir, name), "w").close()
        assert latest_generated_conf(tmp_dir) == os.path.join(tmp_dir, "odoo_260714.conf")

    def test_ignores_non_matching_names(self, tmp_dir):
        for name in ("odoo18_template.conf", "odoo_9999999.conf", "notes.txt", "odoo_123456.conf.bak"):
            open(os.path.join(tmp_dir, name), "w").close()
        assert latest_generated_conf(tmp_dir) is None


class TestVersionPaths:
    def test_inventory_shape_and_exists_flags(self, tmp_dir):
        cfg = _make_version_cfg("18", tmp_dir)
        native_dir = cfg.paths.native_dir
        os.makedirs(native_dir)
        open(os.path.join(native_dir, ".env"), "w").close()
        open(os.path.join(native_dir, "requirements.txt"), "w").close()

        data = _version_paths("18", cfg)

        assert data["native_dir"] == native_dir
        assert data["conf_dir"] == cfg.paths.conf_dir
        assert data["myconfs_dir"] == cfg.paths.myconfs_dir
        assert set(data["files"].keys()) == set(ROLES)
        assert data["files"]["env"] == {"path": os.path.join(native_dir, ".env"), "exists": True}
        assert data["files"]["requirements"]["exists"] is True
        assert data["files"]["compose"]["exists"] is False
        assert data["files"]["template_conf"]["path"] == os.path.join(cfg.paths.conf_dir, "odoo18_template.conf")
        assert data["files"]["generated_conf"] is None

    def test_generated_conf_latest(self, tmp_dir):
        cfg = _make_version_cfg("18", tmp_dir)
        os.makedirs(cfg.paths.myconfs_dir)
        for name in ("odoo_250101.conf", "odoo_260714.conf"):
            open(os.path.join(cfg.paths.myconfs_dir, name), "w").close()

        data = _version_paths("18", cfg)
        entry = data["files"]["generated_conf"]
        assert entry == {"path": os.path.join(cfg.paths.myconfs_dir, "odoo_260714.conf"), "exists": True}

    def test_repos_yaml_override_reflected(self, tmp_dir):
        cfg = _make_version_cfg("18", tmp_dir)
        native_dir = cfg.paths.native_dir
        os.makedirs(native_dir)
        custom_confs = os.path.join(tmp_dir, "custom-confs")
        custom_template = os.path.join(tmp_dir, "custom-tpl.conf")
        os.makedirs(custom_confs)
        open(custom_template, "w").close()
        open(os.path.join(custom_confs, "odoo_260101.conf"), "w").close()
        with open(os.path.join(native_dir, "repos.yaml"), "w", encoding="utf-8") as f:
            f.write(f"paths:\n  template: {custom_template}\n  config_dir: {custom_confs}\n")

        data = _version_paths("18", cfg)

        assert data["myconfs_dir"] == custom_confs
        assert data["files"]["template_conf"] == {"path": custom_template, "exists": True}
        assert data["files"]["generated_conf"]["path"] == os.path.join(custom_confs, "odoo_260101.conf")
        assert data["files"]["repos_yaml"] == {"path": os.path.join(native_dir, "repos.yaml"), "exists": True}


class TestConfigPathsCommand:
    def test_all_versions_json(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "paths", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "18" in payload
        for data in payload.values():
            assert set(data["files"].keys()) == set(ROLES)
            assert "native_dir" in data
            assert "conf_dir" in data
            assert "myconfs_dir" in data

    def test_single_version_json(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "paths", "18", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert list(payload.keys()) == ["18"]

    def test_unknown_version_fails(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "paths", "99", "--json"])
        assert result.exit_code != 0

    def test_human_readable_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "paths", "18"])
        assert result.exit_code == 0
        assert "config files" in result.output
