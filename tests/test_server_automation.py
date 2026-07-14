"""Tests for server-mode playbook handlers (server_automation.py) and pg_exec_container."""

from __future__ import annotations

import os
import sys
import types

import pytest

from odoodev.core import database as db_mod
from odoodev.core import server_automation as sa
from odoodev.core.database import (
    PG_EXEC_CONTAINER,
    PG_EXEC_HOST,
    clear_pg_exec_cache,
    pg_exec_container,
    resolve_pg_exec_mode,
)
from odoodev.core.version_registry import get_version


@pytest.fixture
def version_cfg():
    return get_version("18")


def _current_container() -> str:
    """The container an enclosing pg_exec_container() block routes pg calls to."""
    mode = resolve_pg_exec_mode(0)
    assert mode.kind == PG_EXEC_CONTAINER
    return mode.container_name


# =============================================================================
# pg_exec_container context manager
# =============================================================================


class TestPgExecContainer:
    def test_forces_container_mode_even_with_host_tools(self):
        # autouse fixture fakes psql/pg_dump presence — the override must still win
        clear_pg_exec_cache()
        with pg_exec_container("live-db"):
            mode = resolve_pg_exec_mode(18432)
            assert mode.kind == PG_EXEC_CONTAINER
            assert mode.container_name == "live-db"
            assert mode.cli == "docker"

    def test_resolution_restored_after_block(self):
        clear_pg_exec_cache()
        with pg_exec_container("live-db"):
            pass
        assert resolve_pg_exec_mode(18432).kind == PG_EXEC_HOST

    def test_two_containers_sequentially_no_cross_contamination(self):
        clear_pg_exec_cache()
        with pg_exec_container("live-db"):
            assert resolve_pg_exec_mode(0).container_name == "live-db"
        with pg_exec_container("test-db"):
            assert resolve_pg_exec_mode(0).container_name == "test-db"

    def test_forced_target_never_cached(self):
        clear_pg_exec_cache()
        with pg_exec_container("live-db"):
            resolve_pg_exec_mode(0)
            resolve_pg_exec_mode(4711)
        assert 0 not in db_mod._pg_exec_cache
        assert 4711 not in db_mod._pg_exec_cache

    def test_restored_after_exception(self):
        clear_pg_exec_cache()
        with pytest.raises(RuntimeError):
            with pg_exec_container("live-db"):
                raise RuntimeError("boom")
        assert resolve_pg_exec_mode(18432).kind == PG_EXEC_HOST

    def test_pg_base_cmd_container_shape(self):
        with pg_exec_container("test-db"):
            mode = resolve_pg_exec_mode(0)
        cmd = db_mod._pg_base_cmd("psql", mode, "ownerp", "unused", 0)
        assert cmd == ["docker", "exec", "-i", "test-db", "psql", "-U", "ownerp"]


# =============================================================================
# container.stop / container.start
# =============================================================================


class TestContainerLifecycleHandlers:
    def test_stop_resolves_component_odoo(self, version_cfg, monkeypatch):
        calls = {}

        def fake_stop(name, timeout=30, cli="docker"):
            calls["name"], calls["timeout"] = name, timeout
            return True, "stopped"

        monkeypatch.setattr("odoodev.core.docker_exec.docker_stop", fake_stop)
        args = {"target": "test", "odoo_container": "test-odoo", "db_container": "test-db", "timeout": 60}
        result = sa.handle_container_stop(version_cfg, args)
        assert result.status == "ok"
        assert calls == {"name": "test-odoo", "timeout": 60}

    def test_stop_component_db(self, version_cfg, monkeypatch):
        monkeypatch.setattr("odoodev.core.docker_exec.docker_stop", lambda name, **kw: (True, name))
        args = {"component": "db", "db_container": "test-db"}
        result = sa.handle_container_stop(version_cfg, args)
        assert result.status == "ok"
        assert result.details["container"] == "test-db"

    def test_stop_explicit_container_wins(self, version_cfg, monkeypatch):
        monkeypatch.setattr("odoodev.core.docker_exec.docker_stop", lambda name, **kw: (True, name))
        result = sa.handle_container_stop(version_cfg, {"container": "custom", "odoo_container": "test-odoo"})
        assert result.details["container"] == "custom"

    def test_stop_missing_container_arg_is_error(self, version_cfg):
        result = sa.handle_container_stop(version_cfg, {})
        assert result.status == "error"
        assert "odoo_container" in result.message

    def test_start_failure(self, version_cfg, monkeypatch):
        monkeypatch.setattr("odoodev.core.docker_exec.docker_start", lambda name, **kw: (False, "boom"))
        result = sa.handle_container_start(version_cfg, {"odoo_container": "test-odoo"})
        assert result.status == "error"
        assert "boom" in result.message

    def test_invalid_component(self, version_cfg):
        result = sa.handle_container_stop(version_cfg, {"component": "mailpit", "odoo_container": "x"})
        assert result.status == "error"
        assert "component" in result.message


