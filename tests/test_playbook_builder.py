"""Tests for the playbook assistant's pure generator core (playbook_builder.py)."""

from __future__ import annotations

import json
import os

import pytest
import yaml

from odoodev.core.playbook import PlaybookValidationError, _validate_playbook
from odoodev.core.playbook_builder import (
    AnswersValidationError,
    answers_from_file,
    build_env_file_content,
    build_playbook_dict,
    default_output_path,
    find_env_references,
    render_playbook_yaml,
    slugify,
    validate_answers,
    validate_generated,
    write_env_file,
)


def server_answers() -> dict:
    """A full server-mirror answers dict (mirrors usage/playbook.md reference)."""
    return {
        "schema_version": 1,
        "playbook_type": "server",
        "name": "live-test-mirror",
        "description": "Mirror the live database to the test system",
        "version": "18",
        "on_error": "stop",
        "targets": {
            "live": {"db_container": "live-db", "odoo_container": "live-odoo", "db_name": "production"},
            "test": {
                "db_container": "test-db",
                "odoo_container": "test-odoo",
                "db_name": "production",
                "data_dir": "/opt/odoo/test",
            },
        },
        "rpc": {"enabled": True, "host": "{{ env.ODOO_URL }}", "db": "production"},
        "vars": {"customer": "acme"},
        "recipe": {
            "backup": {"enabled": True, "target": "live", "backup_dir": "/opt/backups/docker", "compression_level": 5},
            "rebuild": {"enabled": True, "target": "test", "timeout": 7200},
            "stop_before_restore": True,
            "restore": {
                "enabled": True,
                "target": "test",
                "backup_source": {
                    "mode": "newest_in_dir",
                    "dir": "/opt/backups/docker",
                    "pattern": "production_*_dockerbackup_*.tar.zst",
                    "select_by": "mtime",
                },
                "sanitize_flags": ["deactivate_cron", "neutralize"],
                "purge_master_data": False,
            },
            "sql_after_restore": {
                "enabled": True,
                "on_error": "continue",
                "statements": [
                    "UPDATE ir_config_parameter SET value = '{{ env.PARTNER_ENTERPRISE_CODE }}' "
                    "WHERE key = 'database.enterprise_code';",
                    "UPDATE website SET domain = 'https://{{ vars.customer }}-test.ownerp.app';",
                ],
            },
            "start_after_restore": True,
            "neutralize": {"enabled": True},
            "update_all": {"enabled": True, "restart": True, "on_error": "continue"},
            "rpc_call": {
                "enabled": True,
                "model": "ir.config_parameter",
                "mode": "method",
                "method": "set_param",
                "args": ["mail.catchall.domain", "{{ vars.customer }}-test.ownerp.app"],
            },
        },
        "extra_steps": [],
        "env_file": {"path": "/root/.config/odoodev/mirror.env", "generate": False},
        "output_path": "./playbooks/live-test-mirror.yaml",
    }


def dev_answers() -> dict:
    return {
        "schema_version": 1,
        "playbook_type": "dev",
        "name": "daily update",
        "version": "18",
        "on_error": "stop",
        "dev_steps": [
            {"command": "start", "args": {"mode": "dev"}},
            {"command": "pull"},
            {"command": "docker.up"},
        ],
        "env_file": {},
        "output_path": "./playbooks/daily-update.yaml",
    }


# =============================================================================
# build_playbook_dict — round-trip through the runner's own validation
# =============================================================================


