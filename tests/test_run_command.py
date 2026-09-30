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


class TestListSteps:
    def test_steps_table(self):
        result = CliRunner().invoke(cli, ["run", "--steps"])
        assert result.exit_code == 0
        assert "docker.up" in result.output
        assert "server.backup" in result.output

    def test_steps_json(self):
        from odoodev.core.playbook import SERVER_COMMANDS, VALID_COMMANDS

        result = CliRunner().invoke(cli, ["run", "--steps", "--output", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert len(data) == len(VALID_COMMANDS)
        by_command = {entry["command"]: entry["mode"] for entry in data}
        for cmd in SERVER_COMMANDS:
            assert by_command[cmd] == "server"
        for cmd in VALID_COMMANDS - SERVER_COMMANDS:
            assert by_command[cmd] == "dev"


class TestOnStepWiring:
    def test_run_passes_on_step_callback(self, tmp_path, monkeypatch):
        pb = tmp_path / "pb.yaml"
        pb.write_text("version: '18'\nsteps:\n  - command: pull\n")
        monkeypatch.setattr("odoodev.core.version_registry.get_version", lambda v: object())

        from odoodev.core.playbook import PlaybookResult, PlaybookRunner

        with patch.object(PlaybookRunner, "execute") as mock_execute:
            mock_execute.return_value = PlaybookResult(
                playbook=str(pb), version="18", status="ok", steps=(), total_duration_ms=0
            )
            result = CliRunner().invoke(cli, ["run", str(pb), "--dry-run"])

        assert result.exit_code == 0
        assert callable(mock_execute.call_args.kwargs["on_step"])


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


# =============================================================================
# Server steps: what they say must reach the screen
# =============================================================================


class TestServerStepOutput:
    def _result(self, **kwargs):
        from odoodev.core.playbook import StepResult

        defaults = {"name": "step", "command": "server.verify", "status": "ok", "exit_code": 0, "duration_ms": 5}
        return StepResult(**{**defaults, **kwargs})

    def _render(self, result) -> str:
        from io import StringIO

        from rich.console import Console

        from odoodev.commands import run as run_mod

        buffer = StringIO()
        with patch.object(run_mod, "console", Console(file=buffer, width=200, color_system=None)):
            run_mod._print_step_result_text(result)
        return buffer.getvalue()

    def test_ok_server_step_prints_its_message(self):
        out = self._render(self._result(message="'acme_prod' is up in 'live-odoo': container healthy"))
        assert "[OK]" in out
        assert "'acme_prod' is up in 'live-odoo'" in out

    def test_ok_dev_step_stays_a_single_line(self):
        out = self._render(self._result(command="docker.up", message="Services started"))
        assert "Services started" not in out

    def test_preflight_warning_is_not_shown_as_a_plain_ok(self):
        out = self._render(
            self._result(name="Preflight", command="preflight", message="[warning] 'live-odoo' is switched off")
        )
        assert "[WARN]" in out and "[OK]" not in out
        assert "[warning] 'live-odoo' is switched off" in out

    def test_preflight_error_lists_every_finding(self):
        message = "[error] odoo_version '18'\n[warning] never updated"
        out = self._render(self._result(name="Preflight", command="preflight", status="error", message=message))
        assert "[ERROR]" in out
        assert "[error] odoo_version '18'" in out
        assert "[warning] never updated" in out

    def test_brackets_in_an_error_message_survive(self):
        out = self._render(self._result(status="error", message="args were ['--verbose'] [red]"))
        assert "['--verbose'] [red]" in out

    def test_no_preflight_flag_reaches_the_runner(self, tmp_path, monkeypatch):
        playbook = tmp_path / "pb.yaml"
        playbook.write_text(yaml.dump({"version": "18", "steps": [{"command": "docker.status"}]}))
        seen = {}

        def fake_execute(self, pb, **kwargs):
            from odoodev.core.playbook import PlaybookResult

            seen.update(kwargs)
            return PlaybookResult(playbook="pb", version="18", status="ok", steps=(), total_duration_ms=0)

        monkeypatch.setattr("odoodev.core.playbook.PlaybookRunner.execute", fake_execute)
        assert CliRunner().invoke(cli, ["run", str(playbook), "--no-preflight"]).exit_code == 0
        assert seen["preflight"] is False
        assert CliRunner().invoke(cli, ["run", str(playbook)]).exit_code == 0
        assert seen["preflight"] is True


# =============================================================================
# Progress: which step is running, and what it is doing
# =============================================================================


class TestStepProgress:
    def _console(self, monkeypatch):
        from io import StringIO

        from rich.console import Console

        from odoodev.commands import run as run_mod

        buffer = StringIO()
        monkeypatch.setattr(run_mod, "console", Console(file=buffer, width=200, color_system=None))
        return run_mod, buffer

    def test_into_a_pipe_each_step_and_report_is_a_plain_line(self, monkeypatch):
        run_mod, buffer = self._console(monkeypatch)  # a StringIO is no terminal
        progress = run_mod._StepProgress()
        progress.start(2, 5, "Restore backup into test")
        progress.update("restoring the dump into 'x__odoodev_new'")
        progress.stop()
        out = buffer.getvalue()
        assert "[2/5] Restore backup into test" in out
        assert "restoring the dump into 'x__odoodev_new'" in out
        assert progress.position == "2/5"

    def test_a_report_without_a_running_step_prints_nothing(self, monkeypatch):
        run_mod, buffer = self._console(monkeypatch)
        run_mod._StepProgress().update("stray")
        assert buffer.getvalue() == ""

    def test_result_line_carries_position_and_readable_duration(self, monkeypatch):
        from odoodev.core.playbook import StepResult

        run_mod, buffer = self._console(monkeypatch)
        result = StepResult("Rebuild image", "server.rebuild", "ok", "rebuilt", 0, 439393)
        run_mod._print_step_result_text(result, "1/2")
        out = buffer.getvalue()
        assert "[OK] 1/2 Rebuild image (7m 19s)" in out
        assert "439393" not in out

    @pytest.mark.parametrize(
        ("ms", "text"),
        [
            (6, "6ms"),
            (999, "999ms"),
            (6368, "6.4s"),
            (59999, "60.0s"),
            (60000, "1m 00s"),
            (439393, "7m 19s"),
            (3_725_000, "1h 02m 05s"),
        ],
    )
    def test_format_duration(self, ms, text):
        from odoodev.commands.run import _format_duration

        assert _format_duration(ms) == text

    def _server_playbook(self, tmp_path):
        playbook = tmp_path / "pb.yaml"
        playbook.write_text(
            yaml.dump(
                {
                    "version": "18",
                    "targets": {"t": {"db_container": "t-db", "odoo_container": "t-odoo", "db_name": "d"}},
                    "steps": [
                        {"name": "Stop it", "command": "container.stop", "args": {"target": "t"}},
                        {"name": "Check it", "command": "server.verify", "args": {"target": "t"}},
                    ],
                }
            )
        )
        return str(playbook)

    def _fake_handlers(self, monkeypatch):
        from odoodev.core import server_automation as sa
        from odoodev.core.playbook import StepResult

        def stop(cfg, args):
            assert "_progress" not in args  # only long-running steps get the callback
            return StepResult("container.stop", "container.stop", "ok", "stopped", 0, 3)

        def verify(cfg, args):
            args["_progress"]("waiting for 't-odoo' to report healthy")
            return StepResult("server.verify", "server.verify", "ok", "up", 0, 1500)

        monkeypatch.setitem(sa.SERVER_COMMAND_HANDLERS, "container.stop", stop)
        monkeypatch.setitem(sa.SERVER_COMMAND_HANDLERS, "server.verify", verify)

    def test_text_run_shows_position_step_name_and_reports(self, tmp_path, monkeypatch):
        self._fake_handlers(monkeypatch)
        result = CliRunner().invoke(cli, ["run", self._server_playbook(tmp_path)])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        started = [line for line in lines if "..." in line]
        assert "[1/2] Stop it" in started[0] and "[2/2] Check it" in started[1]
        assert any("waiting for 't-odoo' to report healthy" in line for line in lines)
        # results carry the playbook's own step names, not the command
        assert any("[OK] 1/2 Stop it" in line for line in lines)
        assert any("[OK] 2/2 Check it (1.5s)" in line for line in lines)

    def test_json_run_emits_start_and_progress_events(self, tmp_path, monkeypatch):
        self._fake_handlers(monkeypatch)
        result = CliRunner().invoke(cli, ["run", self._server_playbook(tmp_path), "-o", "json"])
        assert result.exit_code == 0, result.output
        events = [json.loads(line) for line in result.output.splitlines() if line.startswith("{")]
        kinds = [e["event"] for e in events]
        assert kinds == [
            "playbook_start",
            "step_start",
            "step_done",
            "step_start",
            "step_progress",
            "step_done",
            "playbook_done",
        ]
        assert events[1] == {
            "event": "step_start",
            "index": 1,
            "total": 2,
            "name": "Stop it",
            "command": "container.stop",
        }
        assert events[4]["message"] == "waiting for 't-odoo' to report healthy"
        assert events[4]["index"] == 2
        assert events[5]["name"] == "Check it"

    def test_dry_run_announces_nothing(self, tmp_path, monkeypatch):
        result = CliRunner().invoke(
            cli, ["run", self._server_playbook(tmp_path), "-o", "json", "--dry-run", "--no-preflight"]
        )
        kinds = [json.loads(line)["event"] for line in result.output.splitlines() if line.startswith("{")]
        assert "step_start" not in kinds and "step_progress" not in kinds
