"""Tests for the psql/pg_dump container exec fallback (resolve_pg_exec_mode)."""

from __future__ import annotations

import subprocess

import pytest

from odoodev.core import database as db_mod
from odoodev.core.database import (
    PG_EXEC_CONTAINER,
    PG_EXEC_HOST,
    PG_EXEC_UNAVAILABLE,
    PgExecMode,
    PgToolsUnavailableError,
    _pg_base_cmd,
    backup_database_sql,
    clear_pg_exec_cache,
    list_databases,
    resolve_pg_exec_mode,
    restore_database,
)


class FakeBackend:
    """Minimal ContainerBackend stand-in for resolver tests."""

    name = "Docker"
    cli = "docker"

    def __init__(self, container_name: str | None):
        self.container_name = container_name
        self.lookups = 0

    def find_container_by_port(self, port: int) -> str | None:
        self.lookups += 1
        return self.container_name


def _no_pg_tools(monkeypatch):
    """Make psql/pg_dump appear missing on the host (overrides the autouse fixture)."""
    monkeypatch.setattr("odoodev.core.database.shutil.which", lambda name, *a, **k: None)
    clear_pg_exec_cache()


def _use_backend(monkeypatch, backend):
    monkeypatch.setattr("odoodev.core.container_backend.get_active_backend", lambda *a, **k: backend)


# --- resolve_pg_exec_mode ---


def test_resolver_host_mode_when_tools_present():
    # autouse fixture fakes psql/pg_dump presence
    mode = resolve_pg_exec_mode(18432)
    assert mode.kind == PG_EXEC_HOST


def test_resolver_container_mode_when_tools_missing(monkeypatch):
    _no_pg_tools(monkeypatch)
    backend = FakeBackend("picard-dev-db-16-native")
    _use_backend(monkeypatch, backend)

    mode = resolve_pg_exec_mode(16432)
    assert mode.kind == PG_EXEC_CONTAINER
    assert mode.container_name == "picard-dev-db-16-native"
    assert mode.cli == "docker"


def test_resolver_unavailable_when_no_tools_and_no_container(monkeypatch):
    _no_pg_tools(monkeypatch)
    _use_backend(monkeypatch, FakeBackend(None))

    mode = resolve_pg_exec_mode(16432)
    assert mode.kind == PG_EXEC_UNAVAILABLE


def test_resolver_env_override_forces_host(monkeypatch):
    _no_pg_tools(monkeypatch)
    monkeypatch.setenv("ODOODEV_PG_EXEC", "host")

    mode = resolve_pg_exec_mode(16432)
    assert mode.kind == PG_EXEC_HOST


def test_resolver_env_override_forces_container(monkeypatch):
    # tools present (autouse fixture), but override skips them
    monkeypatch.setenv("ODOODEV_PG_EXEC", "container")
    _use_backend(monkeypatch, FakeBackend("picard-dev-db-18-native"))
    clear_pg_exec_cache()

    mode = resolve_pg_exec_mode(18432)
    assert mode.kind == PG_EXEC_CONTAINER


def test_resolver_caches_backend_lookup_per_port(monkeypatch):
    _no_pg_tools(monkeypatch)
    backend = FakeBackend("picard-dev-db-16-native")
    _use_backend(monkeypatch, backend)

    resolve_pg_exec_mode(16432)
    resolve_pg_exec_mode(16432)
    assert backend.lookups == 1


def test_resolver_prints_fallback_info_once(monkeypatch, capsys):
    _no_pg_tools(monkeypatch)
    _use_backend(monkeypatch, FakeBackend("picard-dev-db-16-native"))

    resolve_pg_exec_mode(16432)
    resolve_pg_exec_mode(16432)
    out = capsys.readouterr().out
    assert out.count("picard-dev-db-16-native") == 1


# --- _pg_base_cmd ---


def test_pg_base_cmd_host_shape():
    mode = PgExecMode(kind=PG_EXEC_HOST)
    cmd = _pg_base_cmd("psql", mode, "ownerp", "localhost", 16432)
    assert cmd == ["psql", "-U", "ownerp", "-h", "localhost", "-p", "16432"]


def test_pg_base_cmd_container_shape():
    mode = PgExecMode(kind=PG_EXEC_CONTAINER, container_name="picard-dev-db-16-native", cli="docker")
    cmd = _pg_base_cmd("pg_dump", mode, "ownerp", "localhost", 16432)
    assert cmd == ["docker", "exec", "-i", "picard-dev-db-16-native", "pg_dump", "-U", "ownerp"]
    assert "-h" not in cmd
    assert "-p" not in cmd


def test_pg_base_cmd_unavailable_raises():
    mode = PgExecMode(kind=PG_EXEC_UNAVAILABLE)
    with pytest.raises(PgToolsUnavailableError) as excinfo:
        _pg_base_cmd("psql", mode, "ownerp", "localhost", 16432)
    message = str(excinfo.value)
    assert "postgresql-client" in message
    assert "odoodev docker up" in message


# --- container mode end-to-end command shapes ---


def _container_mode(monkeypatch, container="picard-dev-db-16-native"):
    _no_pg_tools(monkeypatch)
    _use_backend(monkeypatch, FakeBackend(container))


def test_list_databases_container_mode(monkeypatch):
    _container_mode(monkeypatch)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=" v16_exam | ownerp |\n", stderr="")

    monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
    result = list_databases(host="localhost", port=16432, user="ownerp")
    assert result == ["v16_exam"]
    assert captured["cmd"][:4] == ["docker", "exec", "-i", "picard-dev-db-16-native"]
    assert captured["cmd"][4:] == ["psql", "-U", "ownerp", "-lqt"]


