"""Tests for the ``server.install`` playbook step (odoo-bin shell inside the container)."""

from __future__ import annotations

import json

import pytest

from odoodev.core import database as db_mod
from odoodev.core import server_automation as sa
from odoodev.core.version_registry import get_version

MARKER = db_mod.INSTALL_REPORT_MARKER
ARGS = {
    "odoo_container": "test-odoo",
    "db_container": "test-db",
    "db_name": "acme_test",
    "modules": ["sale_management", "eq_foo"],
}


@pytest.fixture
def version_cfg():
    return get_version("18")


def _report(**kw):
    base = {
        "requested": [],
        "already_installed": [],
        "installed": [],
        "unknown": [],
        "failed": [],
        "list_updated": [],
    }
    base.update(kw)
    return MARKER + json.dumps(base)


class TestScriptAndParsing:
    def test_script_compiles_and_embeds_modules(self):
        script = db_mod._build_install_report_script(["eq_foo"])
        compile(script, "<script>", "exec")
        assert "MODULES = ['eq_foo']" in script
        assert "button_immediate_install" in script
        assert "update_list()" in script
        assert MARKER in script

    def test_parse_ignores_log_noise(self):
        output = (
            "2026-11-20 10:00:00,1 1 INFO acme odoo.modules.loading: loading\n"
            "warning: something odoodev-install-result: not json\n"
            + _report(installed=["a", "b"])
            + "\n2026-11-20 10:00:09,1 1 INFO acme odoo.registry: done\n"
        )
        result = db_mod.parse_install_report(output)
        assert result is not None
        assert result["installed"] == ["a", "b"]

    def test_parse_without_marker(self):
        assert db_mod.parse_install_report("only noise\n") is None

    def test_uninstall_parser_does_not_read_install_marker(self):
        assert db_mod.parse_uninstall_report(_report(installed=["a"])) is None

    def test_command_shape(self, monkeypatch):
        seen = {}
        monkeypatch.setattr("odoodev.core.docker_exec.docker_container_running", lambda n, cli="docker": True)

        def fake_exec(name, cmd, stdin_data=None, cli="docker", user=None, timeout=None):
            seen.update(name=name, cmd=cmd, stdin=stdin_data, user=user, timeout=timeout)
            return True, "out", ""

        monkeypatch.setattr("odoodev.core.docker_exec.docker_exec", fake_exec)
        ok, out = db_mod.run_install_modules_container("db1", "test-odoo", ["m1"], timeout=99)
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

    def test_container_not_running(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.docker_exec.docker_container_running", lambda n, cli="docker": False)
        ok, out = db_mod.run_install_modules_container("db1", "test-odoo", ["m1"])
        assert not ok and "not running" in out


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
        monkeypatch.setattr("odoodev.core.database.run_install_modules_container", fake_shell)
        monkeypatch.setattr("odoodev.core.database._run_psql_tuples", fake_tuples)
        monkeypatch.setattr("odoodev.core.docker_exec.docker_stop", lambda n, **kw: events.append("stop") or (True, ""))
        monkeypatch.setattr(
            "odoodev.core.docker_exec.docker_start", lambda n, **kw: events.append("start") or (True, "")
        )
        return events

    ALL_INSTALLED = (("eq_foo", "installed"), ("sale_management", "installed"))

    def test_installs_waits_for_health_first_and_restarts(self, version_cfg, monkeypatch):
        out = "noise\n" + _report(installed=["eq_foo", "sale", "sale_management"])
        events = self._patch(monkeypatch, shell_out=out, rows=self.ALL_INSTALLED)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "ok", result.message
        assert events[0] == "health" and events[1] == "shell"
        assert events[2] == "psql" and events[-2:] == ["stop", "start"]
        assert "dependencies: sale" in result.message
        assert "restarted" in result.message
        assert "'sale_management', 'eq_foo'" in events[3]

    def test_no_restart(self, version_cfg, monkeypatch):
        out = _report(installed=["eq_foo", "sale_management"])
        events = self._patch(monkeypatch, shell_out=out, rows=self.ALL_INSTALLED)
        result = sa.handle_server_install(version_cfg, {**ARGS, "restart": False})
        assert result.status == "ok"
        assert "stop" not in events

    def test_already_installed_is_skipped_and_reported(self, version_cfg, monkeypatch):
        out = _report(already_installed=["sale_management"], installed=["eq_foo"])
        self._patch(monkeypatch, shell_out=out, rows=self.ALL_INSTALLED)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "ok"
        assert "already installed: sale_management" in result.message

    def test_noop_when_all_already_installed(self, version_cfg, monkeypatch):
        out = _report(already_installed=["eq_foo", "sale_management"])
        events = self._patch(monkeypatch, shell_out=out, rows=self.ALL_INSTALLED)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "ok"
        assert "Nothing to install" in result.message
        assert "stop" not in events

    def test_unknown_after_update_list_is_an_error(self, version_cfg, monkeypatch):
        out = _report(unknown=["eq_foo"], list_updated=["yes"])
        events = self._patch(monkeypatch, shell_out=out)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "eq_foo" in result.message and "module list" in result.message
        assert "psql" not in events and "stop" not in events

    def test_empty_modules_is_a_noop(self, version_cfg, monkeypatch):
        events = self._patch(monkeypatch, shell_out="")
        for empty in ([], "", None):
            result = sa.handle_server_install(version_cfg, {**ARGS, "modules": empty})
            assert result.status == "ok"
            assert "no modules requested" in result.message
        assert events == []

    def test_invalid_module_name_rejected_before_anything_runs(self, version_cfg, monkeypatch):
        events = self._patch(monkeypatch, shell_out="")
        result = sa.handle_server_install(version_cfg, {**ARGS, "modules": ["ok", "bad name;"]})
        assert result.status == "error"
        assert "invalid module name" in result.message
        assert events == []

    def test_fails_when_db_state_is_not_installed(self, version_cfg, monkeypatch):
        out = _report(installed=["sale_management"], failed=["eq_foo"])
        events = self._patch(
            monkeypatch, shell_out=out, rows=[("eq_foo", "uninstalled"), ("sale_management", "installed")]
        )
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "eq_foo (uninstalled)" in result.message
        assert "sale_management (" not in result.message
        assert "stop" not in events

    def test_fails_when_module_row_is_missing_in_db(self, version_cfg, monkeypatch):
        out = _report(installed=["sale_management"])
        self._patch(monkeypatch, shell_out=out, rows=[("sale_management", "installed")])
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "eq_foo (missing)" in result.message

    def test_fails_on_reported_failure(self, version_cfg, monkeypatch):
        out = _report(installed=["eq_foo"], failed=["sale_management"])
        self._patch(monkeypatch, shell_out=out, rows=self.ALL_INSTALLED)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "failures" in result.message

    def test_failure_reason_is_in_the_message(self, version_cfg, monkeypatch):
        err = 'eq_foo: ValueError: boom\nTraceback (most recent call last):\n  File "x.py", line 1\nValueError: boom'
        out = _report(installed=["sale_management"], failed=["eq_foo"], errors=[err])
        self._patch(monkeypatch, shell_out=out, rows=[("eq_foo", "uninstalled"), ("sale_management", "installed")])
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "install failed for: eq_foo" in result.message
        assert "ValueError: boom" in result.message and "Traceback" in result.message

    def test_failure_reason_without_db_mismatch(self, version_cfg, monkeypatch):
        out = _report(installed=["eq_foo"], failed=["sale_management"], errors=["sale_management: KeyError: 'x'"])
        self._patch(monkeypatch, shell_out=out, rows=self.ALL_INSTALLED)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "KeyError: 'x'" in result.message

    def test_old_report_without_errors_key_still_works(self, version_cfg, monkeypatch):
        out = _report(installed=["sale_management"], failed=["eq_foo"])
        self._patch(monkeypatch, shell_out=out, rows=[("eq_foo", "uninstalled"), ("sale_management", "installed")])
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert result.message.endswith("install failed for: eq_foo")

    def test_failure_details_are_bounded(self):
        text = db_mod.format_failure_details({"errors": ["x" * 10000]})
        assert len(text) < db_mod.MAX_FAILURE_DETAIL_CHARS + 50
        assert text.endswith("(truncated)")
        assert db_mod.format_failure_details({}) == ""

    def test_script_records_reason_and_it_runs(self):
        """Run the generated script's helper for real: type, message and traceback tail land in the report."""
        script = db_mod._build_install_report_script(["eq_foo"])
        compile(script, "<script>", "exec")
        assert '"errors": _errors' in script
        ns: dict = {}
        exec(script.split("import json")[0], ns)  # noqa: S102 - helper only, generated by us
        try:
            raise ValueError("boom " * 100)
        except ValueError as exc:
            detail = ns["_failure_detail"]("eq_foo", exc)
        assert detail.startswith("eq_foo: ValueError: boom")
        assert "Traceback (most recent call last)" in detail
        assert len(detail.splitlines()) <= 17
        assert all(len(line) <= 340 for line in detail.splitlines())

    def test_errors_survive_the_parser(self):
        result = db_mod.parse_install_report(_report(failed=["a"], errors=["a: E: x\ntb"]))
        assert result is not None and result["errors"] == ["a: E: x\ntb"]

    def test_psql_failure(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, shell_out=_report(installed=["eq_foo"]), psql_ok=False)
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "Could not read the module states" in result.message

    def test_unhealthy_container_stops_before_shell(self, version_cfg, monkeypatch):
        events = self._patch(monkeypatch, health=("starting", "Odoo container 'test-odoo' did not become healthy"))
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert events == ["health"]

    def test_shell_failure(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, shell_ok=False, shell_out="Traceback ...")
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "Traceback" in result.message

    def test_missing_marker(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, shell_out="just noise")
        result = sa.handle_server_install(version_cfg, dict(ARGS))
        assert result.status == "error"
        assert "no result line" in result.message

    def test_registered(self):
        from odoodev.core.playbook import _PROGRESS_COMMANDS, SERVER_COMMANDS, VALID_COMMANDS
        from odoodev.core.playbook_schema import STEP_ARG_SPECS

        assert "server.install" in VALID_COMMANDS and "server.install" in SERVER_COMMANDS
        assert "server.install" in _PROGRESS_COMMANDS
        spec = STEP_ARG_SPECS["server.install"]
        modules = next(a for a in spec.args if a.name == "modules")
        assert modules.type == "list[str]" and modules.required
        assert sa.SERVER_COMMAND_HANDLERS["server.install"] is sa.handle_server_install
