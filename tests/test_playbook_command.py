"""CliRunner E2E tests for `odoodev playbook` (create --answers, schema, validate)."""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.playbook import load_playbook
from tests.test_playbook_builder import dev_answers, server_answers


@pytest.fixture
def runner():
    return CliRunner()


def _write_answers(tmp_path, answers: dict) -> str:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers))
    return str(path)


# =============================================================================
# playbook create --answers (non-interactive / GUI mode)
# =============================================================================


class TestCreateFromAnswers:
    def test_writes_valid_playbook(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        answers = server_answers()
        answers["output_path"] = "./playbooks/mirror.yaml"
        result = runner.invoke(
            cli, ["playbook", "create", "--answers", _write_answers(tmp_path, answers), "--non-interactive"]
        )
        assert result.exit_code == 0, result.output
        config = load_playbook(str(tmp_path / "playbooks" / "mirror.yaml"))
        assert config.version == "18"
        assert [s.command for s in config.steps][0] == "server.backup"

    def test_dev_answers(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli, ["playbook", "create", "--answers", _write_answers(tmp_path, dev_answers()), "--non-interactive"]
        )
        assert result.exit_code == 0, result.output
        config = load_playbook(str(tmp_path / "playbooks" / "daily-update.yaml"))
        assert [s.command for s in config.steps] == ["docker.up", "pull", "start"]

    def test_output_option_overrides_answers(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "custom" / "mirror.yaml"
        result = runner.invoke(
            cli,
            [
                "playbook",
                "create",
                "--answers",
                _write_answers(tmp_path, server_answers()),
                "--non-interactive",
                "--output",
                str(target),
            ],
        )
        assert result.exit_code == 0, result.output
        assert target.exists()

    def test_non_interactive_without_answers_is_usage_error(self, runner):
        result = runner.invoke(cli, ["playbook", "create", "--non-interactive"])
        assert result.exit_code != 0
        assert "--answers" in result.output

    def test_invalid_answers_lists_all_problems(self, tmp_path, runner):
        broken = {"schema_version": 99, "playbook_type": "server"}
        result = runner.invoke(
            cli, ["playbook", "create", "--answers", _write_answers(tmp_path, broken), "--non-interactive"]
        )
        assert result.exit_code == 1
        assert "schema_version" in result.output
        assert "name is required" in result.output
        assert "targets" in result.output

    def test_existing_output_refused_without_force(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        answers_path = _write_answers(tmp_path, server_answers())
        first = runner.invoke(cli, ["playbook", "create", "--answers", answers_path, "--non-interactive"])
        assert first.exit_code == 0, first.output
        second = runner.invoke(cli, ["playbook", "create", "--answers", answers_path, "--non-interactive"])
        assert second.exit_code == 1
        assert "--force" in second.output
        forced = runner.invoke(cli, ["playbook", "create", "--answers", answers_path, "--non-interactive", "--force"])
        assert forced.exit_code == 0, forced.output

    def test_env_file_written_with_0600(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        answers = server_answers()
        answers["env_file"] = {
            "path": str(tmp_path / "mirror.env"),
            "generate": True,
            "secrets": {"ODOO_PASSWORD": "s3cret", "PARTNER_ENTERPRISE_CODE": "XXXX"},
        }
        result = runner.invoke(
            cli, ["playbook", "create", "--answers", _write_answers(tmp_path, answers), "--non-interactive"]
        )
        assert result.exit_code == 0, result.output
        env_path = tmp_path / "mirror.env"
        assert oct(os.stat(env_path).st_mode)[-3:] == "600"
        assert "ODOO_PASSWORD=s3cret" in env_path.read_text()

    def test_existing_env_file_refused_without_force(self, tmp_path, monkeypatch, runner):
        monkeypatch.chdir(tmp_path)
        env_path = tmp_path / "mirror.env"
        env_path.write_text("PRODUCTION_SECRET=do-not-clobber\n")
        answers = server_answers()
        answers["env_file"] = {"path": str(env_path), "generate": True, "secrets": {"ODOO_PASSWORD": "x"}}
        result = runner.invoke(
            cli, ["playbook", "create", "--answers", _write_answers(tmp_path, answers), "--non-interactive"]
        )
        assert result.exit_code == 1
        assert "env_file" in result.output
        assert "do-not-clobber" in env_path.read_text()  # untouched


# =============================================================================
# playbook schema
# =============================================================================


class TestSchemaCommand:
    def test_json_output_is_single_line_json(self, runner):
        result = runner.invoke(cli, ["playbook", "schema", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["schema_version"] == 2
        assert "sections" in payload and "step_args" in payload

    def test_json_resolves_version_choices(self, runner):
        payload = json.loads(runner.invoke(cli, ["playbook", "schema", "--json"]).output.strip())
        common = next(s for s in payload["sections"] if s["key"] == "common")
        version_field = next(f for f in common["fields"] if f["key"] == "version")
        assert version_field["choices"], "available_versions must be resolved inline"

    def test_json_includes_rebuild_step_spec(self, runner):
        payload = json.loads(runner.invoke(cli, ["playbook", "schema", "--json"]).output.strip())
        rebuild = payload["step_args"]["server.rebuild"]
        assert rebuild["mode"] == "server"
        arg_names = {a["name"] for a in rebuild["args"]}
        assert {"script_path", "config", "timeout"} <= arg_names

    def test_human_output_lists_sections(self, runner):
        result = runner.invoke(cli, ["playbook", "schema"])
        assert result.exit_code == 0
        assert "server_recipe" in result.output


# =============================================================================
# playbook validate
# =============================================================================


class TestValidateCommand:
    def _write_playbook(self, tmp_path, runner) -> str:
        answers = server_answers()
        answers["output_path"] = str(tmp_path / "mirror.yaml")
        result = runner.invoke(
            cli, ["playbook", "create", "--answers", _write_answers(tmp_path, answers), "--non-interactive"]
        )
        assert result.exit_code == 0, result.output
        return answers["output_path"]

    def test_valid_playbook_text(self, tmp_path, runner):
        path = self._write_playbook(tmp_path, runner)
        result = runner.invoke(cli, ["playbook", "validate", path])
        assert result.exit_code == 0
        assert "valid" in result.output

    def test_valid_playbook_json(self, tmp_path, runner):
        path = self._write_playbook(tmp_path, runner)
        result = runner.invoke(cli, ["playbook", "validate", path, "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload == {"valid": True, "steps": 9, "version": "18"}

    def test_invalid_playbook_text(self, tmp_path, runner):
        bad = tmp_path / "bad.yaml"
        bad.write_text("version: '18'\nsteps:\n  - command: does.not.exist\n")
        result = runner.invoke(cli, ["playbook", "validate", str(bad)])
        assert result.exit_code == 1

    def test_invalid_playbook_json(self, tmp_path, runner):
        bad = tmp_path / "bad.yaml"
        bad.write_text("version: '18'\nsteps:\n  - command: does.not.exist\n")
        result = runner.invoke(cli, ["playbook", "validate", str(bad), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output.strip())
        assert payload["valid"] is False
        assert "does.not.exist" in payload["error"]
