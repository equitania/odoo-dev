"""Tests for odoodev.commands.run — CLI integration tests."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from odoodev.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_version_cfg():
    cfg = MagicMock()
    cfg.version = "18"
    cfg.ports.db = 18432
    cfg.ports.odoo = 18069
    cfg.paths.native_dir = "/tmp/test_native"
    cfg.paths.server_dir = "/tmp/test_server"
    cfg.paths.myconfs_dir = "/tmp/test_myconfs"
    cfg.paths.base_expanded = "/tmp/test_base"
    cfg.paths.server_subdir = "v18-server"
    cfg.python = "3.13"
    return cfg


# =============================================================================
# Basic CLI tests
# =============================================================================


class TestRunCommand:
    def test_no_args_shows_interactive_prompt(self, runner):
        result = runner.invoke(cli, ["run"])
        # Without args, run now shows an interactive prompt (select mode)
        # In non-interactive test context, questionary aborts → exit code != 0
        assert result.exit_code != 0

    def test_both_playbook_and_step_error(self, runner, tmp_dir):
        pb_file = os.path.join(tmp_dir, "test.yaml")
        with open(pb_file, "w") as f:
            yaml.dump({"version": "18", "steps": [{"command": "docker.up"}]}, f)
        result = runner.invoke(cli, ["run", pb_file, "--step", "docker.up"])
        assert result.exit_code != 0
        assert "Cannot use both" in result.output

    def test_playbook_not_found(self, runner):
        result = runner.invoke(cli, ["run", "/nonexistent.yaml"])
        assert result.exit_code != 0

    def test_invalid_step_command(self, runner):
        result = runner.invoke(cli, ["run", "--step", "invalid.cmd", "-V", "18"])
        assert result.exit_code != 0
        assert "Unknown command" in result.output or "error" in result.output.lower()


# =============================================================================
# Dry-run tests
# =============================================================================


class TestDryRun:
    @patch("odoodev.core.version_registry.get_version")
    def test_dry_run_yaml(self, mock_gv, runner, tmp_dir, mock_version_cfg):
        mock_gv.return_value = mock_version_cfg

        pb_data = {
            "version": "18",
            "on_error": "stop",
            "steps": [
                {"name": "Start Docker", "command": "docker.up"},
                {"name": "Pull code", "command": "pull"},
            ],
        }
        pb_file = os.path.join(tmp_dir, "test.yaml")
        with open(pb_file, "w") as f:
            yaml.dump(pb_data, f)

        result = runner.invoke(cli, ["run", pb_file, "--dry-run"])
        assert result.exit_code == 0
        # Normalize whitespace: Rich may wrap "[DRY RUN]" across lines on narrow widths.
        assert "dry run" in " ".join(result.output.lower().split())

    @patch("odoodev.core.version_registry.get_version")
    def test_dry_run_inline(self, mock_gv, runner, mock_version_cfg):
        mock_gv.return_value = mock_version_cfg

        result = runner.invoke(cli, ["run", "--step", "docker.up", "--step", "pull", "-V", "18", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()


# =============================================================================
# JSON output tests
# =============================================================================


class TestJsonOutput:
    @patch("odoodev.core.version_registry.get_version")
    def test_json_output_format(self, mock_gv, runner, tmp_dir, mock_version_cfg):
        mock_gv.return_value = mock_version_cfg

        pb_data = {
            "version": "18",
            "on_error": "stop",
            "steps": [{"name": "Docker Up", "command": "docker.up"}],
        }
        pb_file = os.path.join(tmp_dir, "test.yaml")
        with open(pb_file, "w") as f:
            yaml.dump(pb_data, f)

        result = runner.invoke(cli, ["run", pb_file, "--dry-run", "-o", "json"])
        assert result.exit_code == 0

        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        assert len(lines) >= 2  # playbook_start + step_done + playbook_done

        # Each line should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "event" in parsed

    @patch("odoodev.core.version_registry.get_version")
    def test_json_has_playbook_done(self, mock_gv, runner, tmp_dir, mock_version_cfg):
        mock_gv.return_value = mock_version_cfg

        pb_data = {
            "version": "18",
            "steps": [{"command": "docker.up"}],
        }
        pb_file = os.path.join(tmp_dir, "test.yaml")
        with open(pb_file, "w") as f:
            yaml.dump(pb_data, f)

        result = runner.invoke(cli, ["run", pb_file, "--dry-run", "-o", "json"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        events = [json.loads(l) for l in lines]
        event_types = [e["event"] for e in events]

        assert "playbook_start" in event_types
        assert "playbook_done" in event_types


# =============================================================================
# Version handling tests
# =============================================================================


class TestVersionHandling:
    @patch("odoodev.core.version_registry.get_version")
    def test_version_from_playbook(self, mock_gv, runner, tmp_dir, mock_version_cfg):
        mock_gv.return_value = mock_version_cfg

        pb_data = {"version": "18", "steps": [{"command": "docker.up"}]}
        pb_file = os.path.join(tmp_dir, "test.yaml")
        with open(pb_file, "w") as f:
            yaml.dump(pb_data, f)

        result = runner.invoke(cli, ["run", pb_file, "--dry-run"])
        assert result.exit_code == 0
        mock_gv.assert_called_with("18")

    @patch("odoodev.core.version_registry.get_version")
    def test_version_override(self, mock_gv, runner, tmp_dir, mock_version_cfg):
        mock_gv.return_value = mock_version_cfg

        pb_data = {"version": "18", "steps": [{"command": "docker.up"}]}
        pb_file = os.path.join(tmp_dir, "test.yaml")
        with open(pb_file, "w") as f:
            yaml.dump(pb_data, f)

        result = runner.invoke(cli, ["run", pb_file, "-V", "19", "--dry-run"])
        assert result.exit_code == 0
        mock_gv.assert_called_with("19")


# =============================================================================
# Example playbook validation tests
# =============================================================================


class TestExamplePlaybooks:
    """Verify that bundled example playbooks are valid YAML and pass validation."""

    @pytest.fixture
    def examples_dir(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "odoodev", "data", "examples", "playbooks")

    def test_daily_update_valid(self, examples_dir):
        from odoodev.core.playbook import load_playbook

        pb = load_playbook(os.path.join(examples_dir, "daily-update.yaml"))
        assert pb.version == "18"
        assert len(pb.steps) == 4

    def test_start_dev_valid(self, examples_dir):
        from odoodev.core.playbook import load_playbook

        pb = load_playbook(os.path.join(examples_dir, "start-dev.yaml"))
        assert pb.version == "18"
        assert len(pb.steps) == 2

    def test_full_refresh_valid(self, examples_dir):
        from odoodev.core.playbook import load_playbook

        pb = load_playbook(os.path.join(examples_dir, "full-refresh.yaml"))
        assert pb.version == "18"
        assert len(pb.steps) == 5

    def test_restore_db_valid(self, examples_dir):
        from odoodev.core.playbook import load_playbook

        pb = load_playbook(os.path.join(examples_dir, "restore-db.yaml"))
        assert pb.version == "18"
        assert len(pb.steps) == 3
        assert pb.steps[1].args.get("backup-file") is not None


class TestRunList:
    def test_list_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("odoodev.cli.detect_version_from_cwd", lambda: None)
        result = CliRunner().invoke(cli, ["run", "--list"])
        assert result.exit_code == 0
        assert "No playbooks found" in result.output

    def test_list_finds_project_local(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("odoodev.cli.detect_version_from_cwd", lambda: None)
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "daily.yaml").write_text("version: '18'\ndescription: Daily backup\nsteps:\n  - command: pull\n")
        result = CliRunner().invoke(cli, ["run", "--list"])
        assert result.exit_code == 0
        assert "daily" in result.output
        assert "Daily backup" in result.output

    def test_list_json_output(self, tmp_path, monkeypatch):
        import json as json_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("odoodev.cli.detect_version_from_cwd", lambda: None)
        pb_dir = tmp_path / "playbooks"
        pb_dir.mkdir()
        (pb_dir / "x.yaml").write_text("version: '18'\nsteps:\n  - command: pull\n")
        result = CliRunner().invoke(cli, ["run", "--list", "--output", "json"])
        assert result.exit_code == 0
        data = json_mod.loads(result.output.strip())
        assert data[0]["name"] == "x"
        assert data[0]["source"] == "project"

    def test_list_includes_version_dir(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.chdir(tmp_path)
        native = tmp_path / "native"
        (native / "scripts" / "playbooks").mkdir(parents=True)
        (native / "scripts" / "playbooks" / "setup.yaml").write_text("version: '18'\nsteps:\n  - command: pull\n")
        monkeypatch.setattr(
            "odoodev.core.version_registry.get_version",
            lambda v: SimpleNamespace(paths=SimpleNamespace(native_dir=str(native))),
        )
        result = CliRunner().invoke(cli, ["run", "--list", "-V", "18"])
        assert result.exit_code == 0
        assert "setup" in result.output
        assert "version" in result.output


class TestRunVarOption:
    def test_var_overrides_playbook_var(self, tmp_path, monkeypatch):
        pb = tmp_path / "pb.yaml"
        pb.write_text(
            "version: '18'\n"
            "vars:\n"
            "  db: defaultdb\n"
            "steps:\n"
            "  - name: Backup\n"
            "    command: db.backup\n"
            "    args:\n"
            "      name: '{{ vars.db }}'\n"
        )
        monkeypatch.setattr("odoodev.core.version_registry.get_version", lambda v: object())
        result = CliRunner().invoke(cli, ["run", str(pb), "--dry-run", "-D", "db=cli_db"])
        assert result.exit_code == 0
        assert "cli_db" in result.output

    def test_var_invalid_format(self, tmp_path):
        pb = tmp_path / "pb.yaml"
        pb.write_text("version: '18'\nsteps:\n  - command: pull\n")
        result = CliRunner().invoke(cli, ["run", str(pb), "--dry-run", "-D", "novalue"])
        assert result.exit_code != 0
        assert "KEY=VALUE" in result.output
