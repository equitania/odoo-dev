"""Tests for `odoodev db update`, `pull --update` and the db.update playbook step."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

import odoodev.cli  # noqa: F401  (resolve the cli ↔ commands.db import cycle first)
from odoodev.cli import cli
from odoodev.commands import db_update as mod
from odoodev.core.automation import COMMAND_HANDLERS, handle_db_update
from odoodev.core.module_update import UpdateResult, load_update_state


def _cfg(tmp_path):
    cfg = MagicMock()
    cfg.version = "19"
    cfg.ports.db = 19432
    cfg.ports.odoo = 19069
    cfg.paths.native_dir = str(tmp_path / "native")
    cfg.paths.server_dir = str(tmp_path / "server")
    cfg.paths.server_subdir = "v19-server"
    cfg.paths.base_expanded = str(tmp_path)
    cfg.paths.myconfs_dir = str(tmp_path / "myconfs")
    return cfg


class _FakeRunner:
    """Stand-in for run_module_update: scripted outcomes per database."""

    def __init__(self, outcomes: dict[str, dict] | None = None):
        self.outcomes = outcomes or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, db_name, modules, invocation, log_path, version, on_issue=None, timeout=3600):
        self.calls.append((db_name, modules))
        o = self.outcomes.get(db_name, {})
        for level, text in o.get("issues", []):
            if on_issue:
                on_issue(level, text)
        exit_code = o.get("exit_code", 0)
        errors = o.get("errors", 0)
        return UpdateResult(
            db_name=db_name,
            ok=exit_code == 0,
            exit_code=exit_code,
            duration_s=o.get("duration", 1.0),
            log_path=log_path,
            warnings=o.get("warnings", 0),
            errors=errors,
            last_error=o.get("last_error"),
        )


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Patched environment: three databases, ready dev env, one repo head."""
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(mod, "get_version", lambda v: cfg)
    monkeypatch.setattr(
        mod,
        "resolve_invocation",
        lambda c, e: {"venv_python": "py", "odoo_bin": "ob", "config_path": "c", "env": {}, "cwd": "."},
    )
    monkeypatch.setattr(mod, "repo_heads", lambda c: {"server": "abc", "v19-addons": "def"})
    monkeypatch.setattr(mod, "_odoo_port_busy", lambda c, e: False)
    monkeypatch.setattr("odoodev.commands.db.list_databases", lambda **kw: ["v19_a", "v19_b", "v19_c"])
    monkeypatch.setattr("odoodev.commands.db.database_exists", lambda name, **kw: name in {"v19_a", "v19_b", "v19_c"})
    runner = _FakeRunner()
    monkeypatch.setattr(mod, "run_module_update", runner)
    return cfg, runner


class TestHelp:
    def test_registered_on_db_group(self):
        result = CliRunner().invoke(cli, ["db", "update", "--help"])
        assert result.exit_code == 0
        for flag in ("--stale", "--all", "--filter", "-u, --modules", "--stop-on-error", "--dry-run", "--json"):
            assert flag in result.output


class TestSelection:
    def test_all_runs_every_database(self, env):
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        assert result.exit_code == 0, result.output
        assert [c[0] for c in runner.calls] == ["v19_a", "v19_b", "v19_c"]
        assert all(c[1] == "all" for c in runner.calls)
        assert "3 database(s) updated" in result.output

    def test_names_and_modules(self, env):
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_b", "-u", "eq_base,eq_sale", "-y"])
        assert result.exit_code == 0, result.output
        assert runner.calls == [("v19_b", "eq_base,eq_sale")]

    def test_filter_narrows_all(self, env):
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--filter", "_b", "-y"])
        assert result.exit_code == 0, result.output
        assert [c[0] for c in runner.calls] == ["v19_b"]

    def test_conflicting_modes_rejected(self, env):
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "-n", "v19_a", "-y"])
        assert result.exit_code == 1
        assert "only one selection mode" in result.output

    def test_dry_run_executes_nothing(self, env):
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert runner.calls == []
        assert "v19_a" in result.output and "never updated" in result.output
        assert "Dry run" in result.output

    def test_env_not_ready(self, env, monkeypatch):
        monkeypatch.setattr(mod, "resolve_invocation", lambda c, e: None)
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        assert result.exit_code == 1
        assert "not ready" in result.output