# =============================================================================
# server.rebuild — shell-out to update_docker_odoo.py
# =============================================================================


class TestServerRebuild:
    @pytest.fixture
    def rebuild_env(self, tmp_path):
        script = tmp_path / "update_docker_odoo.py"
        script.write_text("# fake update script\n")
        config = tmp_path / "docker2update.yaml"
        config.write_text("containers: []\n")
        return {"script_path": str(script), "config": str(config)}

    def _fake_run(self, monkeypatch, returncode=0, stdout="", stderr="", raise_timeout=False):
        calls: dict = {}

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            if raise_timeout:
                import subprocess

                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        monkeypatch.setattr("subprocess.run", fake_run)
        return calls

    def test_happy_path_command_shape(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch, returncode=0, stdout="done")
        args = {**rebuild_env, "odoo_container": "test-odoo", "timeout": 123}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "ok"
        assert result.details["container"] == "test-odoo"
        assert calls["cmd"] == [
            "python3",
            rebuild_env["script_path"],
            "-c",
            rebuild_env["config"],
            "-s",
            "test-odoo",
        ]
        assert calls["kwargs"]["timeout"] == 123

    def test_explicit_container_wins_over_target(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch)
        args = {**rebuild_env, "container": "custom-odoo", "odoo_container": "test-odoo"}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "ok"
        assert "-s" in calls["cmd"] and calls["cmd"][calls["cmd"].index("-s") + 1] == "custom-odoo"

    def test_extra_args_appended(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch)
        args = {**rebuild_env, "odoo_container": "test-odoo", "extra_args": ["--verbose"]}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "ok"
        assert calls["cmd"][-1] == "--verbose"

    def test_extra_args_must_be_list(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch)
        args = {**rebuild_env, "odoo_container": "test-odoo", "extra_args": "--verbose"}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "error"
        assert "extra_args" in result.message
        assert "cmd" not in calls

    def test_missing_container_is_error_without_subprocess(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch)
        result = sa.handle_server_rebuild(version_cfg, dict(rebuild_env))
        assert result.status == "error"
        assert "container" in result.message
        assert "cmd" not in calls

    def test_missing_script_is_error(self, version_cfg, rebuild_env, monkeypatch, tmp_path):
        calls = self._fake_run(monkeypatch)
        args = {**rebuild_env, "script_path": str(tmp_path / "nope.py"), "odoo_container": "test-odoo"}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "error"
        assert "Rebuild script not found" in result.message
        assert "cmd" not in calls

    def test_missing_config_is_error(self, version_cfg, rebuild_env, monkeypatch, tmp_path):
        calls = self._fake_run(monkeypatch)
        args = {**rebuild_env, "config": str(tmp_path / "nope.yaml"), "odoo_container": "test-odoo"}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "error"
        assert "Rebuild config not found" in result.message
        assert "cmd" not in calls

    def test_nonzero_exit_reports_output_tail(self, version_cfg, rebuild_env, monkeypatch):
        self._fake_run(monkeypatch, returncode=1, stdout="build log", stderr="docker build failed")
        args = {**rebuild_env, "odoo_container": "test-odoo"}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "error"
        assert "exit 1" in result.message
        assert "docker build failed" in result.message

    def test_timeout_is_error(self, version_cfg, rebuild_env, monkeypatch):
        self._fake_run(monkeypatch, raise_timeout=True)
        args = {**rebuild_env, "odoo_container": "test-odoo", "timeout": 5}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "error"
        assert "timed out" in result.message

    def test_default_timeout_used(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch)
        args = {**rebuild_env, "odoo_container": "test-odoo"}
        result = sa.handle_server_rebuild(version_cfg, args)
        assert result.status == "ok"
        assert calls["kwargs"]["timeout"] == sa.REBUILD_TIMEOUT


# =============================================================================
# server.backup
# =============================================================================