class TestBuildServerPlaybook:
    def test_round_trip_is_loadable(self):
        playbook = build_playbook_dict(server_answers())
        rendered = render_playbook_yaml(playbook)
        reloaded = yaml.safe_load(rendered)
        config = _validate_playbook(reloaded)
        assert config.version == "18"
        assert set(config.targets) == {"live", "test"}

    def test_step_order_matches_recipe_guardrails(self):
        playbook = build_playbook_dict(server_answers())
        commands = [step["command"] for step in playbook["steps"]]
        assert commands == [
            "server.backup",
            "server.rebuild",
            "container.stop",
            "server.restore",
            "sql.execute",
            "container.start",
            "server.neutralize",
            "server.update-all",
            "rpc.execute",
        ]

    def test_disabled_recipe_items_are_skipped(self):
        answers = server_answers()
        answers["recipe"]["rebuild"]["enabled"] = False
        answers["recipe"]["sql_after_restore"]["enabled"] = False
        answers["recipe"]["rpc_call"]["enabled"] = False
        commands = [step["command"] for step in build_playbook_dict(answers)["steps"]]
        assert "server.rebuild" not in commands
        assert "sql.execute" not in commands
        assert "rpc.execute" not in commands

    def test_sanitize_flags_land_in_restore_args(self):
        answers = server_answers()
        answers["recipe"]["restore"]["sanitize_flags"] = ["deactivate_cron", "anonymize", "purge_transactions"]
        playbook = build_playbook_dict(answers)
        restore = next(s for s in playbook["steps"] if s["command"] == "server.restore")
        assert restore["args"]["deactivate_cron"] is True
        assert restore["args"]["anonymize"] is True
        assert restore["args"]["neutralize"] is False
        assert restore["args"]["wipe"] is False
        assert restore["args"]["purge_transactions"] is True
        assert "purge_master_data" not in restore["args"]

    def test_rebuild_defaults_omitted(self):
        playbook = build_playbook_dict(server_answers())
        rebuild = next(s for s in playbook["steps"] if s["command"] == "server.rebuild")
        assert rebuild["args"] == {"target": "test"}

    def test_rebuild_non_defaults_kept(self):
        answers = server_answers()
        answers["recipe"]["rebuild"].update({"script_path": "/opt/update.py", "timeout": 3600})
        playbook = build_playbook_dict(answers)
        rebuild = next(s for s in playbook["steps"] if s["command"] == "server.rebuild")
        assert rebuild["args"]["script_path"] == "/opt/update.py"
        assert rebuild["args"]["timeout"] == 3600

    def test_rpc_connection_block_included_when_enabled(self):
        playbook = build_playbook_dict(server_answers())
        assert playbook["rpc"] == {"host": "{{ env.ODOO_URL }}", "db": "production"}

    def test_rpc_connection_block_omitted_when_disabled(self):
        answers = server_answers()
        answers["rpc"]["enabled"] = False
        assert "rpc" not in build_playbook_dict(answers)

    def test_rpc_call_domain_values_form(self):
        answers = server_answers()
        answers["recipe"]["rpc_call"] = {
            "enabled": True,
            "model": "res.partner",
            "mode": "domain_values",
            "domain": [["is_company", "=", True]],
            "values": {"website": "https://example.com"},
        }
        playbook = build_playbook_dict(answers)
        rpc = next(s for s in playbook["steps"] if s["command"] == "rpc.execute")
        assert rpc["args"] == {
            "model": "res.partner",
            "domain": [["is_company", "=", True]],
            "values": {"website": "https://example.com"},
        }

    def test_extra_steps_appended(self):
        answers = server_answers()
        answers["extra_steps"] = [
            {
                "command": "sql.execute",
                "name": "Custom",
                "args": {"target": "test", "statements": ["SELECT 1;"]},
                "on_error": "continue",
            },
        ]
        playbook = build_playbook_dict(answers)
        assert playbook["steps"][-1]["command"] == "sql.execute"
        assert playbook["steps"][-1]["on_error"] == "continue"
        validate_generated(playbook)

    def test_default_owner_omitted_from_targets(self):
        answers = server_answers()
        answers["targets"]["live"]["owner"] = "ownerp"
        answers["targets"]["test"]["owner"] = "custom"
        playbook = build_playbook_dict(answers)
        assert "owner" not in playbook["targets"]["live"]
        assert playbook["targets"]["test"]["owner"] == "custom"

    def test_file_mode_backup_source(self):
        answers = server_answers()
        answers["recipe"]["restore"]["backup_source"] = {"mode": "file", "path": "/opt/backups/fixed.tar.zst"}
        playbook = build_playbook_dict(answers)
        restore = next(s for s in playbook["steps"] if s["command"] == "server.restore")
        assert restore["args"]["backup_source"] == {"mode": "file", "path": "/opt/backups/fixed.tar.zst"}
        validate_generated(playbook)


class TestBuildDevPlaybook:
    def test_round_trip_is_loadable(self):
        playbook = build_playbook_dict(dev_answers())
        config = _validate_playbook(yaml.safe_load(render_playbook_yaml(playbook)))
        assert len(config.steps) == 3

    def test_canonical_execution_order(self):
        playbook = build_playbook_dict(dev_answers())
        commands = [step["command"] for step in playbook["steps"]]
        assert commands == ["docker.up", "pull", "start"]

    def test_args_preserved(self):
        playbook = build_playbook_dict(dev_answers())
        start = next(s for s in playbook["steps"] if s["command"] == "start")
        assert start["args"] == {"mode": "dev"}

    def test_plain_string_steps_accepted(self):
        answers = dev_answers()
        answers["dev_steps"] = ["pull", "repos"]
        playbook = build_playbook_dict(answers)
        assert [s["command"] for s in playbook["steps"]] == ["pull", "repos"]


# =============================================================================
# validate_generated / render_playbook_yaml
# =============================================================================