class TestStale:
    def test_state_recorded_and_stale_skips_current(self, env):
        cfg, runner = env
        first = CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])
        assert first.exit_code == 0, first.output
        state = load_update_state(mod.update_state_path(cfg))
        assert state["databases"]["v19_a"]["repos"] == {"server": "abc", "v19-addons": "def"}

        runner.calls.clear()
        second = CliRunner().invoke(cli, ["db", "update", "19", "--stale", "-y"])
        assert second.exit_code == 0, second.output
        assert [c[0] for c in runner.calls] == ["v19_b", "v19_c"]
        assert "1 up to date, skipped: v19_a" in second.output

    def test_stale_after_repo_change(self, env, monkeypatch):
        cfg, runner = env
        CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        monkeypatch.setattr(mod, "repo_heads", lambda c: {"server": "abc", "v19-addons": "NEW"})
        runner.calls.clear()
        result = CliRunner().invoke(cli, ["db", "update", "19", "--stale", "--dry-run"])
        assert result.exit_code == 0
        assert result.output.count("1 repo changed: v19-addons") == 3

    def test_all_current_is_a_noop(self, env):
        cfg, runner = env
        CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        runner.calls.clear()
        result = CliRunner().invoke(cli, ["db", "update", "19", "--stale", "-y"])
        assert result.exit_code == 0
        assert runner.calls == []
        assert "up to date" in result.output

    def test_stale_without_any_database_is_not_a_failure(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db.list_databases", lambda **kw: [])
        result = CliRunner().invoke(cli, ["db", "update", "19", "--stale", "-y"])
        assert result.exit_code == 0, result.output
        assert runner.calls == []
        as_json = CliRunner().invoke(cli, ["db", "update", "19", "--stale", "--json"])
        assert as_json.exit_code == 0, as_json.output
        assert json.loads(as_json.stdout)["results"] == []

    def test_explicit_all_without_databases_still_fails(self, env, monkeypatch):
        monkeypatch.setattr("odoodev.commands.db.list_databases", lambda **kw: [])
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        assert result.exit_code == 1

    def test_partial_module_update_does_not_mark_current(self, env):
        cfg, runner = env
        CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-u", "eq_base", "-y"])
        assert "v19_a" not in load_update_state(mod.update_state_path(cfg))["databases"]

    def test_logged_errors_do_not_mark_current(self, env):
        cfg, runner = env
        runner.outcomes["v19_a"] = {"errors": 1, "last_error": "odoo.x: bad"}
        result = CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])
        assert result.exit_code == 0
        assert "not marked current" in result.output
        assert "v19_a" not in load_update_state(mod.update_state_path(cfg))["databases"]


