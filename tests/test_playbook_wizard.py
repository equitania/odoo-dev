"""Tests for the interactive playbook assistant (commands/playbook_cmd.py wizard flow).

The output.py prompt wrappers imported into playbook_cmd are replaced with
queue-driven fakes — one queue per prompt kind, answers popped in call order.
The DEFAULT sentinel means "accept the prompt's default value".
"""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.playbook import load_playbook

DEFAULT = object()

_PC = "odoodev.commands.playbook_cmd"


class PromptScript:
    """Queue-driven fake for the wizard's prompt helpers."""

    def __init__(self, **queues):
        self.queues = {kind: list(values) for kind, values in queues.items()}
        self.log: list[tuple[str, str]] = []

    def pop(self, kind: str, message: str, default=None):
        self.log.append((kind, str(message)))
        queue = self.queues.get(kind)
        assert queue, f"unexpected {kind} prompt: {message!r} (log: {self.log})"
        value = queue.pop(0)
        return default if value is DEFAULT else value

    def assert_drained(self):
        leftovers = {kind: queue for kind, queue in self.queues.items() if queue}
        assert not leftovers, f"unconsumed prompt answers: {leftovers}"


@pytest.fixture
def install_script(monkeypatch):
    def _install(script: PromptScript) -> PromptScript:
        monkeypatch.setattr(f"{_PC}.text_input", lambda message, default="": script.pop("text", message, default))
        monkeypatch.setattr(f"{_PC}.path_input", lambda message, default="": script.pop("path", message, default))
        monkeypatch.setattr(
            f"{_PC}.select",
            lambda message, choices=None, default=None: script.pop("select", message, default),
        )
        monkeypatch.setattr(f"{_PC}.confirm", lambda message, default=True: script.pop("confirm", message, default))
        monkeypatch.setattr(
            f"{_PC}.checkbox_with_separators",
            lambda message, choices, instruction=None: script.pop("checkbox", message),
        )
        monkeypatch.setattr(f"{_PC}.password_input", lambda message: script.pop("password", message))
        return script

    return _install


def _run_create(tmp_path, monkeypatch) -> object:
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(cli, ["playbook", "create"])


# =============================================================================
# Server-mode happy path
# =============================================================================


def _server_script(tmp_path) -> PromptScript:
    """Happy path: source = fresh backup from live pair, destination = test pair."""
    return PromptScript(
        select=[
            "server",  # playbook type
            "18",  # version
            "stop",  # on_error
            "fresh_backup",  # SOURCE question
            "test",  # rebuild target
            "continue",  # update-all on_error
        ],
        text=[
            "live test mirror",  # name
            DEFAULT,  # description
            DEFAULT,  # source target name -> live
            DEFAULT,  # live db_container -> live-db
            "production",  # live db_name
            DEFAULT,  # live odoo_container -> live-odoo
            DEFAULT,  # live owner -> ownerp
            DEFAULT,  # live data_dir -> ""
            DEFAULT,  # backup_dir -> /opt/backups/docker
            DEFAULT,  # compression level -> 5
            DEFAULT,  # destination target name -> test
            DEFAULT,  # test db_container -> test-db
            "production",  # test db_name
            DEFAULT,  # test odoo_container -> test-odoo
            DEFAULT,  # test owner
            "/opt/odoo/test",  # test data_dir
            DEFAULT,  # rebuild script_path -> ~/update_docker_odoo.py
            DEFAULT,  # rebuild config -> ~/docker2update.yaml
            DEFAULT,  # rebuild timeout -> 7200
            DEFAULT,  # restore template -> template0
        ],
        path=[
            str(tmp_path / "playbooks" / "mirror.yaml"),  # output path
        ],
        confirm=[
            False,  # only_sql
            False,  # adjust derived pattern?
            False,  # add another target?
            True,  # drop
            False,  # purge_master_data
            True,  # update-all restart
            False,  # add custom step
            False,  # configure rpc block
            False,  # add custom var
            False,  # generate secrets file
            True,  # write playbook (summary confirm)
        ],
        checkbox=[
            ["rebuild", "stop_before_restore", "start_after_restore", "neutralize", "update_all"],  # recipe
            ["deactivate_cron", "neutralize"],  # sanitize flags
        ],
    )


