"""Tests for odoodev pull command."""

import os

from click.testing import CliRunner

from odoodev.cli import cli


class TestPullHelp:
    def test_pull_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "pull" in result.output

    def test_pull_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.output
        assert "--verbose" in result.output


class TestPullNoConfig:
    def test_pull_no_repos_yaml(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.pull.resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr("odoodev.commands.pull.load_versions", lambda: {})
        monkeypatch.setattr(
            "odoodev.commands.pull.get_version",
            lambda v, vers=None: _make_version_cfg("/tmp/nonexistent"),
        )
        monkeypatch.setattr("odoodev.commands.pull._find_repos_config", lambda cfg: None)

        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "18"])
        assert result.exit_code != 0


class TestPullExecution:
    def test_pull_all_skipped(self, tmp_path, monkeypatch):
        """All repos missing on disk → all skipped."""
        repos_yaml = tmp_path / "repos.yaml"
        repos_yaml.write_text(
            "version: '18'\n"
            "branch: develop\n"
            "paths:\n"
            f"  base: {tmp_path}\n"
            "addons:\n"
            "  - key: test-addon\n"
            "    path: test-addon\n"
            "    git_url: git@example.com:test/test-addon.git\n"
            "    section: Other\n"
        )

        monkeypatch.setattr("odoodev.commands.pull.resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr("odoodev.commands.pull.load_versions", lambda: {})
        monkeypatch.setattr(
            "odoodev.commands.pull.get_version",
            lambda v, vers=None: _make_version_cfg(str(tmp_path)),
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "18", "-c", str(repos_yaml)])
        assert result.exit_code == 0
        assert "Skipped" in result.output

    def test_pull_with_existing_repo(self, tmp_path, monkeypatch):
        """Existing repo dir → update_repo called."""
        # Create fake server dir
        server_dir = tmp_path / "v18-server"
        server_dir.mkdir()

        repos_yaml = tmp_path / "repos.yaml"
        repos_yaml.write_text(f"version: '18'\nbranch: develop\npaths:\n  base: {tmp_path}\n")

        monkeypatch.setattr("odoodev.commands.pull.resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr("odoodev.commands.pull.load_versions", lambda: {})
        monkeypatch.setattr(
            "odoodev.commands.pull.get_version",
            lambda v, vers=None: _make_version_cfg(str(tmp_path)),
        )
        monkeypatch.setattr("odoodev.commands.pull.update_repo", lambda path, branch: True)

        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "18", "-c", str(repos_yaml)])
        assert result.exit_code == 0
        assert "Updated" in result.output

    def test_pull_failed_repo(self, tmp_path, monkeypatch):
        """Failed repo update → exit code 1."""
        server_dir = tmp_path / "v18-server"
        server_dir.mkdir()

        repos_yaml = tmp_path / "repos.yaml"
        repos_yaml.write_text(f"version: '18'\nbranch: develop\npaths:\n  base: {tmp_path}\n")

        monkeypatch.setattr("odoodev.commands.pull.resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr("odoodev.commands.pull.load_versions", lambda: {})
        monkeypatch.setattr(
            "odoodev.commands.pull.get_version",
            lambda v, vers=None: _make_version_cfg(str(tmp_path)),
        )
        monkeypatch.setattr("odoodev.commands.pull.update_repo", lambda path, branch: False)

        runner = CliRunner()
        result = runner.invoke(cli, ["pull", "18", "-c", str(repos_yaml)])
        assert result.exit_code != 0
        assert "Failed" in result.output


def _make_version_cfg(base_path: str):
    """Create a minimal mock VersionConfig."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class MockPaths:
        base: str = base_path
        server_subdir: str = "v18-server"
        dev_subdir: str = "v18-dev"
        native_subdir: str = "dev18_native"
        conf_subdir: str = "conf"

        @property
        def base_expanded(self) -> str:
            return os.path.expanduser(self.base)

        @property
        def native_dir(self) -> str:
            return os.path.join(self.base_expanded, self.dev_subdir, self.native_subdir)

        @property
        def dev_dir(self) -> str:
            return os.path.join(self.base_expanded, self.dev_subdir)

    @dataclass(frozen=True)
    class MockGit:
        server_url: str = "git@example.com:v18/v18-server.git"
        branch: str = "develop"

    @dataclass(frozen=True)
    class MockPorts:
        db: int = 18432
        odoo: int = 18069
        gevent: int = 18072
        mailpit: int = 18025
        smtp: int = 1025

    @dataclass(frozen=True)
    class MockVersionConfig:
        version: str = "18"
        python: str = "3.12"
        postgres: str = "16.11-alpine"
        paths: MockPaths = MockPaths()
        git: MockGit = MockGit()
        ports: MockPorts = MockPorts()

    return MockVersionConfig()