class TestOutput:
    def test_only_warnings_and_errors_echoed(self, env):
        cfg, runner = env
        runner.outcomes["v19_a"] = {
            "warnings": 1,
            "issues": [("WARNING", "odoo.addons.base: dubious"), ("ERROR", "odoo.x: boom"), ("RAW", "Traceback")],
            "errors": 1,
            "last_error": "odoo.x: boom",
        }
        result = CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])
        assert "WARN" in result.output and "odoo.addons.base: dubious" in result.output
        assert "ERROR" in result.output and "odoo.x: boom" in result.output
        assert "Traceback" in result.output

    def test_failure_summary_and_exit_code(self, env):
        cfg, runner = env
        runner.outcomes["v19_b"] = {"exit_code": 255, "errors": 1, "last_error": "odoo.registry: dead"}
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "odoo.registry: dead" in result.output
        assert "1/3 database(s) failed" in result.output
        # the failure did not stop the batch
        assert [c[0] for c in runner.calls] == ["v19_a", "v19_b", "v19_c"]

    def test_stop_on_error(self, env):
        cfg, runner = env
        runner.outcomes["v19_a"] = {"exit_code": 1}
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y", "--stop-on-error"])
        assert result.exit_code == 1
        assert [c[0] for c in runner.calls] == ["v19_a"]

    def test_json_contract(self, env):
        cfg, runner = env
        runner.outcomes["v19_b"] = {"exit_code": 2, "last_error": "x"}
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["version"] == "19" and payload["modules"] == "all"
        assert [r["database"] for r in payload["results"]] == ["v19_a", "v19_b", "v19_c"]
        assert payload["results"][1]["ok"] is False and payload["results"][1]["exit_code"] == 2
        assert payload["skipped_current"] == []
        assert payload["server_running"] is False

    def test_json_stdout_is_pure_json(self, env):
        """Warnings (e.g. a missing -n database) go to stderr, stdout carries exactly one JSON line."""
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-n", "nope", "--json"])
        assert result.exit_code == 0, result.output
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert [r["database"] for r in payload["results"]] == ["v19_a"]
        assert "does not exist" in result.stderr

    def test_json_requires_explicit_selection(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr(
            "odoodev.commands.db.select", lambda *a, **kw: pytest.fail("interactive prompt in --json mode")
        )
        result = CliRunner().invoke(cli, ["db", "update", "19", "--json"])
        assert result.exit_code == 1
        assert "explicit selection" in result.stderr
        assert result.stdout == ""
        assert runner.calls == []

    def test_json_multi_is_rejected(self, env):
        result = CliRunner().invoke(cli, ["db", "update", "19", "-m", "--json"])
        assert result.exit_code == 1
        assert "explicit selection" in result.stderr

    def test_json_reports_running_server(self, env, monkeypatch):
        monkeypatch.setattr(mod, "_odoo_port_busy", lambda c, e: True)
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--json"])
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["server_running"] is True
        assert "restart it after the update" in result.stderr

    def test_running_server_warning(self, env, monkeypatch):
        monkeypatch.setattr(mod, "_odoo_port_busy", lambda c, e: True)
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--dry-run"])
        assert "restart it after the update" in result.output


class TestDbListMarkers:
    def test_markers_only_with_state_file(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db.get_version", lambda v: cfg)
        before = CliRunner().invoke(cli, ["db", "list", "19"])
        assert "stale" not in before.output

        CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])
        after = CliRunner().invoke(cli, ["db", "list", "19"])
        assert "v19_b  (stale: never updated)" in after.output
        assert "v19_a\n" in after.output
        assert "db update 19 --stale" in after.output

        as_json = CliRunner().invoke(cli, ["db", "list", "19", "--json"])
        payload = json.loads(as_json.output.strip().splitlines()[-1])
        assert payload["stale"] == {"v19_b": "never updated", "v19_c": "never updated"}

    def test_drop_forgets_state(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db.get_version", lambda v: cfg)
        monkeypatch.setattr("odoodev.commands.db._drop_one_with_filestore", lambda n, v, p, t: True)
        CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])
        result = CliRunner().invoke(cli, ["db", "drop", "19", "-n", "v19_a", "-y"])
        assert result.exit_code == 0, result.output
        assert "v19_a" not in load_update_state(mod.update_state_path(cfg))["databases"]

    def test_restore_forgets_state_before_dropping(self, env, monkeypatch, tmp_path):
        """A restored database is a new database — it must never inherit 'current'."""
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db.get_version", lambda v: cfg)
        CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])
        backup = tmp_path / "prod.zip"
        backup.write_bytes(b"x")
        # Stop the restore right after the drop: the state must already be gone by then.
        monkeypatch.setattr("odoodev.commands.db.drop_database", lambda name, **kw: False)
        result = CliRunner().invoke(cli, ["db", "restore", "19", "-n", "v19_a", "-z", str(backup), "-y"])
        assert result.exit_code == 1
        assert "v19_a" not in load_update_state(mod.update_state_path(cfg))["databases"]

    def test_rename_moves_and_copy_duplicates_state(self, env, monkeypatch, tmp_path):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db.get_version", lambda v: cfg)
        monkeypatch.setattr("odoodev.commands.db._ensure_no_connections", lambda *a, **kw: None)
        monkeypatch.setattr("odoodev.commands.db._resolve_copy_names", lambda p, s, d: (s, d))
        monkeypatch.setattr("odoodev.commands.db.rename_database", lambda s, d, **kw: True)
        monkeypatch.setattr("odoodev.commands.db.copy_database", lambda s, d, **kw: True)
        monkeypatch.setattr("odoodev.commands.db.get_filestore_path", lambda v, db_name: str(tmp_path / "fs" / db_name))
        CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-y"])

        renamed = CliRunner().invoke(cli, ["db", "rename", "19", "-s", "v19_a", "-d", "v19_x", "-y"])
        assert renamed.exit_code == 0, renamed.output
        dbs = load_update_state(mod.update_state_path(cfg))["databases"]
        assert "v19_a" not in dbs and "v19_x" in dbs

        copied = CliRunner().invoke(cli, ["db", "copy", "19", "-s", "v19_x", "-d", "v19_y", "-y"])
        assert copied.exit_code == 0, copied.output
        dbs = load_update_state(mod.update_state_path(cfg))["databases"]
        assert dbs["v19_x"] == dbs["v19_y"]