class TestServerBackup:
    def _args(self, tmp_path, **extra):
        data_dir = tmp_path / "data"
        (data_dir / "filestore" / "production").mkdir(parents=True)
        (data_dir / "filestore" / "production" / "blob").write_text("x")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        return {
            "db_container": "live-db",
            "odoo_container": "live-odoo",
            "db_name": "production",
            "data_dir": str(data_dir),
            "backup_dir": str(backup_dir),
            **extra,
        }

    def test_creates_container2backup_compatible_archive(self, version_cfg, tmp_path, monkeypatch):
        seen = {}

        def fake_dump(db_name, output_path, host, port, user):
            seen["dump_container"] = _current_container()
            seen["user"] = user
            with open(output_path, "w") as fh:
                fh.write("-- dump")
            return True

        def fake_tar(sql_path, output_path, filestore_path=None, level=5):
            seen["filestore_path"] = filestore_path
            seen["level"] = level
            with open(output_path, "w") as fh:
                fh.write("archive")
            return True

        monkeypatch.setattr("odoodev.core.database.backup_database_sql", fake_dump)
        monkeypatch.setattr("odoodev.core.database.create_backup_tar_zst", fake_tar)

        args = self._args(tmp_path, compression_level=9, owner="custom")
        result = sa.handle_server_backup(version_cfg, args)
        assert result.status == "ok", result.message
        assert seen["dump_container"] == "live-db"
        assert seen["user"] == "custom"
        assert seen["filestore_path"].endswith("filestore/production")
        assert seen["level"] == 9

        backup_file = result.details["backup_file"]
        import re

        assert re.search(
            r"production_live-odoo_dockerbackup_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.tar\.zst$", backup_file
        )
        assert os.path.isfile(backup_file)

    def test_missing_filestore_refuses_silent_sql_only(self, version_cfg, tmp_path):
        args = self._args(tmp_path)
        args["db_name"] = "other_db"  # no filestore/other_db directory
        result = sa.handle_server_backup(version_cfg, args)
        assert result.status == "error"
        assert "Filestore not found" in result.message

    def test_only_sql_skips_filestore(self, version_cfg, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.database.backup_database_sql",
            lambda db, out, host, port, user: open(out, "w").close() or True,
        )
        seen = {}

        def fake_tar(sql_path, output_path, filestore_path=None, level=5):
            seen["filestore_path"] = filestore_path
            open(output_path, "w").close()
            return True

        monkeypatch.setattr("odoodev.core.database.create_backup_tar_zst", fake_tar)
        args = self._args(tmp_path, only_sql=True)
        args["db_name"] = "other_db"
        result = sa.handle_server_backup(version_cfg, args)
        assert result.status == "ok"
        assert seen["filestore_path"] is None
        assert "_sql_only" in result.details["backup_file"]

    def test_dump_failure(self, version_cfg, tmp_path, monkeypatch):
        monkeypatch.setattr("odoodev.core.database.backup_database_sql", lambda *a, **kw: False)
        result = sa.handle_server_backup(version_cfg, self._args(tmp_path))
        assert result.status == "error"
        assert "pg_dump" in result.message

    def test_missing_backup_dir(self, version_cfg, tmp_path):
        args = self._args(tmp_path, backup_dir=str(tmp_path / "nope"))
        result = sa.handle_server_backup(version_cfg, args)
        assert result.status == "error"


# =============================================================================
# server.restore
# =============================================================================


