"""Tests for the ``server.uninstall`` playbook step (odoo-bin shell inside the container)."""

from __future__ import annotations

import json

import pytest

from odoodev.core import database as db_mod
from odoodev.core import server_automation as sa
from odoodev.core.version_registry import get_version

MARKER = db_mod.UNINSTALL_REPORT_MARKER
ARGS = {
    "odoo_container": "test-odoo",
    "db_container": "test-db",
    "db_name": "acme_test",
    "modules": ["account_ebics", "account_ebics_batch"],
}


@pytest.fixture
def version_cfg():
    return get_version("18")


def _report(**kw):
    base = {"requested": [], "installed": [], "uninstalled": [], "not_installed": [], "unknown": [], "failed": []}
    base.update(kw)
    return MARKER + json.dumps(base)


class TestScriptAndParsing:
    def test_validate_rejects_bad_names(self):
        with pytest.raises(ValueError, match="invalid module name"):
            db_mod.validate_module_names(["ok_mod", "x'; import os #"])
        with pytest.raises(ValueError):
            db_mod.validate_module_names("Upper")

    def test_validate_accepts_list_and_csv(self):
        assert db_mod.validate_module_names("a_b, c1,a_b") == ["a_b", "c1"]
        assert db_mod.validate_module_names(["a", "b"]) == ["a", "b"]

    def test_script_compiles_and_embeds_modules(self):
        script = db_mod._build_uninstall_report_script(["account_ebics"])
        compile(script, "<script>", "exec")
        assert "MODULES = ['account_ebics']" in script
        assert "button_immediate_uninstall" in script
        assert MARKER in script

    def test_parse_ignores_log_noise(self):
        output = (
            "2026-10-21 10:00:00,1 1 INFO acme odoo.modules.loading: loading\n"
            "warning: something odoodev-uninstall-result: not json\n"
            + _report(installed=["a"], uninstalled=["a", "b"])
            + "\n2026-10-21 10:00:09,1 1 INFO acme odoo.registry: done\n"
        )
        result = db_mod.parse_uninstall_report(output)
        assert result is not None
        assert result["uninstalled"] == ["a", "b"]

    def test_parse_without_marker(self):
        assert db_mod.parse_uninstall_report("only noise\n") is None

    def test_command_shape(self, monkeypatch):
        seen = {}
        monkeypatch.setattr("odoodev.core.docker_exec.docker_container_running", lambda n, cli="docker": True)

        def fake_exec(name, cmd, stdin_data=None, cli="docker", user=None, timeout=None):
            seen.update(name=name, cmd=cmd, stdin=stdin_data, user=user, timeout=timeout)
            return True, "out", ""

        monkeypatch.setattr("odoodev.core.docker_exec.docker_exec", fake_exec)
        ok, out = db_mod.run_uninstall_modules_container("db1", "test-odoo", ["m1"], timeout=99)
        assert ok and out == "out"
        assert seen["name"] == "test-odoo"
        assert seen["cmd"] == [
            "python3",
            "/opt/odoo/odoo-server/odoo-bin",
            "shell",
            "-c",
            "/opt/odoo/etc/odoo.conf",
            "-d",
            "db1",
            "--no-http",
        ]
        assert seen["user"] == "odoo"
        assert seen["timeout"] == 99
        assert "MODULES = ['m1']" in seen["stdin"]

    def test_docker_exec_user_flag(self, monkeypatch):
        import subprocess

        from odoodev.core import docker_exec as de

        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(de.subprocess, "run", fake_run)
        de.docker_exec("c", ["true"], user="odoo")
        de.docker_exec("c", ["true"])
        assert calls[0] == ["docker", "exec", "-i", "-u", "odoo", "c", "true"]
        assert calls[1] == ["docker", "exec", "-i", "c", "true"]