class TestPullUpdate:
    def test_pull_help_has_update(self):
        result = CliRunner().invoke(cli, ["pull", "--help"])
        assert "--update" in result.output

    def test_pull_hands_off_to_stale_update(self, monkeypatch, tmp_path):
        repos_yaml = tmp_path / "repos.yaml"
        repos_yaml.write_text(f"version: '19'\nbranch: develop\npaths:\n  base: {tmp_path}\naddons: []\n")
        cfg = _cfg(tmp_path)
        monkeypatch.setattr("odoodev.commands.pull.resolve_version", lambda ctx, v: "19")
        monkeypatch.setattr("odoodev.commands.pull.load_versions", lambda: {})
        monkeypatch.setattr("odoodev.commands.pull.get_version", lambda v, vers=None: cfg)
        monkeypatch.setattr("odoodev.commands.pull._find_repos_config", lambda c: str(repos_yaml))
        calls: list[dict] = []

        def fake_update(version, **kwargs):
            calls.append({"version": version, **kwargs})
            return 0

        monkeypatch.setattr(mod, "update_databases", fake_update)
        result = CliRunner().invoke(cli, ["pull", "19", "--update"])
        assert result.exit_code == 0, result.output
        assert calls == [{"version": "19", "stale": True, "yes": True}]

    def test_pull_update_propagates_failure(self, monkeypatch, tmp_path):
        repos_yaml = tmp_path / "repos.yaml"
        repos_yaml.write_text(f"version: '19'\nbranch: develop\npaths:\n  base: {tmp_path}\naddons: []\n")
        cfg = _cfg(tmp_path)
        monkeypatch.setattr("odoodev.commands.pull.resolve_version", lambda ctx, v: "19")
        monkeypatch.setattr("odoodev.commands.pull.load_versions", lambda: {})
        monkeypatch.setattr("odoodev.commands.pull.get_version", lambda v, vers=None: cfg)
        monkeypatch.setattr("odoodev.commands.pull._find_repos_config", lambda c: str(repos_yaml))
        monkeypatch.setattr(mod, "update_databases", lambda version, **kw: 1)
        result = CliRunner().invoke(cli, ["pull", "19", "--update"])
        assert result.exit_code == 1


