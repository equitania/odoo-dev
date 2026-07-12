"""Tests for the server-mode playbook schema (targets, env_file, rpc, recursive rendering)."""

from __future__ import annotations

import pytest

from odoodev.core.playbook import (
    VALID_COMMANDS,
    PlaybookValidationError,
    TargetConfig,
    _inject_target_context,
    _resolve_rpc_config,
    build_template_context,
    load_env_file,
    load_playbook,
    render_step_args,
)


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


SERVER_PLAYBOOK = """
version: "18"
description: "mirror"
env_file: ""
targets:
  live:
    db_container: live-db
    odoo_container: live-odoo
    db_name: production
  test:
    db_container: test-db
    odoo_container: test-odoo
    db_name: production
    owner: custom
    data_dir: /opt/odoo/test
steps:
  - name: "stop"
    command: container.stop
    args: { target: test, component: odoo }
"""


# --- VALID_COMMANDS ---


def test_valid_commands_contain_server_steps():
    for cmd in (
        "container.stop",
        "container.start",
        "server.backup",
        "server.restore",
        "server.neutralize",
        "server.update-all",
        "sql.execute",
        "rpc.execute",
    ):
        assert cmd in VALID_COMMANDS


# --- targets parsing ---


def test_load_playbook_with_targets(tmp_path):
    path = _write(tmp_path, "pb.yaml", SERVER_PLAYBOOK)
    pb = load_playbook(path)
    assert set(pb.targets) == {"live", "test"}
    live = pb.targets["live"]
    assert live.db_container == "live-db"
    assert live.odoo_container == "live-odoo"
    assert live.db_name == "production"
    assert live.owner == "ownerp"  # default
    assert live.data_dir == ""
    test = pb.targets["test"]
    assert test.owner == "custom"
    assert test.data_dir == "/opt/odoo/test"


def test_playbook_without_targets_still_loads(tmp_path):
    path = _write(tmp_path, "pb.yaml", 'version: "18"\nsteps:\n  - command: db.list\n')
    pb = load_playbook(path)
    assert pb.targets == {}
    assert pb.env_file == ""
    assert pb.rpc == {}


def test_target_missing_db_container_raises(tmp_path):
    content = 'version: "18"\ntargets:\n  t: { db_name: x }\nsteps:\n  - command: db.list\n'
    with pytest.raises(PlaybookValidationError, match="db_container"):
        load_playbook(_write(tmp_path, "pb.yaml", content))


def test_target_missing_db_name_raises(tmp_path):
    content = 'version: "18"\ntargets:\n  t: { db_container: x }\nsteps:\n  - command: db.list\n'
    with pytest.raises(PlaybookValidationError, match="db_name"):
        load_playbook(_write(tmp_path, "pb.yaml", content))


def test_targets_not_mapping_raises(tmp_path):
    content = 'version: "18"\ntargets: [a, b]\nsteps:\n  - command: db.list\n'
    with pytest.raises(PlaybookValidationError, match="targets"):
        load_playbook(_write(tmp_path, "pb.yaml", content))


# --- env_file ---


def test_load_env_file(tmp_path):
    path = _write(tmp_path, "mirror.env", "ODOO_USER=admin\nODOO_PASSWORD=secret\n# comment\n")
    values = load_env_file(path)
    assert values == {"ODOO_USER": "admin", "ODOO_PASSWORD": "secret"}


def test_load_env_file_missing_raises():
    with pytest.raises(PlaybookValidationError, match="env_file not found"):
        load_env_file("/nonexistent/mirror.env")


def test_env_file_values_win_over_process_env(monkeypatch):
    monkeypatch.setenv("MIRROR_KEY", "from-process")
    context = build_template_context({}, None, {"MIRROR_KEY": "from-file"})
    assert context["env"]["MIRROR_KEY"] == "from-file"


def test_build_template_context_backward_compatible(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "x")
    context = build_template_context({"a": "1"}, {"a": "2"})
    assert context["vars"]["a"] == "2"
    assert context["env"]["SOME_VAR"] == "x"


# --- recursive rendering ---


def test_render_step_args_recursive_nested(monkeypatch):
    context = build_template_context({"customer": "acme"}, None, {"CODE": "M123"})
    args = {
        "backup_source": {"dir": "/opt/backups", "pattern": "{{ vars.customer }}_*.tar.zst"},
        "statements": [
            "UPDATE x SET v = '{{ env.CODE }}';",
            "UPDATE y SET d = 'https://{{ vars.customer }}-test.example';",
        ],
        "drop": True,
        "level": 5,
    }
    rendered = render_step_args(args, context)
    assert rendered["backup_source"]["pattern"] == "acme_*.tar.zst"
    assert rendered["statements"][0] == "UPDATE x SET v = 'M123';"
    assert rendered["statements"][1] == "UPDATE y SET d = 'https://acme-test.example';"
    assert rendered["drop"] is True
    assert rendered["level"] == 5