class TestServerRestore:
    def _setup(self, tmp_path, monkeypatch, *, running_odoo=False, with_filestore=True, **extra):
        backups = tmp_path / "backups"
        backups.mkdir()
        backup = backups / "production_live-db_dockerbackup_2026-07-12_02-00-00.tar.zst"
        backup.write_text("archive")

        data_dir = tmp_path / "data"
        (data_dir / "filestore" / "production").mkdir(parents=True)
        (data_dir / "filestore" / "production" / "stale").write_text("old")
        (data_dir / "sessions").mkdir()
        (data_dir / "sessions" / "sess").write_text("s")

        events: list[str] = []

        def fake_extract(backup_file, extract_path):
            with open(os.path.join(extract_path, "dump.sql"), "w") as fh:
                fh.write("-- sql")
            if with_filestore:
                fs = os.path.join(extract_path, "filestore", "aa")
                os.makedirs(fs)
                with open(os.path.join(fs, "blob"), "w") as fh:
                    fh.write("new")
            events.append("extract")
            return True

        def record(name, ret=True):
            def _fn(*a, **kw):
                events.append(f"{name}@{_current_container()}")
                return ret

            return _fn

        monkeypatch.setattr(
            "odoodev.core.docker_exec.docker_container_running", lambda name, cli="docker": running_odoo
        )
        monkeypatch.setattr(
            "odoodev.core.docker_exec.chown_recursive", lambda p, uid, gid: events.append("chown") or True
        )
        monkeypatch.setattr("odoodev.core.database.check_restore_space", lambda *a, **kw: (True, "", 0))
        monkeypatch.setattr("odoodev.core.database.extract_backup", fake_extract)
        monkeypatch.setattr("odoodev.core.database.drop_database", record("drop"))
        monkeypatch.setattr("odoodev.core.database.restore_database", record("restore"))
        monkeypatch.setattr("odoodev.core.database.deactivate_cronjobs", record("cron"))
        monkeypatch.setattr("odoodev.core.database.neutralize_bank_sync", record("bank"))
        monkeypatch.setattr("odoodev.core.database.anonymize_database", record("anon"))
        monkeypatch.setattr("odoodev.core.database.wipe_database", record("wipe"))

        created = {}

        def fake_create(db_name, host, port, user, template="template1"):
            created["template"] = template
            created["user"] = user
            events.append(f"create@{_current_container()}")
            return True

        monkeypatch.setattr("odoodev.core.database.create_database", fake_create)

        args = {
            "db_container": "test-db",
            "odoo_container": "test-odoo",
            "db_name": "production",
            "data_dir": str(data_dir),
            "backup_source": {
                "mode": "newest_in_dir",
                "dir": str(backups),
                "pattern": "production_*_dockerbackup_*.tar.zst",
            },
            **extra,
        }
        return args, events, created, data_dir

    def test_full_restore_sequence(self, version_cfg, tmp_path, monkeypatch):
        args, events, created, data_dir = self._setup(tmp_path, monkeypatch, deactivate_cron=True, neutralize=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message

        assert events[0] == "extract"
        assert events[1:4] == ["drop@test-db", "create@test-db", "restore@test-db"]
        assert "cron@test-db" in events
        assert "bank@test-db" in events
        assert created["template"] == "template0"
        assert created["user"] == "ownerp"

        # filestore swapped: stale gone, new blob in place, sessions removed
        assert not (data_dir / "filestore" / "production" / "stale").exists()
        assert (data_dir / "filestore" / "production" / "aa" / "blob").read_text() == "new"
        assert not (data_dir / "sessions").exists()
        assert "chown" in events

    def test_running_odoo_container_blocks_restore(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, running_odoo=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "still running" in result.message
        assert "drop@test-db" not in events

    def test_missing_filestore_is_hard_error(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, with_filestore=False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "no filestore" in result.message

    def test_missing_filestore_allowed_when_opted_in(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, with_filestore=False, allow_missing_filestore=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok"

    def test_sanitize_flag_enables_default_steps(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, sanitize=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok"
        for step in ("cron", "bank", "anon", "wipe"):
            assert f"{step}@test-db" in events

    def test_explicit_no_flag_wins_over_sanitize(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, sanitize=True, anonymize=False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok"
        assert "anon@test-db" not in events
        assert "cron@test-db" in events

    def test_sanitize_failure_reported(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, deactivate_cron=True)
        monkeypatch.setattr("odoodev.core.database.deactivate_cronjobs", lambda *a, **kw: False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "deactivate_cron" in result.message

    def test_no_backup_found(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch)
        args["backup_source"]["pattern"] = "nomatch_*.tar.zst"
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "no backup matching" in result.message

    def test_space_check_failure_aborts_before_extract(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr("odoodev.core.database.check_restore_space", lambda *a, **kw: (False, "disk full", 0))
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "disk full" in result.message
        assert "extract" not in events


# =============================================================================
# server.neutralize / server.update-all
# =============================================================================


class TestOdooBinContainerHandlers:
    def test_neutralize_ok(self, version_cfg, monkeypatch):
        seen = {}

        def fake(db, container, odoo_bin_path, config_path):
            seen.update(db=db, container=container, bin=odoo_bin_path, conf=config_path)
            return True, "done"

        monkeypatch.setattr("odoodev.core.database.run_neutralize_container", fake)
        args = {"odoo_container": "test-odoo", "db_name": "production"}
        result = sa.handle_server_neutralize(version_cfg, args)
        assert result.status == "ok"
        assert seen["container"] == "test-odoo"
        assert seen["bin"] == "/opt/odoo/odoo-server/odoo-bin"
        assert seen["conf"] == "/opt/odoo/etc/odoo.conf"

    def test_neutralize_failure(self, version_cfg, monkeypatch):
        monkeypatch.setattr("odoodev.core.database.run_neutralize_container", lambda *a, **kw: (False, "not running"))
        result = sa.handle_server_neutralize(version_cfg, {"odoo_container": "test-odoo", "db_name": "p"})
        assert result.status == "error"
        assert "not running" in result.message

    def test_update_all_with_restart(self, version_cfg, monkeypatch):
        events = []
        monkeypatch.setattr(
            "odoodev.core.database.run_update_all_container",
            lambda *a, **kw: events.append("update") or (True, "ok"),
        )
        monkeypatch.setattr("odoodev.core.docker_exec.docker_stop", lambda n, **kw: events.append("stop") or (True, ""))
        monkeypatch.setattr(
            "odoodev.core.docker_exec.docker_start", lambda n, **kw: events.append("start") or (True, "")
        )
        result = sa.handle_server_update_all(version_cfg, {"odoo_container": "test-odoo", "db_name": "p"})
        assert result.status == "ok"
        assert events == ["update", "stop", "start"]
        assert "restarted" in result.message

    def test_update_all_no_restart(self, version_cfg, monkeypatch):
        monkeypatch.setattr("odoodev.core.database.run_update_all_container", lambda *a, **kw: (True, "ok"))
        result = sa.handle_server_update_all(
            version_cfg, {"odoo_container": "test-odoo", "db_name": "p", "restart": False}
        )
        assert result.status == "ok"
        assert "restarted" not in result.message


# =============================================================================
# sql.execute
# =============================================================================


class TestSqlExecute:
    def test_server_mode_runs_statements_in_container(self, version_cfg, monkeypatch):
        ran = []

        def fake_psql(command, db=None, host="localhost", port=18432, user="ownerp"):
            ran.append((command, db, _current_container(), user))
            return True, ""

        monkeypatch.setattr("odoodev.core.database._run_psql", fake_psql)
        args = {
            "db_container": "test-db",
            "db_name": "production",
            "owner": "custom",
            "statements": ["UPDATE a SET b = 1;", "DELETE FROM c;"],
        }
        result = sa.handle_sql_execute(version_cfg, args)
        assert result.status == "ok"
        assert result.details["executed"] == 2
        assert ran[0] == ("UPDATE a SET b = 1;", "production", "test-db", "custom")
        assert ran[1][0] == "DELETE FROM c;"

    def test_statement_failure_aborts_with_index(self, version_cfg, monkeypatch):
        calls = iter([(True, ""), (False, "syntax error")])
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda *a, **kw: next(calls))
        args = {"db_container": "test-db", "db_name": "p", "statements": ["ok;", "bad;"]}
        result = sa.handle_sql_execute(version_cfg, args)
        assert result.status == "error"
        assert "Statement 2" in result.message
        assert "syntax error" in result.message

    def test_sql_file(self, version_cfg, tmp_path, monkeypatch):
        sql = tmp_path / "post.sql"
        sql.write_text("UPDATE x SET y = 1;")
        seen = {}

        def fake_file(content, db, host="localhost", port=18432, user="ownerp"):
            seen["content"], seen["db"] = content, db
            return True, ""

        monkeypatch.setattr("odoodev.core.database._run_psql_file", fake_file)
        args = {"db_container": "test-db", "db_name": "p", "file": str(sql)}
        result = sa.handle_sql_execute(version_cfg, args)
        assert result.status == "ok"
        assert seen["content"] == "UPDATE x SET y = 1;"

    def test_requires_statements_or_file(self, version_cfg):
        result = sa.handle_sql_execute(version_cfg, {"db_container": "test-db", "db_name": "p"})
        assert result.status == "error"

    def test_dev_fallback_without_target(self, version_cfg, monkeypatch):
        seen = {}

        def fake_psql(command, db=None, host="localhost", port=18432, user="ownerp"):
            seen["port"] = port
            return True, ""

        monkeypatch.setattr("odoodev.core.database._run_psql", fake_psql)
        args = {"db_name": "v18_exam", "statements": ["SELECT 1;"]}
        result = sa.handle_sql_execute(version_cfg, args)
        assert result.status == "ok"
        assert seen["port"] == version_cfg.ports.db


# =============================================================================
# rpc.execute
# =============================================================================


class FakeOdooRpc:
    instances: list[FakeOdooRpc] = []

    def __init__(self, host="localhost", protocol="jsonrpc", port=8069):
        self.host, self.protocol, self.port = host, protocol, port
        self.logged_in = None
        self.calls: list[tuple] = []
        self.search_result: list[int] = [1, 2]
        FakeOdooRpc.instances.append(self)

    def login(self, db, user, password):
        self.logged_in = (db, user, password)

    def execute_kw(self, model, method, args, kwargs):
        self.calls.append((model, method, args, kwargs))
        if method == "search":
            return self.search_result
        return True


@pytest.fixture
def fake_rpc(monkeypatch):
    FakeOdooRpc.instances = []
    module = types.ModuleType("odoorpc_toolbox")
    module.ODOO = FakeOdooRpc
    monkeypatch.setitem(sys.modules, "odoorpc_toolbox", module)
    return FakeOdooRpc


_RPC_CONFIG = {"host": "https://test.example.com", "db": "production", "user": "admin", "password": "pw"}


class TestRpcExecute:
    def test_direct_method_call(self, version_cfg, fake_rpc):
        args = {
            "model": "ir.config_parameter",
            "method": "set_param",
            "args": ["mail.catchall.domain", "test.invalid"],
            "_rpc_config": dict(_RPC_CONFIG),
        }
        result = sa.handle_rpc_execute(version_cfg, args)
        assert result.status == "ok", result.message
        odoo = fake_rpc.instances[0]
        assert odoo.host == "test.example.com"
        assert odoo.protocol == "jsonrpc+ssl"
        assert odoo.port == 443
        assert odoo.logged_in == ("production", "admin", "pw")
        assert odoo.calls == [("ir.config_parameter", "set_param", ["mail.catchall.domain", "test.invalid"], {})]

    def test_domain_plus_values_writes(self, version_cfg, fake_rpc):
        args = {
            "model": "website",
            "domain": [["id", "!=", False]],
            "values": {"domain": "https://acme-test.ownerp.app"},
            "_rpc_config": dict(_RPC_CONFIG),
        }
        result = sa.handle_rpc_execute(version_cfg, args)
        assert result.status == "ok"
        odoo = fake_rpc.instances[0]
        assert odoo.calls[0] == ("website", "search", [[["id", "!=", False]]], {})
        assert odoo.calls[1] == ("website", "write", [[1, 2], {"domain": "https://acme-test.ownerp.app"}], {})
        assert result.details["count"] == 2

    def test_domain_empty_search_is_noop_ok(self, version_cfg, fake_rpc):
        args = {"model": "website", "domain": [], "values": {"x": 1}, "_rpc_config": dict(_RPC_CONFIG)}
        FakeOdooRpc.search_result = []

        class Empty(FakeOdooRpc):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.search_result = []

        sys.modules["odoorpc_toolbox"].ODOO = Empty
        result = sa.handle_rpc_execute(version_cfg, args)
        assert result.status == "ok"
        assert result.details["count"] == 0

    def test_missing_library_gives_install_hint(self, version_cfg, monkeypatch):
        monkeypatch.setitem(sys.modules, "odoorpc_toolbox", None)
        args = {"model": "res.users", "method": "search_count", "_rpc_config": dict(_RPC_CONFIG)}
        result = sa.handle_rpc_execute(version_cfg, args)
        assert result.status == "error"
        assert "[rpc]" in result.message

    def test_incomplete_credentials(self, version_cfg, fake_rpc):
        args = {
            "model": "res.users",
            "method": "search_count",
            "_rpc_config": {"host": "https://x.example", "db": "p"},
        }
        result = sa.handle_rpc_execute(version_cfg, args)
        assert result.status == "error"
        assert "credentials" in result.message

    def test_missing_host(self, version_cfg, fake_rpc):
        result = sa.handle_rpc_execute(version_cfg, {"model": "res.users", "method": "search_count", "_rpc_config": {}})
        assert result.status == "error"
        assert "host" in result.message

    def test_http_host_defaults(self, version_cfg, fake_rpc):
        args = {
            "model": "res.users",
            "method": "search_count",
            "_rpc_config": {**_RPC_CONFIG, "host": "http://10.0.0.5", "port": "8069"},
        }
        result = sa.handle_rpc_execute(version_cfg, args)
        assert result.status == "ok"
        odoo = fake_rpc.instances[0]
        assert odoo.host == "10.0.0.5"
        assert odoo.protocol == "jsonrpc"
        assert odoo.port == 8069