class TestValidationAndRendering:
    def test_validate_generated_catches_broken_target(self):
        playbook = build_playbook_dict(server_answers())
        del playbook["targets"]["test"]["db_container"]
        with pytest.raises(PlaybookValidationError, match="generated playbook failed validation"):
            validate_generated(playbook)

    def test_validate_generated_catches_unknown_command(self):
        playbook = build_playbook_dict(dev_answers())
        playbook["steps"][0]["command"] = "does.not.exist"
        with pytest.raises(PlaybookValidationError):
            validate_generated(playbook)

    def test_render_has_header_comment(self):
        rendered = render_playbook_yaml({"version": "18", "steps": []})
        assert rendered.startswith("# Generated by: odoodev playbook create\n")

    def test_render_preserves_insertion_order(self):
        rendered = render_playbook_yaml(build_playbook_dict(server_answers()))
        assert rendered.index("version:") < rendered.index("targets:") < rendered.index("steps:")


# =============================================================================
# answers validation
# =============================================================================


class TestValidateAnswers:
    def test_valid_answers_have_no_problems(self):
        assert validate_answers(server_answers()) == []
        assert validate_answers(dev_answers()) == []

    def test_all_problems_collected(self):
        problems = validate_answers({"schema_version": 99, "playbook_type": "nope"})
        assert len(problems) >= 3  # schema_version, playbook_type, name, version

    def test_schema_version_mismatch(self):
        answers = server_answers()
        answers["schema_version"] = 99
        assert any("schema_version" in p for p in validate_answers(answers))

    def test_schema_version_1_still_accepted(self):
        # v1 answers files (0.54.0) stay valid — the answers format is unchanged.
        answers = server_answers()
        answers["schema_version"] = 1
        assert validate_answers(answers) == []

    def test_self_mirror_is_rejected(self):
        # v0.54.0 failure mode: backup source == restore destination.
        answers = server_answers()
        answers["recipe"]["backup"]["target"] = "test"
        assert any("same target" in p for p in validate_answers(answers))

    def test_self_mirror_via_destination_key(self):
        answers = server_answers()
        answers["recipe"]["destination"] = "live"
        answers["recipe"]["restore"].pop("target", None)
        assert any("same target" in p for p in validate_answers(answers))

    def test_backup_without_restore_is_fine(self):
        # Pure backup playbook (no restore) may keep any target.
        answers = server_answers()
        answers["recipe"]["restore"]["enabled"] = False
        answers["recipe"]["backup"]["target"] = "test"
        answers["recipe"]["destination"] = "test"
        assert validate_answers(answers) == []

    def test_server_requires_targets(self):
        answers = server_answers()
        answers["targets"] = {}
        assert any("targets" in p for p in validate_answers(answers))

    def test_target_missing_db_container(self):
        answers = server_answers()
        del answers["targets"]["live"]["db_container"]
        assert any("db_container" in p for p in validate_answers(answers))

    def test_unknown_recipe_target_reference(self):
        answers = server_answers()
        answers["recipe"]["restore"]["target"] = "staging"
        assert any("staging" in p for p in validate_answers(answers))

    def test_backup_requires_dir(self):
        answers = server_answers()
        answers["recipe"]["backup"]["backup_dir"] = ""
        assert any("backup_dir" in p for p in validate_answers(answers))

    def test_restore_file_mode_requires_path(self):
        answers = server_answers()
        answers["recipe"]["restore"]["backup_source"] = {"mode": "file"}
        assert any("'file' requires 'path'" in p for p in validate_answers(answers))

    def test_unknown_sanitize_flag(self):
        answers = server_answers()
        answers["recipe"]["restore"]["sanitize_flags"] = ["deactivate_cron", "shred_everything"]
        assert any("shred_everything" in p for p in validate_answers(answers))

    def test_rpc_call_requires_model(self):
        answers = server_answers()
        answers["recipe"]["rpc_call"]["model"] = ""
        assert any("model" in p for p in validate_answers(answers))

    def test_extra_step_unknown_command(self):
        answers = server_answers()
        answers["extra_steps"] = [{"command": "bogus.command"}]
        assert any("bogus.command" in p for p in validate_answers(answers))

    def test_dev_rejects_server_steps(self):
        answers = dev_answers()
        answers["dev_steps"] = [{"command": "server.restore"}]
        assert any("server-mode step" in p for p in validate_answers(answers))

    def test_dev_allows_sql_execute(self):
        answers = dev_answers()
        answers["dev_steps"] = [{"command": "sql.execute", "args": {"db_name": "x", "statements": ["SELECT 1;"]}}]
        assert validate_answers(answers) == []

    def test_env_file_generate_requires_path(self):
        answers = server_answers()
        answers["env_file"] = {"generate": True, "path": ""}
        assert any("env_file.path" in p for p in validate_answers(answers))

    def test_invalid_secret_name(self):
        answers = server_answers()
        answers["env_file"] = {"generate": True, "path": "/tmp/x.env", "secrets": {"BAD NAME": "x"}}
        assert any("BAD NAME" in p for p in validate_answers(answers))