class TestHandler:
    def _patch(self, monkeypatch, *, shell_out=None, shell_ok=True, rows=(), health=("healthy", ""), psql_ok=True):
        events: list = []

        def fake_wait(container, timeout, report):
            events.append("health")
            return health

        def fake_shell(db, container, modules, **kw):
            events.append("shell")
            return shell_ok, shell_out if shell_out is not None else ""

        def fake_tuples(query, db, host, port, user):
            events.append("psql")
            events.append(query)
            return psql_ok, [list(r) for r in rows]

        monkeypatch.setattr(sa, "_wait_container_healthy", fake_wait)
        monkeypatch.setattr("odoodev.core.database.run_uninstall_modules_container", fake_shell)
        monkeypatch.setattr("odoodev.core.database._run_psql_tuples", fake_tuples)
        monkeypatch.setattr("odoodev.core.docker_exec.docker_stop", lambda n, **kw: events.append("stop") or (True, ""))
        monkeypatch.setattr(
            "odoodev.core.docker_exec.docker_start", lambda n, **kw: events.append("start") or (True, "")
        )
        return events

    def test_uninstalls_waits_for_health_first_and_restarts(self, version_cfg, monkeypatch):
        out = "noise\n" + _report(
            installed=["account_ebics", "account_ebics_batch"],
            uninstalled=["account_ebics", "account_ebics_batch", "account_ebics_oe"],
        )
        events = self._patch(monkeypatch, shell_out=out)
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "ok", result.message
        assert events[0] == "health" and events[1] == "shell"
        assert events[2] == "psql" and events[-2:] == ["stop", "start"]
        assert "account_ebics_oe" in result.message and "dependents: account_ebics_oe" in result.message
        assert "restarted" in result.message
        assert "'account_ebics', 'account_ebics_batch'" in events[3]

    def test_no_restart(self, version_cfg, monkeypatch):
        out = _report(installed=["account_ebics"], uninstalled=["account_ebics"])
        events = self._patch(monkeypatch, shell_out=out)
        result = sa.handle_server_uninstall(version_cfg, {**ARGS, "restart": False})
        assert result.status == "ok"
        assert "stop" not in events

    def test_noop_when_nothing_installed(self, version_cfg, monkeypatch):
        out = _report(not_installed=["account_ebics"], unknown=["account_ebics_batch"])
        events = self._patch(monkeypatch, shell_out=out)
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "ok"
        assert "Nothing to uninstall" in result.message
        assert "account_ebics_batch" in result.message
        assert "stop" not in events

    def test_unknown_is_noted_not_an_error(self, version_cfg, monkeypatch):
        out = _report(installed=["account_ebics"], uninstalled=["account_ebics"], unknown=["account_ebics_batch"])
        self._patch(monkeypatch, shell_out=out)
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "ok"
        assert "not in this database: account_ebics_batch" in result.message

    def test_invalid_module_name_rejected_before_anything_runs(self, version_cfg, monkeypatch):
        events = self._patch(monkeypatch, shell_out="")
        result = sa.handle_server_uninstall(version_cfg, {**ARGS, "modules": ["ok", "bad name;"]})
        assert result.status == "error"
        assert "invalid module name" in result.message
        assert events == []

    def test_modules_required(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, shell_out="")
        args = {k: v for k, v in ARGS.items() if k != "modules"}
        assert sa.handle_server_uninstall(version_cfg, args).status == "error"

    def test_fails_when_db_still_shows_installed(self, version_cfg, monkeypatch):
        out = _report(installed=["account_ebics"], uninstalled=["account_ebics"])
        events = self._patch(monkeypatch, shell_out=out, rows=[("account_ebics", "installed")])
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "account_ebics (installed)" in result.message
        assert "stop" not in events

    def test_fails_on_reported_failure(self, version_cfg, monkeypatch):
        out = _report(installed=["account_ebics"], failed=["account_ebics"])
        self._patch(monkeypatch, shell_out=out)
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "failures" in result.message

    def test_unhealthy_container_stops_before_shell(self, version_cfg, monkeypatch):
        events = self._patch(monkeypatch, health=("starting", "Odoo container 'test-odoo' did not become healthy"))
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert events == ["health"]

    def test_shell_failure(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, shell_ok=False, shell_out="Traceback ...")
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "Traceback" in result.message

    def test_missing_marker(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, shell_out="just noise")
        result = sa.handle_server_uninstall(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "no result line" in result.message

    def test_registered(self):
        from odoodev.core.playbook import SERVER_COMMANDS, VALID_COMMANDS
        from odoodev.core.playbook_schema import STEP_ARG_SPECS

        assert "server.uninstall" in VALID_COMMANDS and "server.uninstall" in SERVER_COMMANDS
        spec = STEP_ARG_SPECS["server.uninstall"]
        modules = next(a for a in spec.args if a.name == "modules")
        assert modules.type == "list[str]" and modules.required
        assert sa.SERVER_COMMAND_HANDLERS["server.uninstall"] is sa.handle_server_uninstall