def test_render_step_args_template_error_in_nested_value():
    context = build_template_context({}, None)
    with pytest.raises(PlaybookValidationError, match="statements\\[0\\]"):
        render_step_args({"statements": ["{{ broken"]}, context)


# --- _inject_target_context ---


_TARGETS = {
    "test": TargetConfig(
        db_container="test-db",
        db_name="production",
        odoo_container="test-odoo",
        owner="ownerp",
        data_dir="/opt/odoo/test",
    )
}


def test_inject_target_noop_without_target_key():
    args = {"name": "x"}
    assert _inject_target_context(args, _TARGETS) is args


def test_inject_target_merges_flat_keys():
    result = _inject_target_context({"target": "test"}, _TARGETS)
    assert result["db_container"] == "test-db"
    assert result["odoo_container"] == "test-odoo"
    assert result["db_name"] == "production"
    assert result["owner"] == "ownerp"
    assert result["data_dir"] == "/opt/odoo/test"
    assert result["target"] == "test"


def test_inject_target_explicit_args_win():
    result = _inject_target_context({"target": "test", "db_name": "other"}, _TARGETS)
    assert result["db_name"] == "other"


def test_inject_target_unknown_raises():
    with pytest.raises(PlaybookValidationError, match="Unknown target 'live'"):
        _inject_target_context({"target": "live"}, _TARGETS)


# --- rpc config resolution ---


def test_resolve_rpc_config_env_fallbacks():
    context = build_template_context(
        {},
        None,
        {
            "ODOO_URL": "https://test.example.com",
            "ODOO_PORT": "443",
            "ODOO_USER": "admin",
            "ODOO_PASSWORD": "secret",
            "ODOO_DATABASE": "production",
        },
    )
    resolved = _resolve_rpc_config({}, context)
    assert resolved["host"] == "https://test.example.com"
    assert resolved["port"] == "443"
    assert resolved["user"] == "admin"
    assert resolved["password"] == "secret"
    assert resolved["db"] == "production"


def test_resolve_rpc_config_section_wins_over_env():
    context = build_template_context({}, None, {"ODOO_DATABASE": "env-db", "ODOO_USER": "env-user"})
    resolved = _resolve_rpc_config({"db": "section-db"}, context)
    assert resolved["db"] == "section-db"
    assert resolved["user"] == "env-user"


def test_resolve_rpc_config_renders_templates():
    context = build_template_context({"db": "prod"}, None, {"ODOO_URL": "https://x.example"})
    resolved = _resolve_rpc_config({"host": "{{ env.ODOO_URL }}", "db": "{{ vars.db }}"}, context)
    assert resolved["host"] == "https://x.example"
    assert resolved["db"] == "prod"


# --- runner integration (dry-run, no docker needed) ---


def test_server_playbook_dry_run(tmp_path):
    from odoodev.core.playbook import PlaybookRunner

    path = _write(tmp_path, "pb.yaml", SERVER_PLAYBOOK)
    pb = load_playbook(path)
    result = PlaybookRunner().execute(pb, dry_run=True, playbook_name="pb.yaml")
    assert result.status == "ok"
    assert result.steps[0].status == "ok"
    assert "[dry-run]" in result.steps[0].message


def test_env_file_not_loaded_in_dry_run(tmp_path):
    """Dry-run must stay previewable without the server's secrets file."""
    from odoodev.core.playbook import PlaybookRunner

    content = SERVER_PLAYBOOK.replace('env_file: ""', "env_file: /nonexistent/mirror.env")
    pb = load_playbook(_write(tmp_path, "pb.yaml", content))
    result = PlaybookRunner().execute(pb, dry_run=True)
    assert result.status == "ok"


def test_env_file_missing_fails_real_run(tmp_path):
    from odoodev.core.playbook import PlaybookRunner

    content = SERVER_PLAYBOOK.replace('env_file: ""', "env_file: /nonexistent/mirror.env")
    pb = load_playbook(_write(tmp_path, "pb.yaml", content))
    with pytest.raises(PlaybookValidationError, match="env_file not found"):
        PlaybookRunner().execute(pb, dry_run=False)