class TestAnswersFromFile:
    def test_valid_file(self, tmp_path):
        path = tmp_path / "answers.json"
        path.write_text(json.dumps(server_answers()))
        answers = answers_from_file(str(path))
        assert answers["name"] == "live-test-mirror"

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "answers.json"
        path.write_text("{not json")
        with pytest.raises(AnswersValidationError, match="not valid JSON"):
            answers_from_file(str(path))

    def test_non_object_top_level(self, tmp_path):
        path = tmp_path / "answers.json"
        path.write_text("[1, 2]")
        with pytest.raises(AnswersValidationError, match="JSON object"):
            answers_from_file(str(path))

    def test_problems_are_collected(self, tmp_path):
        path = tmp_path / "answers.json"
        path.write_text(json.dumps({"schema_version": 1, "playbook_type": "server"}))
        with pytest.raises(AnswersValidationError) as excinfo:
            answers_from_file(str(path))
        assert len(excinfo.value.problems) >= 3


# =============================================================================
# helpers: env references, slug, output path
# =============================================================================


class TestHelpers:
    def test_find_env_references_nested(self):
        playbook = build_playbook_dict(server_answers())
        refs = find_env_references(playbook)
        assert "ODOO_URL" in refs
        assert "PARTNER_ENTERPRISE_CODE" in refs

    def test_find_env_references_ignores_vars(self):
        refs = find_env_references({"a": "{{ vars.customer }}", "b": ["{{ env.SECRET_X }}"]})
        assert refs == {"SECRET_X"}

    def test_slugify(self):
        assert slugify("Live Test Mirror!") == "live-test-mirror"
        assert slugify("  Ümlaut  Näme ") == "mlaut-n-me"
        assert slugify("///") == "playbook"

    def test_default_output_path(self):
        assert default_output_path("Live Mirror") == os.path.join(".", "playbooks", "live-mirror.yaml")


# =============================================================================
# secrets env_file
# =============================================================================


class TestEnvFile:
    def test_content_format(self):
        content = build_env_file_content({"ODOO_URL": "https://acme.test", "ODOO_PASSWORD": "s3cret"})
        assert "ODOO_URL=https://acme.test" in content
        assert "ODOO_PASSWORD=s3cret" in content
        assert content.startswith("# Generated by: odoodev playbook create")

    def test_values_with_spaces_are_quoted(self):
        content = build_env_file_content({"NOTE": "hello world # not a comment"})
        assert 'NOTE="hello world # not a comment"' in content

    def test_invalid_name_rejected(self):
        with pytest.raises(ValueError, match="invalid env variable name"):
            build_env_file_content({"BAD NAME": "x"})

    def test_newline_value_rejected(self):
        with pytest.raises(ValueError, match="newlines"):
            build_env_file_content({"KEY": "a\nb"})

    def test_write_sets_0600_permissions(self, tmp_path):
        target = tmp_path / "secrets" / "mirror.env"
        written = write_env_file(str(target), {"ODOO_PASSWORD": "x"})
        assert written.exists()
        assert oct(os.stat(written).st_mode)[-3:] == "600"

    def test_merge_keeps_existing_keys(self, tmp_path):
        target = tmp_path / "mirror.env"
        write_env_file(str(target), {"ODOO_URL": "https://old.example", "KEEP_ME": "yes"})
        write_env_file(str(target), {"ODOO_URL": "https://new.example"}, merge_existing=True)
        from dotenv import dotenv_values

        values = dotenv_values(target)
        assert values["ODOO_URL"] == "https://new.example"
        assert values["KEEP_ME"] == "yes"
        assert oct(os.stat(target).st_mode)[-3:] == "600"

    def test_overwrite_without_merge_replaces(self, tmp_path):
        target = tmp_path / "mirror.env"
        write_env_file(str(target), {"OLD_KEY": "x"})
        write_env_file(str(target), {"NEW_KEY": "y"})
        from dotenv import dotenv_values

        values = dotenv_values(target)
        assert "OLD_KEY" not in values
        assert values["NEW_KEY"] == "y"

    def test_quoted_value_round_trips_through_dotenv(self, tmp_path):
        target = tmp_path / "mirror.env"
        write_env_file(str(target), {"NOTE": 'va"lue with space'})
        from dotenv import dotenv_values

        assert dotenv_values(target)["NOTE"] == 'va"lue with space'
