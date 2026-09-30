"""Tests for the interactive playbook assistant (commands/playbook_cmd.py wizard flow).

The output.py prompt wrappers imported into playbook_cmd are replaced with
queue-driven fakes — one queue per prompt kind, answers popped in call order.
The DEFAULT sentinel means "accept the prompt's default value".
"""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from odoodev import i18n
from odoodev.cli import cli
from odoodev.core.playbook import load_playbook

DEFAULT = object()

_PC = "odoodev.commands.playbook_cmd"


@pytest.fixture(autouse=True)
def _explicit_language(monkeypatch):
    """Pin the language explicitly so the wizard's language question never
    fires here — otherwise prompt queues would shift depending on whether the
    developer's machine has a ~/.config/odoodev/config.yaml."""
    monkeypatch.setenv("ODOODEV_LANG", "en")


@pytest.fixture(autouse=True)
def _bare_host(monkeypatch):
    """By default the wizard runs on a machine that is no ownERP server: no
    docker2update.yaml, no container2backup.yaml, no backups lying around —
    whatever the developer's home directory happens to contain."""
    monkeypatch.setattr(f"{_PC}.load_instances", lambda: [])
    monkeypatch.setattr(f"{_PC}.default_backup_dir", lambda: "/opt/backups/docker")
    monkeypatch.setattr(f"{_PC}.list_backups", lambda directory: [])


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
            ["rebuild", "stop_before_restore", "start_after_restore", "update_all"],  # recipe (no neutralize here)
            ["deactivate_cron", "neutralize"],  # what happens to the restored DB (drives server.neutralize)
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
        # The rebuild is the module update: it follows the restore and starts Odoo
        # itself, so no separate container.start is generated.
        assert commands == [
            "server.backup",
            "container.stop",
            "server.restore",
            "server.rebuild",
            "server.neutralize",
            "server.update-all",
        ]

    def test_default_selection_saves_updates_and_verifies(self, tmp_path, monkeypatch, install_script):
        prompts = _server_script(tmp_path)
        prompts.queues["checkbox"][0] = [
            "safety_backup",
            "stop_before_restore",
            "rebuild",
            "start_after_restore",
            "verify",
        ]
        prompts.queues["select"].remove("continue")  # no update-all -> no on_error question
        prompts.queues["confirm"].pop(4)  # ... and no "restart after update" question
        prompts.queues["text"].insert(16, DEFAULT)  # safety backup dir -> /opt/backups/docker
        script = install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        steps = data["steps"]
        assert [s["command"] for s in steps] == [
            "server.backup",
            "server.backup",
            "container.stop",
            "server.restore",
            "server.rebuild",
            "server.neutralize",
            "server.verify",
        ]
        # destination first (safety), source second — the restore takes the LAST backup file
        assert steps[0]["args"] == {
            "target": "test",
            "backup_dir": "/opt/backups/docker",
            "compression_level": 5,
            "safety": True,
        }
        assert steps[1]["args"]["target"] == "live"
        assert steps[6]["args"] == {"target": "test"}

    def test_fresh_backup_hands_file_to_restore(self, tmp_path, monkeypatch, install_script):
        install_script(_server_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        backup = next(s for s in data["steps"] if s["command"] == "server.backup")
        assert backup["args"]["target"] == "live"
        restore = next(s for s in data["steps"] if s["command"] == "server.restore")
        assert restore["args"]["target"] == "test"
        # No pattern guessing: the restore consumes the exact file the backup created.
        assert restore["args"]["backup_source"] == {"mode": "from_backup_step"}

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
                    ["stop_before_restore", "start_after_restore", "update_all"],
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
                    ["stop_before_restore", "start_after_restore", "update_all"],
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
        # ONE decision: neutralize deselected in the sanitize question -> no step either.
        assert "server.neutralize" not in [s["command"] for s in data["steps"]]

    def test_neutralize_selection_adds_the_step(self, tmp_path, monkeypatch, install_script):
        # neutralize is picked ONCE (sanitize question) and yields flag + step.
        install_script(_server_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        restore = next(s for s in data["steps"] if s["command"] == "server.restore")
        assert restore["args"]["neutralize"] is True
        assert "server.neutralize" in [s["command"] for s in data["steps"]]

    def test_neutralize_without_start_after_skips_step(self, tmp_path, monkeypatch, install_script):
        prompts = _server_script(tmp_path)
        # neither start_after nor rebuild (which starts Odoo itself) -> nothing is running afterwards
        prompts.queues["checkbox"][0] = ["stop_before_restore", "update_all"]
        del prompts.queues["text"][16:19]  # no rebuild script/config/timeout questions
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        commands = [s["command"] for s in data["steps"]]
        assert "container.start" not in commands
        # odoo-bin neutralize needs the running container -> step omitted, psql flag stays.
        assert "server.neutralize" not in commands
        restore = next(s for s in data["steps"] if s["command"] == "server.restore")
        assert restore["args"]["neutralize"] is True

    def test_rebuild_counts_as_running_for_neutralize(self, tmp_path, monkeypatch, install_script):
        prompts = _server_script(tmp_path)
        prompts.queues["checkbox"][0] = ["rebuild", "stop_before_restore", "update_all"]  # no start_after
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        data = yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])
        commands = [s["command"] for s in data["steps"]]
        assert "container.start" not in commands
        assert commands.index("server.rebuild") < commands.index("server.neutralize")

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

    def test_source_and_dest_prompts_use_role_labels(self, tmp_path, monkeypatch, install_script):
        script = install_script(_server_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output

        text_prompts = [message for kind, message in script.log if kind == "text"]
        assert i18n.MESSAGES["en"]["playbook.server.source.name"] in text_prompts
        assert i18n.MESSAGES["en"]["playbook.server.dest.name"] in text_prompts
        # the generic label is reserved for the optional extra-target loop
        assert i18n.MESSAGES["en"]["playbook.server.target.name"] not in text_prompts


# =============================================================================
# Language question
# =============================================================================


class TestLanguageQuestion:
    def test_asked_and_persisted_when_not_explicit(self, monkeypatch, install_script):
        from pathlib import Path

        from odoodev.commands import playbook_cmd
        from odoodev.core.global_config import GlobalConfig

        monkeypatch.setattr(i18n, "_explicit_language", False)
        monkeypatch.setattr(i18n, "_active_language", "en")
        saved = {}

        def fake_save(config):
            saved["config"] = config
            return Path("/tmp/config.yaml")

        monkeypatch.setattr("odoodev.core.global_config.load_global_config", lambda: GlobalConfig())
        monkeypatch.setattr("odoodev.core.global_config.save_global_config", fake_save)

        script = install_script(PromptScript(select=["de"], confirm=[True]))
        playbook_cmd._wizard_language()
        script.assert_drained()

        assert i18n.get_language() == "de"
        assert saved["config"].cli.language == "de"

    def test_decline_persist_keeps_language_for_session_only(self, monkeypatch, install_script):
        from odoodev.commands import playbook_cmd

        monkeypatch.setattr(i18n, "_explicit_language", False)
        monkeypatch.setattr(i18n, "_active_language", "en")

        def fail_save(config):  # pragma: no cover - must not be reached
            raise AssertionError("save_global_config must not be called")

        monkeypatch.setattr("odoodev.core.global_config.save_global_config", fail_save)

        script = install_script(PromptScript(select=["de"], confirm=[False]))
        playbook_cmd._wizard_language()
        script.assert_drained()
        assert i18n.get_language() == "de"

    def test_skipped_when_language_is_explicit(self, monkeypatch, install_script):
        from odoodev.commands import playbook_cmd

        monkeypatch.setattr(i18n, "_explicit_language", True)
        script = install_script(PromptScript())  # any prompt would fail the queue assert
        playbook_cmd._wizard_language()
        script.assert_drained()


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


# =============================================================================
# On an ownERP server: instances, backup directory and backups are offered
# =============================================================================


def _instances():
    from odoodev.core.server_inventory import Instance

    return [
        Instance("live-odoo", "acme_prod", "live-db", data_dir="/opt/odoo/live", odoo_version="19"),
        Instance("test-odoo", "acme_test", "test-db", data_dir="/opt/odoo/test", odoo_version="19", active=False),
    ]


def _inventory_script(tmp_path, **overrides) -> PromptScript:
    """Live -> test mirror where both ends are picked from docker2update.yaml."""
    queues = {
        "select": [
            "server",
            DEFAULT,  # version: preselected from the server's configuration
            "stop",
            "fresh_backup",
            "live-odoo",  # SOURCE instance
            "test-odoo",  # DESTINATION instance
        ],
        "text": [
            "mirror",  # name
            DEFAULT,  # description
            DEFAULT,  # backup_dir -> from container2backup.yaml
            DEFAULT,  # compression level
            DEFAULT,  # safety backup dir -> same directory
            DEFAULT,  # rebuild script_path
            DEFAULT,  # rebuild config
            DEFAULT,  # rebuild timeout
            DEFAULT,  # restore template
        ],
        "path": [str(tmp_path / "playbooks" / "mirror.yaml")],
        "confirm": [
            False,  # only_sql
            False,  # add another target?
            True,  # drop
            False,  # purge_master_data
            False,  # add custom step
            False,  # configure rpc block
            False,  # add custom var
            False,  # generate secrets file
            True,  # write playbook
        ],
        "checkbox": [
            ["safety_backup", "stop_before_restore", "rebuild", "verify"],
            ["deactivate_cron"],
        ],
    }
    queues.update(overrides)
    return PromptScript(**queues)


class TestServerInventory:
    @pytest.fixture(autouse=True)
    def _ownerp_host(self, monkeypatch):
        monkeypatch.setattr(f"{_PC}.load_instances", _instances)
        monkeypatch.setattr(f"{_PC}.default_backup_dir", lambda: "/srv/backups/docker")
        monkeypatch.setattr(f"{_PC}._report_preflight", lambda path: None)

    def _data(self, tmp_path) -> dict:
        return yaml.safe_load((tmp_path / "playbooks" / "mirror.yaml").read_text().split("\n", 1)[1])

    def test_both_ends_come_from_the_update_configuration(self, tmp_path, monkeypatch, install_script):
        script = install_script(_inventory_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()  # not one container, database or directory had to be typed

        data = self._data(tmp_path)
        assert data["version"] == "19"
        assert data["targets"] == {
            "live": {
                "db_container": "live-db",
                "db_name": "acme_prod",
                "odoo_container": "live-odoo",
                "data_dir": "/opt/odoo/live",
            },
            "test": {
                "db_container": "test-db",
                "db_name": "acme_test",
                "odoo_container": "test-odoo",
                "data_dir": "/opt/odoo/test",
            },
        }
        steps = {s["name"]: s for s in data["steps"]}
        backups = [s for s in data["steps"] if s["command"] == "server.backup"]
        assert [b["args"]["target"] for b in backups] == ["test", "live"]
        assert {b["args"]["backup_dir"] for b in backups} == {"/srv/backups/docker"}
        assert "Restore backup into test" in steps

    def test_the_source_instance_is_not_offered_as_destination(self, tmp_path, monkeypatch, install_script):
        script = install_script(_inventory_script(tmp_path))
        _run_create(tmp_path, monkeypatch)
        dest_prompt = [msg for kind, msg in script.log if kind == "select" and "DESTINATION" in msg]
        assert len(dest_prompt) == 1
        # the fake select cannot see choices; the exclusion is asserted on the helper itself
        from odoodev.commands import playbook_cmd as pc

        seen = {}
        monkeypatch.setattr(
            pc,
            "select",
            lambda message, choices=None, default=None: (
                seen.setdefault("values", [c.value for c in choices]) and "test-odoo"
            ),
        )
        answers = {"targets": {}, "version": "19"}
        assert (
            pc._pick_instance(answers, _instances(), "playbook.server.inventory.pick_dest", exclude=("live-odoo",))
            == "test"
        )
        assert seen["values"] == ["test-odoo", pc._MANUAL]

    def test_manual_entry_stays_possible(self, tmp_path, monkeypatch, install_script):
        prompts = _inventory_script(tmp_path)
        prompts.queues["select"][5] = "__manual__"  # destination by hand
        prompts.queues["text"][4:4] = [
            "stage",  # destination target name
            "stage-db",
            "staging",
            "stage-odoo",
            DEFAULT,  # owner
            "/opt/odoo/stage",
        ]
        script = install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()
        assert self._data(tmp_path)["targets"]["stage"]["db_name"] == "staging"

    def test_version_disagreement_is_said_at_once(self, tmp_path, monkeypatch, install_script):
        prompts = _inventory_script(tmp_path)
        prompts.queues["select"][1] = "18"
        install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "configured as Odoo 19" in result.output.replace("\n", " ")

    def test_existing_backup_is_picked_from_a_list(self, tmp_path, monkeypatch, install_script):
        from odoodev.core.server_inventory import BackupFile

        listed = {}

        def fake_list(directory):
            listed["directory"] = directory
            return [
                BackupFile(
                    "/srv/backups/docker/acme_prod_live-odoo_dockerbackup_2026-09-30_02-00-00.tar.zst",
                    9 * 1024**3,
                    1.0e9,
                ),
                BackupFile("/srv/backups/docker/older.tar.zst", 8 * 1024**3, 0.9e9),
            ]

        monkeypatch.setattr(f"{_PC}.list_backups", fake_list)
        prompts = _inventory_script(tmp_path)
        prompts.queues["select"] = [
            "server",
            DEFAULT,
            "stop",
            "existing_file",
            "/srv/backups/docker/older.tar.zst",  # the file, picked — not typed
            "live-odoo",  # destination: nothing is excluded, there is no source instance
        ]
        del prompts.queues["text"][2:4]  # no backup dir / compression questions
        prompts.queues["confirm"].pop(0)  # no only_sql question
        script = install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()
        assert listed["directory"] == "/srv/backups/docker"
        restore = next(s for s in self._data(tmp_path)["steps"] if s["command"] == "server.restore")
        assert restore["args"]["backup_source"] == {"mode": "file", "path": "/srv/backups/docker/older.tar.zst"}
        assert restore["args"]["target"] == "live"

    def test_no_backups_found_falls_back_to_typing_the_path(self, tmp_path, monkeypatch, install_script):
        prompts = _inventory_script(tmp_path)
        prompts.queues["select"] = ["server", DEFAULT, "stop", "existing_file", "live-odoo"]
        prompts.queues["text"][2:4] = ["/root/dump.tar.zst"]  # the path, instead of backup dir + compression
        prompts.queues["confirm"].pop(0)
        script = install_script(prompts)
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        script.assert_drained()
        restore = next(s for s in self._data(tmp_path)["steps"] if s["command"] == "server.restore")
        assert restore["args"]["backup_source"]["path"] == "/root/dump.tar.zst"


class TestPreflightReport:
    def _run(self, tmp_path, monkeypatch, install_script, preflight_result):
        from odoodev.core.playbook import PlaybookRunner

        monkeypatch.setattr(PlaybookRunner, "_preflight", lambda self, config, version, context: preflight_result)
        install_script(_server_script(tmp_path))
        return _run_create(tmp_path, monkeypatch)

    def test_findings_are_shown_and_the_playbook_is_still_written(self, tmp_path, monkeypatch, install_script):
        from odoodev.core.playbook import StepResult

        finding = StepResult(
            name="Preflight",
            command="preflight",
            status="error",
            message="[error] ~/docker2update.yaml has odoo_version '18' for 'test-odoo'\n[warning] never updated",
            exit_code=1,
            duration_ms=1,
        )
        result = self._run(tmp_path, monkeypatch, install_script, finding)
        assert result.exit_code == 0, result.output
        assert (tmp_path / "playbooks" / "mirror.yaml").exists()
        flat = result.output.replace("\n", " ")
        assert "odoo_version '18'" in flat
        assert "never updated" in flat
        assert "stops the run before its first step" in flat

    def test_clean_host_says_what_the_check_covers(self, tmp_path, monkeypatch, install_script):
        result = self._run(tmp_path, monkeypatch, install_script, None)
        assert result.exit_code == 0, result.output
        assert "no findings" in result.output.replace("\n", " ")

    def test_a_crashing_check_does_not_lose_the_playbook(self, tmp_path, monkeypatch, install_script):
        from odoodev.core.playbook import PlaybookRunner

        def boom(self, config, version, context):
            raise RuntimeError("docker exploded")

        monkeypatch.setattr(PlaybookRunner, "_preflight", boom)
        install_script(_server_script(tmp_path))
        result = _run_create(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert (tmp_path / "playbooks" / "mirror.yaml").exists()
        assert "docker exploded" in result.output