class TestServerWizard:
    def test_happy_path_produces_loadable_playbook(self, tmp_path, monkeypatch, install_script):
        script = install_script(_server_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()

        output = tmp_path / "playbooks" / "mirror.yaml"
        assert output.exists()
        config = load_playbook(str(output))
        assert config.version == "18"
        assert set(config.targets) == {"live", "test"}
        assert config.targets["live"].db_container == "live-db"
        assert config.targets["test"].data_dir == "/opt/odoo/test"
        commands = [step.command for step in config.steps]
        assert commands == [
            "server.backup",
            "server.rebuild",
            "container.stop",
            "server.restore",
            "container.start",
            "server.neutralize",
            "server.update-all",
        ]

    def test_fresh_backup_derives_restore_pattern(self, tmp_path, monkeypatch, install_script):
        install_script(_server_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        backup = next(s for s in data["steps"] if s["command"] == "server.backup")
        assert backup["args"]["target"] == "live"
        restore = next(s for s in data["steps"] if s["command"] == "server.restore")
        assert restore["args"]["target"] == "test"
        assert restore["args"]["backup_source"] == {
            "mode": "newest_in_dir",
            "dir": "/opt/backups/docker",
            "pattern": "production_live-odoo_dockerbackup_*.tar.zst",
            "select_by": "mtime",
        }

    def test_rebuild_server_paths_stay_unexpanded(self, tmp_path, monkeypatch, install_script):
        # Defaults (answered via DEFAULT) must be omitted; a custom ~ path must stay literal.
        prompts = _server_script(tmp_path)
        prompts.queues["text"][16] = "~/custom/update.py"  # rebuild script_path
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        raw = (tmp_path / "playbooks" / "mirror.yaml").read_text()
        assert "~/custom/update.py" in raw  # literal, NOT locally expanded
        data = yaml.safe_load(raw.split("\n", 1)[1])
        rebuild = next(s for s in data["steps"] if s["command"] == "server.rebuild")
        assert rebuild["args"] == {"target": "test", "script_path": "~/custom/update.py"}  # config default omitted

    def test_source_existing_file_skips_backup_step(self, tmp_path, monkeypatch, install_script):
        script = install_script(
            PromptScript(
                select=[
                    "server",  # playbook type
                    "18",  # version
                    "stop",  # on_error
                    "existing_file",  # SOURCE question
                    "continue",  # update-all on_error
                ],
                text=[
                    "restore from file",  # name
                    DEFAULT,  # description
                    "~/backups/fixed.tar.zst",  # source backup file (server path, stays literal)
                    DEFAULT,  # destination name -> test
                    DEFAULT,  # test db_container
                    "production",  # test db_name
                    DEFAULT,  # test odoo_container
                    DEFAULT,  # owner
                    DEFAULT,  # data_dir
                    DEFAULT,  # restore template
                ],
                path=[str(tmp_path / "playbooks" / "from-file.yaml")],
                confirm=[
                    False,  # add another target?
                    True,  # drop
                    False,  # purge_master_data
                    True,  # update-all restart
                    False,  # add custom step
                    False,  # configure rpc block
                    False,  # add custom var
                    False,  # generate secrets file
                    True,  # write playbook
                ],
                checkbox=[
                    ["stop_before_restore", "start_after_restore", "neutralize", "update_all"],
                    ["deactivate_cron", "neutralize"],
                ],
            )
        )
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()

        raw = (tmp_path / "playbooks" / "from-file.yaml").read_text()
        assert "~/backups/fixed.tar.zst" in raw  # not locally expanded
        data = yaml.safe_load(raw.split("\n", 1)[1])
        commands = [s["command"] for s in data["steps"]]
        assert "server.backup" not in commands
        restore = next(s for s in data["steps"] if s["command"] == "server.restore")
        assert restore["args"]["backup_source"] == {"mode": "file", "path": "~/backups/fixed.tar.zst"}

    def test_self_mirror_guard_reasks_destination(self, tmp_path, monkeypatch, install_script):
        script = install_script(
            PromptScript(
                select=[
                    "server",
                    "18",
                    "stop",
                    "fresh_backup",
                    "continue",  # update-all on_error
                ],
                text=[
                    "guarded mirror",  # name
                    DEFAULT,  # description
                    DEFAULT,  # source name -> live
                    DEFAULT,  # live db_container -> live-db
                    "production",  # live db_name
                    DEFAULT,  # live odoo_container
                    DEFAULT,  # owner
                    DEFAULT,  # data_dir
                    DEFAULT,  # backup_dir
                    DEFAULT,  # compression
                    "oops",  # 1st destination attempt: name
                    "live-db",  # SAME db_container as the source -> guard fires
                    "production",  # db_name
                    DEFAULT,  # odoo_container
                    DEFAULT,  # owner
                    DEFAULT,  # data_dir
                    DEFAULT,  # 2nd destination attempt: name -> test
                    DEFAULT,  # test db_container -> test-db
                    "production",  # db_name
                    DEFAULT,  # odoo_container
                    DEFAULT,  # owner
                    DEFAULT,  # data_dir
                    DEFAULT,  # restore template
                ],
                path=[str(tmp_path / "playbooks" / "guarded.yaml")],
                confirm=[
                    False,  # only_sql
                    False,  # adjust pattern
                    False,  # self-mirror confirm -> NO, re-ask destination
                    False,  # add another target?
                    True,  # drop
                    False,  # purge_master_data
                    True,  # restart
                    False,  # custom step
                    False,  # rpc block
                    False,  # vars
                    False,  # secrets
                    True,  # write
                ],
                checkbox=[
                    ["stop_before_restore", "start_after_restore", "neutralize", "update_all"],
                    ["deactivate_cron", "neutralize"],
                ],
            )
        )
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()

        config = load_playbook(str(tmp_path / "playbooks" / "guarded.yaml"))
        assert set(config.targets) == {"live", "test"}  # rejected 'oops' target was discarded
        restore = next(s for s in config.steps if s.command == "server.restore")
        assert restore.args["target"] == "test"

    def test_sanitize_selection_lands_in_restore_args(self, tmp_path, monkeypatch, install_script):
        prompts = _server_script(tmp_path)
        prompts.queues["checkbox"][1] = ["deactivate_cron", "anonymize", "wipe"]
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        restore = next(s for s in data["steps"] if s["command"] == "server.restore")
        assert restore["args"]["anonymize"] is True
        assert restore["args"]["wipe"] is True
        assert restore["args"]["neutralize"] is False

    def test_cancel_midway_exits_zero_without_output(self, tmp_path, monkeypatch, install_script):
        install_script(PromptScript(select=["server"]))

        def cancel(message, default=""):
            raise SystemExit(0)

        monkeypatch.setattr(f"{_PC}.text_input", cancel)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0
        assert not (tmp_path / "playbooks").exists()

    def test_summary_decline_writes_nothing(self, tmp_path, monkeypatch, install_script):
        prompts = _server_script(tmp_path)
        prompts.queues["confirm"][-1] = False  # decline "write this playbook?"
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0
        assert not (tmp_path / "playbooks" / "mirror.yaml").exists()


# =============================================================================
# Dev-mode happy path
# =============================================================================


def _dev_script(tmp_path) -> PromptScript:
    return PromptScript(
        select=[
            "dev",  # playbook type
            "18",  # version
            "stop",  # on_error
            "dev",  # start arg: mode
        ],
        text=[
            "daily update",  # name
            DEFAULT,  # description
        ],
        path=[
            DEFAULT,  # pull arg: config (empty -> omitted)
            DEFAULT,  # repos arg: config
            DEFAULT,  # start arg: config
            str(tmp_path / "playbooks" / "daily.yaml"),  # output path
        ],
        confirm=[
            False,  # pull verbose
            False,  # repos config-only
            False,  # repos server-only
            False,  # repos skip-access-check
            False,  # repos verbose
            False,  # add custom var
            False,  # generate secrets file
            True,  # write playbook
        ],
        checkbox=[["pull", "repos", "start"]],
    )


class TestDevWizard:
    def test_happy_path(self, tmp_path, monkeypatch, install_script):
        script = install_script(_dev_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()

        config = load_playbook(str(tmp_path / "playbooks" / "daily.yaml"))
        assert [step.command for step in config.steps] == ["pull", "repos", "start"]
        start = next(step for step in config.steps if step.command == "start")
        assert start.args == {"mode": "dev"}

    def test_empty_selection_falls_back_to_defaults(self, tmp_path, monkeypatch, install_script):
        prompts = _dev_script(tmp_path)
        prompts.queues["checkbox"] = [[]]
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        config = load_playbook(str(tmp_path / "playbooks" / "daily.yaml"))
        assert [step.command for step in config.steps] == ["pull", "repos", "start"]


# =============================================================================
# SQL statement builder + secrets step (unit level)
# =============================================================================


class TestSqlStatementBuilder:
    def test_presets_and_env_key_tracking(self, install_script):
        from odoodev.commands.playbook_cmd import _wizard_sql_statements

        script = install_script(
            PromptScript(
                select=["enterprise_code", "website_domain", "custom", "done"],
                text=[DEFAULT, "DELETE FROM ir_logging;"],  # website domain default, custom SQL
            )
        )
        pending: set[str] = set()
        statements = _wizard_sql_statements({"targets": {}}, pending)
        script.assert_drained()
        assert any("database.enterprise_code" in s for s in statements)
        assert any("UPDATE website SET domain" in s for s in statements)
        assert "{{ vars.customer }}" in next(s for s in statements if "website" in s)
        assert statements[-1] == "DELETE FROM ir_logging;"
        assert pending == {"PARTNER_ENTERPRISE_CODE"}


class TestSecretsStep:
    def _answers(self) -> dict:
        return {
            "schema_version": 1,
            "playbook_type": "server",
            "name": "mirror",
            "version": "18",
            "targets": {"test": {"db_container": "test-db", "db_name": "prod"}},
            "recipe": {
                "destination": "test",
                "sql_after_restore": {
                    "enabled": True,
                    "statements": ["UPDATE x SET y = '{{ env.PARTNER_ENTERPRISE_CODE }}';"],
                },
            },
            "_pending_env_keys": {"ODOO_PASSWORD"},
        }

    def test_detected_keys_are_prompted_and_masked(self, tmp_path, install_script):
        from odoodev.commands.playbook_cmd import _wizard_secrets

        env_path = tmp_path / "mirror.env"
        script = install_script(
            PromptScript(
                confirm=[True, False],  # generate yes, add-more no
                path=[str(env_path)],
                password=["rpc-secret", "enterprise-code-123"],  # sorted: PASSWORD, then CODE — both masked
            )
        )
        answers = self._answers()
        _wizard_secrets(answers)
        script.assert_drained()
        assert answers["env_file"]["generate"] is True
        assert answers["env_file"]["secrets"] == {
            "ODOO_PASSWORD": "rpc-secret",
            "PARTNER_ENTERPRISE_CODE": "enterprise-code-123",
        }

    def test_existing_file_merge_confirmed(self, tmp_path, install_script):
        from odoodev.commands.playbook_cmd import _wizard_secrets

        env_path = tmp_path / "mirror.env"
        env_path.write_text("KEEP_ME=yes\n")
        script = install_script(
            PromptScript(
                confirm=[True, False, True],  # generate, add-more, merge
                path=[str(env_path)],
                password=["code", "secret"],
            )
        )
        answers = self._answers()
        _wizard_secrets(answers)
        script.assert_drained()
        assert answers["env_file"]["_merge"] is True
        assert answers["env_file"]["generate"] is True

    def test_existing_file_merge_declined_skips_write(self, tmp_path, install_script):
        from odoodev.commands.playbook_cmd import _wizard_secrets

        env_path = tmp_path / "mirror.env"
        env_path.write_text("KEEP_ME=yes\n")
        script = install_script(
            PromptScript(
                confirm=[True, False, False],  # generate, add-more, merge declined
                path=[str(env_path)],
                password=["code", "secret"],
            )
        )
        answers = self._answers()
        _wizard_secrets(answers)
        script.assert_drained()
        assert answers["env_file"]["generate"] is False

    def test_no_values_entered_writes_no_file(self, tmp_path, install_script):
        from odoodev.commands.playbook_cmd import _wizard_secrets

        env_path = tmp_path / "mirror.env"
        script = install_script(
            PromptScript(
                confirm=[True, False],  # generate yes, add-more no
                path=[str(env_path)],
                password=["", ""],  # user skips both detected keys
            )
        )
        answers = self._answers()
        _wizard_secrets(answers)
        script.assert_drained()
        # env_file stays referenced (pending keys exist) but nothing is written.
        assert answers["env_file"]["generate"] is False
        assert "secrets" not in answers["env_file"]
        assert not env_path.exists()

    def test_declined_generation_keeps_path_reference(self, tmp_path, install_script):
        from odoodev.commands.playbook_cmd import _wizard_secrets

        script = install_script(PromptScript(confirm=[False], path=[str(tmp_path / "mirror.env")]))
        answers = self._answers()
        _wizard_secrets(answers)
        script.assert_drained()
        assert answers["env_file"]["generate"] is False
        assert answers["env_file"]["path"] == str(tmp_path / "mirror.env")