class TestAutomation:
    def test_registered(self):
        assert COMMAND_HANDLERS["db.update"] is handle_db_update

    def test_missing_selection(self, env):
        cfg, runner = env
        result = handle_db_update(cfg, {})
        assert result.status == "error"
        assert "name" in result.message

    def test_names_string_and_stale(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db._get_db_params", lambda c, e: {"host": "h", "port": 1, "user": "u"})
        result = handle_db_update(cfg, {"name": "v19_a, v19_b", "modules": "all"})
        assert result.status == "ok", result.message
        assert [c[0] for c in runner.calls] == ["v19_a", "v19_b"]
        assert len(result.details["results"]) == 2

        runner.calls.clear()
        result = handle_db_update(cfg, {"all": True, "stale": True})
        assert result.status == "ok"
        assert [c[0] for c in runner.calls] == ["v19_c"]
        assert result.details["skipped_current"] == ["v19_a", "v19_b"]

    def test_failure_is_error_with_details(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db._get_db_params", lambda c, e: {"host": "h", "port": 1, "user": "u"})
        runner.outcomes["v19_b"] = {"exit_code": 1, "last_error": "boom"}
        result = handle_db_update(cfg, {"all": True})
        assert result.status == "error"
        assert "v19_b" in result.message
        assert result.details["results"][1]["last_error"] == "boom"

    def test_env_not_ready(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr(mod, "resolve_invocation", lambda c, e: None)
        result = handle_db_update(cfg, {"all": True})
        assert result.status == "error"

    def test_system_databases_are_never_updated(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db._get_db_params", lambda c, e: {"host": "h", "port": 1, "user": "u"})
        monkeypatch.setattr("odoodev.commands.db.database_exists", lambda name, **kw: True)
        result = handle_db_update(cfg, {"name": ["postgres", "v19_a"]})
        assert result.status == "ok", result.message
        assert [c[0] for c in runner.calls] == ["v19_a"]

    def test_timeout_and_running_server_reach_the_step(self, env, monkeypatch):
        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db._get_db_params", lambda c, e: {"host": "h", "port": 1, "user": "u"})
        monkeypatch.setattr(mod, "_odoo_port_busy", lambda c, e: True)
        seen: list[int] = []
        original = runner.__call__

        def spy(*a, timeout=3600, **kw):
            seen.append(timeout)
            return original(*a, timeout=timeout, **kw)

        monkeypatch.setattr(mod, "run_module_update", spy)
        result = handle_db_update(cfg, {"name": "v19_a", "timeout": 120})
        assert seen == [120]
        assert result.details["server_running"] is True

    def test_timeout_is_offered_in_the_wizard_schema(self):
        from odoodev.core.playbook_schema import STEP_ARG_SPECS

        args = {a.name: a for a in STEP_ARG_SPECS["db.update"].args}
        assert args["timeout"].type == "int"


class TestAutomationStateCleanup:
    def test_drop_step_forgets_state(self, env, monkeypatch):
        from odoodev.core.automation import handle_db_drop

        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db._get_db_params", lambda c, e: {"host": "h", "port": 1, "user": "u"})
        handle_db_update(cfg, {"name": "v19_a"})
        monkeypatch.setattr("odoodev.core.database.drop_database", lambda name, **kw: True)
        assert handle_db_drop(cfg, {"name": "v19_a"}).status == "ok"
        assert "v19_a" not in load_update_state(mod.update_state_path(cfg))["databases"]

    def test_restore_step_forgets_state(self, env, monkeypatch, tmp_path):
        from odoodev.core.automation import handle_db_restore

        cfg, runner = env
        monkeypatch.setattr("odoodev.commands.db._get_db_params", lambda c, e: {"host": "h", "port": 1, "user": "u"})
        handle_db_update(cfg, {"name": "v19_a"})
        backup = tmp_path / "prod.zip"
        backup.write_bytes(b"x")
        monkeypatch.setattr("odoodev.core.database.drop_database", lambda name, **kw: True)
        monkeypatch.setattr("odoodev.core.database.get_restore_temp_dir", lambda f: str(tmp_path / "extract"))
        monkeypatch.setattr("odoodev.core.database.check_restore_space", lambda *a: (True, "", 0))
        monkeypatch.setattr("odoodev.core.database.extract_backup", lambda f, p: False)
        monkeypatch.setattr("odoodev.core.database.cleanup_restore_temp", lambda p: None)
        result = handle_db_restore(cfg, {"name": "v19_a", "backup-file": str(backup)})
        assert result.status == "error"  # extraction stubbed to fail — the state is gone regardless
        assert "v19_a" not in load_update_state(mod.update_state_path(cfg))["databases"]


class TestExecuteUpdatesCallbacks:
    def test_on_start_precedes_each_database_with_its_log_path(self, env, tmp_path):
        cfg, runner = env
        seen: list[tuple[str, int, int, str]] = []
        results = mod.execute_updates(
            "19",
            {"venv_python": "py"},
            ["v19_a", "v19_b"],
            "all",
            {"server": "abc"},
            {"databases": {}},
            str(tmp_path / "state.yaml"),
            on_start=lambda db, index, total, log: seen.append((db, index, total, log)),
        )
        assert [(s[0], s[1], s[2]) for s in seen] == [("v19_a", 1, 2), ("v19_b", 2, 2)]
        assert [s[3] for s in seen] == [r.log_path for r in results]
