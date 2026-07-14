"""Tests for the playbook assistant field schema (playbook_schema.py)."""

from __future__ import annotations

from odoodev.core.playbook import SERVER_COMMANDS, VALID_COMMANDS
from odoodev.core.playbook_schema import (
    DEV_STEP_GROUPS,
    DEV_STEP_ORDER,
    SANITIZE_FLAGS,
    SCHEMA_VERSION,
    SECTIONS,
    SQL_PRESETS,
    STEP_ARG_SPECS,
    wizard_schema,
)


class TestSchemaStructure:
    def test_schema_version_present(self):
        schema = wizard_schema()
        assert schema["schema_version"] == SCHEMA_VERSION
        assert schema["playbook_types"] == ["dev", "server"]

    def test_all_sections_present(self):
        keys = [section["key"] for section in wizard_schema()["sections"]]
        for expected in (
            "playbook_type",
            "common",
            "server_targets",
            "server_recipe",
            "server_extra_steps",
            "server_rpc",
            "vars",
            "dev_steps",
            "secrets",
            "output",
        ):
            assert expected in keys

    def test_applies_to_filtering(self):
        dev_keys = {s["key"] for s in wizard_schema("dev")["sections"]}
        server_keys = {s["key"] for s in wizard_schema("server")["sections"]}
        assert "server_targets" not in dev_keys
        assert "dev_steps" not in server_keys
        assert "common" in dev_keys and "common" in server_keys

    def test_every_field_has_mandatory_metadata(self):
        for section in wizard_schema()["sections"]:
            for field in list(section.get("fields", [])) + list(section.get("item_fields", [])):
                assert field["key"], f"field without key in section {section['key']}"
                assert field["type"], f"field {field['key']} without type"
                assert field["label_key"].startswith("playbook."), f"field {field['key']} label_key"

    def test_versions_choices_resolved(self):
        schema = wizard_schema()
        common = next(s for s in schema["sections"] if s["key"] == "common")
        version_field = next(f for f in common["fields"] if f["key"] == "version")
        assert isinstance(version_field["choices"], list) and version_field["choices"]

    def test_server_commands_choices_resolved(self):
        schema = wizard_schema()
        extra = next(s for s in schema["sections"] if s["key"] == "server_extra_steps")
        command_field = next(f for f in extra["item_fields"] if f["key"] == "command")
        assert set(command_field["choices"]) == set(SERVER_COMMANDS)

    def test_targets_source_stays_unresolved(self):
        schema = wizard_schema()
        recipe = next(s for s in schema["sections"] if s["key"] == "server_recipe")
        target_field = next(f for f in recipe["fields"] if f["key"] == "recipe.backup.target")
        assert target_field["choices_source"] == "targets"
        assert "choices" not in target_field

    def test_json_serializable(self):
        import json

        json.dumps(wizard_schema())

    def test_secret_field_flagged(self):
        secrets = next(s for s in wizard_schema()["sections"] if s["key"] == "secrets")
        values_field = next(f for f in secrets["fields"] if f["key"] == "env_file.secrets")
        assert values_field["secret"] is True


class TestStepArgSpecs:
    def test_every_valid_command_has_a_spec(self):
        assert set(STEP_ARG_SPECS) == set(VALID_COMMANDS)

    def test_modes_match_server_commands(self):
        for command, spec in STEP_ARG_SPECS.items():
            expected = "server" if command in SERVER_COMMANDS else "dev"
            assert spec.mode == expected, command

    def test_rebuild_spec_defaults(self):
        spec = STEP_ARG_SPECS["server.rebuild"]
        args = {a.name: a for a in spec.args}
        assert args["script_path"].default == "~/update_docker_odoo.py"
        assert args["config"].default == "~/docker2update.yaml"
        assert args["timeout"].default == 7200

    def test_restore_spec_covers_sanitize_flags(self):
        arg_names = {a.name for a in STEP_ARG_SPECS["server.restore"].args}
        for flag in SANITIZE_FLAGS:
            assert flag in arg_names


class TestPresetsAndGroups:
    def test_sql_presets_reference_known_env_keys(self):
        preset = SQL_PRESETS["enterprise_code"]
        assert "PARTNER_ENTERPRISE_CODE" in preset["env_keys"]
        assert any("database.enterprise_code" in s for s in preset["statements"])

    def test_website_preset_has_domain_prompt(self):
        preset = SQL_PRESETS["website_domain"]
        assert preset["prompt_key"] == "domain"
        assert "{domain}" in preset["statements"][0]

    def test_dev_groups_cover_only_dev_commands(self):
        grouped = {cmd for cmds in DEV_STEP_GROUPS.values() for cmd in cmds}
        assert grouped <= (VALID_COMMANDS - SERVER_COMMANDS)

    def test_dev_order_covers_all_grouped_commands(self):
        grouped = {cmd for cmds in DEV_STEP_GROUPS.values() for cmd in cmds}
        assert grouped <= set(DEV_STEP_ORDER)

    def test_sections_wizard_and_schema_share_source(self):
        # The dict output must mirror the dataclass source 1:1 (drift guard).
        assert len(wizard_schema()["sections"]) == len(SECTIONS)