def test_backup_database_sql_container_mode(monkeypatch, tmp_path):
    _container_mode(monkeypatch)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["stdout"] = kwargs.get("stdout")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
    out = tmp_path / "dump.sql"
    assert backup_database_sql("v16_exam", str(out), host="localhost", port=16432, user="ownerp")
    assert captured["cmd"] == ["docker", "exec", "-i", "picard-dev-db-16-native", "pg_dump", "-U", "ownerp", "v16_exam"]
    # pg_dump output is captured via stdout redirection (works through docker exec)
    assert captured["stdout"] is not None


def test_restore_database_pipes_stdin_no_dash_f(monkeypatch, tmp_path):
    _container_mode(monkeypatch)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["stdin"] = kwargs.get("stdin")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
    sql = tmp_path / "dump.sql"
    sql.write_text("SELECT 1;")
    assert restore_database("v16_exam", str(sql), host="localhost", port=16432, user="ownerp")
    assert "-f" not in captured["cmd"]
    assert captured["stdin"] is not None
    expected = ["docker", "exec", "-i", "picard-dev-db-16-native", "psql", "-U", "ownerp", "-d", "v16_exam"]
    assert captured["cmd"] == expected


def test_restore_database_host_mode_also_pipes_stdin(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["stdin"] = kwargs.get("stdin")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("odoodev.core.database.subprocess.run", fake_run)
    sql = tmp_path / "dump.sql"
    sql.write_text("SELECT 1;")
    assert restore_database("v18_exam", str(sql), host="localhost", port=18432, user="ownerp")
    assert captured["cmd"] == ["psql", "-U", "ownerp", "-h", "localhost", "-p", "18432", "-d", "v18_exam"]
    assert captured["stdin"] is not None


# --- regression: missing binary must not crash ---


def test_list_databases_missing_binary_returns_empty(monkeypatch):
    """Regression for the migration-server crash: FileNotFoundError('psql') leaked as traceback."""

    def raise_fnf(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "psql")

    monkeypatch.setattr("odoodev.core.database.subprocess.run", raise_fnf)
    assert list_databases(host="localhost", port=16432, user="ownerp") == []


def test_run_psql_missing_binary_returns_error_tuple(monkeypatch):
    def raise_fnf(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "psql")

    monkeypatch.setattr("odoodev.core.database.subprocess.run", raise_fnf)
    ok, err = db_mod._run_psql("SELECT 1;", db="postgres", host="localhost", port=16432, user="ownerp")
    assert not ok
    assert "psql" in err


def test_backup_unavailable_mode_returns_false(monkeypatch, tmp_path):
    _no_pg_tools(monkeypatch)
    _use_backend(monkeypatch, FakeBackend(None))
    out = tmp_path / "dump.sql"
    assert not backup_database_sql("v16_exam", str(out), host="localhost", port=16432, user="ownerp")


# --- CLI precheck (_ensure_pg_reachable) ---


def _stub_db_cmd(monkeypatch, port=16432):
    from odoodev.commands import db as db_cmd

    monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "16")
    monkeypatch.setattr(db_cmd, "get_version", lambda v: object())
    monkeypatch.setattr(db_cmd, "_load_env_vars", lambda cfg: {})
    monkeypatch.setattr(
        db_cmd, "_get_db_params", lambda cfg, env: {"host": "localhost", "port": port, "user": "ownerp"}
    )
    monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
    return db_cmd


def test_db_list_no_tools_no_container_clean_exit(monkeypatch):
    """Full regression for the migration-server crash: clean exit 1, no traceback."""
    from click.testing import CliRunner

    from odoodev.cli import cli

    _stub_db_cmd(monkeypatch)
    _no_pg_tools(monkeypatch)
    _use_backend(monkeypatch, FakeBackend(None))
    monkeypatch.setattr("odoodev.core.prerequisites.check_port", lambda h, p: True)

    runner = CliRunner()
    result = runner.invoke(cli, ["db", "list", "16"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert "postgresql-client" in result.output
    assert "odoodev docker up" in result.output


def test_db_list_port_unreachable_clean_exit(monkeypatch):
    from click.testing import CliRunner

    from odoodev.cli import cli

    _stub_db_cmd(monkeypatch)
    monkeypatch.setattr("odoodev.core.prerequisites.check_port", lambda h, p: False)

    runner = CliRunner()
    result = runner.invoke(cli, ["db", "list", "16"])
    assert result.exit_code == 1
    assert "not accessible" in result.output
    assert "odoodev docker up" in result.output


def test_db_list_container_fallback_lists_databases(monkeypatch):
    from click.testing import CliRunner

    from odoodev.cli import cli

    db_cmd = _stub_db_cmd(monkeypatch)
    _no_pg_tools(monkeypatch)
    _use_backend(monkeypatch, FakeBackend("picard-dev-db-16-native"))
    monkeypatch.setattr("odoodev.core.prerequisites.check_port", lambda h, p: True)
    monkeypatch.setattr(db_cmd, "list_databases", lambda **kw: ["v16_exam"])

    runner = CliRunner()
    result = runner.invoke(cli, ["db", "list", "16"])
    assert result.exit_code == 0
    assert "v16_exam" in result.output
    assert "picard-dev-db-16-native" in result.output  # one-time fallback info line
