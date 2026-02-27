"""Tests for odoodev.core.playbook — dataclasses, validation, loading, runner."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from odoodev.core.playbook import (
    PlaybookConfig,
    PlaybookRunner,
    PlaybookValidationError,
    StepConfig,
    StepResult,
    VALID_COMMANDS,
    build_playbook_from_steps,
    load_playbook,
)


# =============================================================================
# StepConfig dataclass tests
# =============================================================================


class TestStepConfig:
    def test_default_args(self):
        step = StepConfig(name="test", command="docker.up")
        assert step.args == {}
        assert step.on_error == ""

    def test_with_args(self):
        step = StepConfig(name="test", command="repos", args={"config-only": True})
        assert step.args == {"config-only": True}

    def test_frozen(self):
        step = StepConfig(name="test", command="docker.up")
        with pytest.raises(AttributeError):
            step.name = "changed"  # type: ignore[misc]


# =============================================================================
# PlaybookConfig dataclass tests
# =============================================================================


class TestPlaybookConfig:
    def test_basic_creation(self):
        steps = (StepConfig(name="s1", command="docker.up"),)
        pb = PlaybookConfig(version="18", on_error="stop", steps=steps)
        assert pb.version == "18"
        assert pb.on_error == "stop"
        assert len(pb.steps) == 1

    def test_frozen(self):
        steps = (StepConfig(name="s1", command="docker.up"),)
        pb = PlaybookConfig(version="18", on_error="stop", steps=steps)
        with pytest.raises(AttributeError):
            pb.version = "19"  # type: ignore[misc]


# =============================================================================
# StepResult / PlaybookResult tests
# =============================================================================


class TestStepResult:
    def test_ok_result(self):
        r = StepResult(name="s1", command="docker.up", status="ok", message="done", exit_code=0, duration_ms=100)
        assert r.status == "ok"
        assert r.exit_code == 0
        assert r.details == {}

    def test_error_result_with_details(self):
        r = StepResult(
            name="s1",
            command="start",
            status="error",
            message="failed",
            exit_code=1,
            duration_ms=50,
            details={"pid": 123},
        )
        assert r.details == {"pid": 123}


# =============================================================================
# VALID_COMMANDS sanity
# =============================================================================


class TestValidCommands:
    def test_contains_expected(self):
        expected = {"docker.up", "docker.down", "docker.status", "pull", "repos", "start", "stop"}
        assert expected.issubset(VALID_COMMANDS)

    def test_contains_db_commands(self):
        assert "db.list" in VALID_COMMANDS
        assert "db.backup" in VALID_COMMANDS
        assert "db.restore" in VALID_COMMANDS
        assert "db.drop" in VALID_COMMANDS

    def test_contains_env_venv(self):
        assert "env.check" in VALID_COMMANDS
        assert "venv.check" in VALID_COMMANDS
        assert "venv.setup" in VALID_COMMANDS


# =============================================================================
# load_playbook tests
# =============================================================================


class TestLoadPlaybook:
    def test_load_valid_playbook(self, tmp_dir):
        data = {
            "version": "18",
            "on_error": "stop",
            "steps": [
                {"name": "Start Docker", "command": "docker.up"},
                {"name": "Pull code", "command": "pull"},
            ],
        }
        path = os.path.join(tmp_dir, "test.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)

        pb = load_playbook(path)
        assert pb.version == "18"
        assert pb.on_error == "stop"
        assert len(pb.steps) == 2
        assert pb.steps[0].command == "docker.up"
        assert pb.steps[1].command == "pull"

    def test_load_with_args(self, tmp_dir):
        data = {
            "version": "18",
            "on_error": "continue",
            "steps": [
                {"name": "Repos config-only", "command": "repos", "args": {"config-only": True}},
            ],
        }
        path = os.path.join(tmp_dir, "args.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)

        pb = load_playbook(path)
        assert pb.steps[0].args == {"config-only": True}

    def test_load_with_step_on_error(self, tmp_dir):
        data = {
            "version": "18",
            "on_error": "stop",
            "steps": [
                {"name": "Backup", "command": "db.backup", "args": {"name": "test"}, "on_error": "continue"},
            ],
        }
        path = os.path.join(tmp_dir, "onerror.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)

        pb = load_playbook(path)
        assert pb.steps[0].on_error == "continue"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_playbook("/nonexistent/path.yaml")

    def test_empty_file(self, tmp_dir):
        path = os.path.join(tmp_dir, "empty.yaml")
        Path(path).touch()
        with pytest.raises(PlaybookValidationError, match="empty"):
            load_playbook(path)

    def test_missing_version(self, tmp_dir):
        data = {"steps": [{"command": "docker.up"}]}
        path = os.path.join(tmp_dir, "noversion.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)
        with pytest.raises(PlaybookValidationError, match="version"):
            load_playbook(path)

    def test_missing_steps(self, tmp_dir):
        data = {"version": "18"}
        path = os.path.join(tmp_dir, "nosteps.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)
        with pytest.raises(PlaybookValidationError, match="at least one step"):
            load_playbook(path)

    def test_invalid_command(self, tmp_dir):
        data = {"version": "18", "steps": [{"name": "bad", "command": "invalid.cmd"}]}
        path = os.path.join(tmp_dir, "badcmd.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)
        with pytest.raises(PlaybookValidationError, match="unknown command"):
            load_playbook(path)

    def test_invalid_on_error(self, tmp_dir):
        data = {"version": "18", "on_error": "explode", "steps": [{"command": "docker.up"}]}
        path = os.path.join(tmp_dir, "badon.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)
        with pytest.raises(PlaybookValidationError, match="on_error"):
            load_playbook(path)

    def test_step_missing_command(self, tmp_dir):
        data = {"version": "18", "steps": [{"name": "missing cmd"}]}
        path = os.path.join(tmp_dir, "nocmd.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)
        with pytest.raises(PlaybookValidationError, match="command"):
            load_playbook(path)

    def test_default_on_error(self, tmp_dir):
        data = {"version": "18", "steps": [{"command": "docker.up"}]}
        path = os.path.join(tmp_dir, "defaults.yaml")
        with open(path, "w") as f:
            yaml.dump(data, f)

        pb = load_playbook(path)
        assert pb.on_error == "stop"


# =============================================================================
# build_playbook_from_steps tests
# =============================================================================


class TestBuildPlaybookFromSteps:
    def test_single_step(self):
        pb = build_playbook_from_steps(["docker.up"], "18")
        assert pb.version == "18"
        assert len(pb.steps) == 1
        assert pb.steps[0].command == "docker.up"

    def test_multiple_steps(self):
        pb = build_playbook_from_steps(["docker.up", "pull", "repos"], "18")
        assert len(pb.steps) == 3
        assert pb.steps[2].command == "repos"

    def test_step_names_match_commands(self):
        pb = build_playbook_from_steps(["docker.up", "pull"], "18")
        assert pb.steps[0].name == "docker.up"
        assert pb.steps[1].name == "pull"

    def test_empty_steps_raises(self):
        with pytest.raises(PlaybookValidationError, match="No steps"):
            build_playbook_from_steps([], "18")

    def test_empty_version_raises(self):
        with pytest.raises(PlaybookValidationError, match="Version"):
            build_playbook_from_steps(["docker.up"], "")

    def test_invalid_command_raises(self):
        with pytest.raises(PlaybookValidationError, match="Unknown command"):
            build_playbook_from_steps(["not.a.command"], "18")

    def test_custom_on_error(self):
        pb = build_playbook_from_steps(["docker.up"], "18", on_error="continue")
        assert pb.on_error == "continue"


# =============================================================================
# PlaybookRunner tests
# =============================================================================


class TestPlaybookRunner:
    @patch("odoodev.core.playbook.PlaybookRunner.__init__", return_value=None)
    def _make_runner(self, mock_init, handlers=None):
        runner = PlaybookRunner.__new__(PlaybookRunner)
        runner._handlers = handlers or {}
        return runner

    def test_dry_run(self):
        runner = self._make_runner()
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(StepConfig(name="s1", command="docker.up"),),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, dry_run=True, playbook_name="test")

        assert result.status == "ok"
        assert len(result.steps) == 1
        assert "[dry-run]" in result.steps[0].message

    def test_handler_called(self):
        mock_handler = MagicMock(
            return_value=StepResult(
                name="docker.up",
                command="docker.up",
                status="ok",
                message="done",
                exit_code=0,
                duration_ms=100,
            )
        )
        runner = self._make_runner(handlers={"docker.up": mock_handler})
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(StepConfig(name="s1", command="docker.up"),),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, playbook_name="test")

        assert result.status == "ok"
        mock_handler.assert_called_once()

    def test_on_error_stop_skips_remaining(self):
        error_handler = MagicMock(
            return_value=StepResult(
                name="pull", command="pull", status="error", message="fail", exit_code=1, duration_ms=50
            )
        )
        ok_handler = MagicMock(
            return_value=StepResult(
                name="repos", command="repos", status="ok", message="ok", exit_code=0, duration_ms=50
            )
        )
        runner = self._make_runner(handlers={"pull": error_handler, "repos": ok_handler})
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(
                StepConfig(name="pull", command="pull"),
                StepConfig(name="repos", command="repos"),
            ),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, playbook_name="test")

        assert result.status == "error"
        assert result.steps[0].status == "error"
        assert result.steps[1].status == "skipped"
        ok_handler.assert_not_called()

    def test_on_error_continue(self):
        error_handler = MagicMock(
            return_value=StepResult(
                name="pull", command="pull", status="error", message="fail", exit_code=1, duration_ms=50
            )
        )
        ok_handler = MagicMock(
            return_value=StepResult(
                name="repos", command="repos", status="ok", message="ok", exit_code=0, duration_ms=50
            )
        )
        runner = self._make_runner(handlers={"pull": error_handler, "repos": ok_handler})
        pb = PlaybookConfig(
            version="18",
            on_error="continue",
            steps=(
                StepConfig(name="pull", command="pull"),
                StepConfig(name="repos", command="repos"),
            ),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, playbook_name="test")

        assert result.status == "error"
        assert result.steps[0].status == "error"
        assert result.steps[1].status == "ok"
        ok_handler.assert_called_once()

    def test_step_on_error_overrides_playbook(self):
        """Step-level on_error=continue overrides playbook on_error=stop."""
        error_handler = MagicMock(
            return_value=StepResult(
                name="pull", command="pull", status="error", message="fail", exit_code=1, duration_ms=50
            )
        )
        ok_handler = MagicMock(
            return_value=StepResult(
                name="repos", command="repos", status="ok", message="ok", exit_code=0, duration_ms=50
            )
        )
        runner = self._make_runner(handlers={"pull": error_handler, "repos": ok_handler})
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(
                StepConfig(name="pull", command="pull", on_error="continue"),
                StepConfig(name="repos", command="repos"),
            ),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, playbook_name="test")

        assert result.steps[1].status == "ok"
        ok_handler.assert_called_once()

    def test_missing_handler(self):
        runner = self._make_runner(handlers={})
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(StepConfig(name="s1", command="docker.up"),),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, playbook_name="test")

        assert result.status == "error"
        assert "No handler" in result.steps[0].message

    def test_handler_exception(self):
        def boom(version_cfg, args):
            raise RuntimeError("kaboom")

        runner = self._make_runner(handlers={"docker.up": boom})
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(StepConfig(name="s1", command="docker.up"),),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, playbook_name="test")

        assert result.status == "error"
        assert "kaboom" in result.steps[0].message

    def test_version_override(self):
        runner = self._make_runner(handlers={})
        pb = PlaybookConfig(
            version="18",
            on_error="stop",
            steps=(StepConfig(name="s1", command="docker.up"),),
        )

        with patch("odoodev.core.version_registry.get_version") as mock_gv:
            mock_gv.return_value = MagicMock()
            result = runner.execute(pb, version_override="19", playbook_name="test")

        mock_gv.assert_called_with("19")
        assert result.version == "19"
