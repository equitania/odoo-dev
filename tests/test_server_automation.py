"""Tests for server-mode playbook handlers (server_automation.py) and pg_exec_container."""

from __future__ import annotations

import os
import shutil
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


@pytest.fixture(autouse=True)
def _no_container_release(monkeypatch):
    """server.backup/verify read release.py out of the image — never from a real docker here."""
    monkeypatch.setattr("odoodev.core.docker_exec.read_container_file", lambda name, path, cli="docker": None)


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
        """Stand-in for the update script: a fake Popen whose stdout yields the given lines."""
        import subprocess

        calls: dict = {}

        class FakePopen:
            def __init__(self, cmd, **kwargs):
                calls["cmd"] = cmd
                calls["kwargs"] = kwargs
                # stderr is merged into stdout by the handler (stderr=STDOUT)
                self.stdout = iter((stdout + stderr).splitlines(keepends=True))
                self.returncode = returncode

            def wait(self, timeout=None):
                if timeout is not None:
                    calls["kwargs"]["timeout"] = timeout
                if raise_timeout and not calls.get("killed"):
                    raise subprocess.TimeoutExpired(calls["cmd"], timeout)
                return self.returncode

            def kill(self):
                calls["killed"] = True

        monkeypatch.setattr("subprocess.Popen", FakePopen)
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

    DOUP_FAILED_UPDATE = (
        "  update odoo\n"
        "    13:45:50    15 CRIT  acme_prod odoo.modules.module: Couldn't load module base_setup\n"
        "    13:45:50    15 ERROR acme_prod odoo.registry: Failed to load registry\n"
        "    13:45:50    15 CRIT  acme_prod odoo.service.server: Failed to initialize database `acme_prod`.\n"
        "    ImportError: cannot import name '_check_apikey_credentials' from 'odoo.addons.base.models.res_users'\n"
        "  update odoo ................................. ok (33s)\n"
        "  successful updates .......................... 1\n"
    )

    def test_exit_zero_with_failed_module_update_is_an_error(self, version_cfg, rebuild_env, monkeypatch):
        # Seen on a customer server: the script reported a successful update while Odoo
        # could not load the database at all.
        self._fake_run(monkeypatch, returncode=0, stdout=self.DOUP_FAILED_UPDATE)
        result = sa.handle_server_rebuild(version_cfg, {**rebuild_env, "odoo_container": "live-odoo"})
        assert result.status == "error"
        assert "exited 0" in result.message
        assert "Failed to initialize database" in result.message
        assert "_check_apikey_credentials" in result.message

    def test_trust_exit_code_skips_the_output_check(self, version_cfg, rebuild_env, monkeypatch):
        self._fake_run(monkeypatch, returncode=0, stdout=self.DOUP_FAILED_UPDATE)
        args = {**rebuild_env, "odoo_container": "live-odoo", "trust_exit_code": True}
        assert sa.handle_server_rebuild(version_cfg, args).status == "ok"

    def test_import_error_alone_is_not_a_failed_update(self, version_cfg, rebuild_env, monkeypatch):
        self._fake_run(monkeypatch, returncode=0, stdout="WARN some cron: ImportError: optional lib missing\n")
        result = sa.handle_server_rebuild(version_cfg, {**rebuild_env, "odoo_container": "live-odoo"})
        assert result.status == "ok"

    def test_each_line_of_the_script_is_reported_as_progress(self, version_cfg, rebuild_env, monkeypatch):
        self._fake_run(monkeypatch, stdout="  release manager ... ok (0s)\n\n  build image odoo/live\n  update odoo\n")
        seen: list[str] = []
        args = {**rebuild_env, "odoo_container": "live-odoo", "_progress": seen.append}
        assert sa.handle_server_rebuild(version_cfg, args).status == "ok"
        assert seen == ["release manager ... ok (0s)", "build image odoo/live", "update odoo"]

    def test_the_script_runs_unbuffered_and_without_a_terminal(self, version_cfg, rebuild_env, monkeypatch):
        import subprocess

        calls = self._fake_run(monkeypatch)
        sa.handle_server_rebuild(version_cfg, {**rebuild_env, "odoo_container": "live-odoo"})
        # a Python child writing to a pipe buffers in blocks — progress would arrive at the very end
        assert calls["kwargs"]["env"]["PYTHONUNBUFFERED"] == "1"
        assert calls["kwargs"]["stdin"] == subprocess.DEVNULL
        assert calls["kwargs"]["stderr"] == subprocess.STDOUT

    def test_timeout_kills_the_script(self, version_cfg, rebuild_env, monkeypatch):
        calls = self._fake_run(monkeypatch, raise_timeout=True)
        result = sa.handle_server_rebuild(version_cfg, {**rebuild_env, "odoo_container": "x", "timeout": 5})
        assert result.status == "error"
        assert calls["killed"] is True

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

    def _fake_archive(self, monkeypatch, seen=None):
        monkeypatch.setattr(
            "odoodev.core.database.backup_database_sql",
            lambda db, out, host, port, user: open(out, "w").close() or True,
        )

        def fake_tar(sql_path, output_path, filestore_path=None, level=5):
            if seen is not None:
                seen["filestore_path"] = filestore_path
            open(output_path, "w").close()
            return True

        monkeypatch.setattr("odoodev.core.database.create_backup_tar_zst", fake_tar)

    def test_manifest_records_the_kernel_of_the_source(self, version_cfg, tmp_path, monkeypatch):
        self._fake_archive(monkeypatch)
        monkeypatch.setattr(
            "odoodev.core.docker_exec.read_container_file",
            lambda name, path, cli="docker": "version_info = (19, 0, 0, FINAL, 0, '-26.09.29')\n",
        )
        result = sa.handle_server_backup(version_cfg, self._args(tmp_path))
        assert result.status == "ok", result.message
        manifest = result.details["backup_file"] + ".manifest"
        content = open(manifest).read()
        assert "odoo_build=26.09.29" in content
        assert "db_name=production" in content
        assert os.stat(manifest).st_mode & 0o777 == 0o600

    def test_safety_backup_of_missing_database_is_a_noop(self, version_cfg, tmp_path, monkeypatch):
        monkeypatch.setattr("odoodev.core.database.database_exists", lambda db, host, port, user: False)
        monkeypatch.setattr("odoodev.core.database.backup_database_sql", lambda *a, **kw: pytest.fail("must not dump"))
        result = sa.handle_server_backup(version_cfg, self._args(tmp_path, safety=True))
        assert result.status == "ok"
        assert "nothing to back up" in result.message
        assert "backup_file" not in result.details
        assert os.listdir(tmp_path / "backups") == []

    def test_safety_backup_never_feeds_a_from_backup_step_restore(self, version_cfg, tmp_path, monkeypatch):
        self._fake_archive(monkeypatch)
        monkeypatch.setattr("odoodev.core.database.database_exists", lambda db, host, port, user: True)
        result = sa.handle_server_backup(version_cfg, self._args(tmp_path, safety=True))
        assert result.status == "ok", result.message
        assert "backup_file" not in result.details
        name = os.path.basename(result.details["safety_backup_file"])
        assert "_prerestore_" in name and "_dockerbackup_" not in name

    def test_safety_backup_without_filestore_degrades_to_sql_only(self, version_cfg, tmp_path, monkeypatch):
        seen = {}
        self._fake_archive(monkeypatch, seen)
        monkeypatch.setattr("odoodev.core.database.database_exists", lambda db, host, port, user: True)
        args = self._args(tmp_path, safety=True)
        args["db_name"] = "other_db"  # exists in PostgreSQL, has no filestore directory
        result = sa.handle_server_backup(version_cfg, args)
        assert result.status == "ok", result.message
        assert seen["filestore_path"] is None
        assert "_sql_only" in result.details["safety_backup_file"]


# =============================================================================
# server.restore
# =============================================================================


class TestResolveBackupFile:
    def test_from_backup_step_uses_runtime_file(self, tmp_path):
        backup = tmp_path / "production_live-odoo_dockerbackup_2026-07-15_02-00-00.tar.zst"
        backup.write_text("archive")
        args = {
            "backup_source": {"mode": "from_backup_step"},
            "_runtime": {"backup_file": str(backup)},
        }
        assert sa._resolve_backup_file(args, "server.restore") == str(backup)

    def test_from_backup_step_without_backup_step_errors(self):
        args = {"backup_source": {"mode": "from_backup_step"}, "_runtime": {}}
        with pytest.raises(ValueError, match="server.backup"):
            sa._resolve_backup_file(args, "server.restore")

    def test_from_backup_step_missing_runtime_errors(self):
        with pytest.raises(ValueError, match="from_backup_step"):
            sa._resolve_backup_file({"backup_source": {"mode": "from_backup_step"}}, "server.restore")

    def test_from_backup_step_vanished_file_errors(self, tmp_path):
        args = {
            "backup_source": {"mode": "from_backup_step"},
            "_runtime": {"backup_file": str(tmp_path / "gone.tar.zst")},
        }
        with pytest.raises(ValueError, match="no longer exists"):
            sa._resolve_backup_file(args, "server.restore")

    def test_unknown_mode_lists_all_modes(self):
        with pytest.raises(ValueError, match="from_backup_step.*file.*newest_in_dir"):
            sa._resolve_backup_file({"backup_source": {"mode": "teleport"}}, "server.restore")


class TestServerRestore:
    def _setup(
        self,
        tmp_path,
        monkeypatch,
        *,
        running_odoo=False,
        with_filestore=True,
        existing=("production",),
        restore_ok=True,
        sql_errors=(),
        installed_modules=120,
        **extra,
    ):
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
        databases: set[str] = set(existing)

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

        def fake_exists(db_name, host, port, user):
            _current_container()  # must run inside a pg_exec_container block
            return db_name in databases

        def fake_drop(db_name, host, port, user):
            if db_name in databases:
                databases.discard(db_name)
                events.append(f"drop:{db_name}")
            return True

        created = {}

        def fake_create(db_name, host, port, user, template="template1"):
            created["template"] = template
            created["user"] = user
            databases.add(db_name)
            events.append(f"create:{db_name}")
            return True

        def fake_restore(db_name, sql_file, host, port, user):
            events.append(f"restore:{db_name}@{_current_container()}")
            return restore_ok, list(sql_errors)

        def fake_rename(old, new, host, port, user):
            if old not in databases or new in databases:
                return False
            databases.discard(old)
            databases.add(new)
            events.append(f"rename:{old}>{new}")
            return True

        monkeypatch.setattr(
            "odoodev.core.docker_exec.docker_container_running", lambda name, cli="docker": running_odoo
        )
        monkeypatch.setattr(
            "odoodev.core.docker_exec.chown_recursive", lambda p, uid, gid: events.append("chown") or True
        )
        monkeypatch.setattr(
            "odoodev.core.docker_exec.ensure_dir_owner", lambda p, uid, gid: events.append("own_root") or True
        )
        monkeypatch.setattr("odoodev.core.database.check_restore_space", lambda *a, **kw: (True, "", 0))
        monkeypatch.setattr("odoodev.core.database.extract_backup", fake_extract)
        monkeypatch.setattr("odoodev.core.database.database_exists", fake_exists)
        monkeypatch.setattr("odoodev.core.database.drop_database", fake_drop)
        monkeypatch.setattr("odoodev.core.database.create_database", fake_create)
        monkeypatch.setattr("odoodev.core.database.restore_database_report", fake_restore)
        monkeypatch.setattr(
            "odoodev.core.database.count_installed_modules", lambda db, host, port, user: installed_modules
        )
        monkeypatch.setattr("odoodev.core.database.rename_database_quoted", fake_rename)
        monkeypatch.setattr("odoodev.core.database.dump_uses_pgvector", lambda sql_file: False)
        monkeypatch.setattr("odoodev.core.database.deactivate_cronjobs", record("cron"))
        monkeypatch.setattr("odoodev.core.database.neutralize_bank_sync", record("bank"))
        monkeypatch.setattr("odoodev.core.database.anonymize_database", record("anon"))
        monkeypatch.setattr("odoodev.core.database.wipe_database", record("wipe"))

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
        self.databases = databases
        return args, events, created, data_dir

    def test_full_restore_sequence(self, version_cfg, tmp_path, monkeypatch):
        args, events, created, data_dir = self._setup(tmp_path, monkeypatch, deactivate_cron=True, neutralize=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message

        # restored into the staging database, swapped in by renaming, old copy dropped last
        assert events[0] == "extract"
        db_events = [e for e in events if e.split(":")[0] in ("create", "restore", "rename", "drop")]
        assert db_events == [
            "create:production__odoodev_new",
            "restore:production__odoodev_new@test-db",
            "rename:production>production__odoodev_old",
            "rename:production__odoodev_new>production",
            "drop:production__odoodev_old",
        ]
        assert self.databases == {"production"}
        assert "cron@test-db" in events
        assert "bank@test-db" in events
        assert created["template"] == "template0"
        assert created["user"] == "ownerp"
        assert result.details["replaced_existing"] is True

        # filestore swapped: stale gone, new blob in place, sessions removed, no debris
        assert not (data_dir / "filestore" / "production" / "stale").exists()
        assert (data_dir / "filestore" / "production" / "aa" / "blob").read_text() == "new"
        assert sorted(p.name for p in (data_dir / "filestore").iterdir()) == ["production"]
        assert not (data_dir / "sessions").exists()
        assert "chown" in events

    def test_first_restore_into_empty_server(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, data_dir = self._setup(tmp_path, monkeypatch, existing=())
        import shutil

        shutil.rmtree(data_dir / "filestore")  # a fresh server has no filestore directory at all
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message
        assert self.databases == {"production"}
        assert not any(e.startswith("drop:") for e in events)
        assert (data_dir / "filestore" / "production" / "aa" / "blob").read_text() == "new"
        # the parent directory is handed to the Odoo user, not left to root
        assert "own_root" in events
        assert result.details["replaced_existing"] is False

    def test_failed_dump_leaves_existing_database_and_filestore(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, data_dir = self._setup(tmp_path, monkeypatch, restore_ok=False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "unchanged" in result.message
        assert self.databases == {"production"}
        assert not any(e.startswith("rename:") for e in events)
        assert (data_dir / "filestore" / "production" / "stale").read_text() == "old"
        assert (data_dir / "sessions" / "sess").exists()

    def test_failed_dump_quotes_what_psql_said(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(
            tmp_path,
            monkeypatch,
            restore_ok=False,
            sql_errors=["ERROR:  could not extend file: No space left on device"],
        )
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "No space left on device" in result.message

    def test_restored_copy_without_odoo_tables_is_never_swapped_in(self, version_cfg, tmp_path, monkeypatch):
        # psql exits 0 on failed statements — a dump that broke off early "restores" fine.
        args, events, _, data_dir = self._setup(
            tmp_path,
            monkeypatch,
            installed_modules=-1,
            sql_errors=['ERROR:  relation "ir_module_module" does not exist'],
        )
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "not a usable Odoo database" in result.message
        assert "ir_module_module" in result.message
        assert not any(e.startswith("rename:") for e in events)
        assert self.databases == {"production"}
        assert (data_dir / "filestore" / "production" / "stale").read_text() == "old"

    def test_check_restored_can_be_switched_off(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, installed_modules=-1, check_restored=False)
        assert sa.handle_server_restore(version_cfg, args).status == "ok"

    def test_harmless_sql_errors_are_reported_not_hidden(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, sql_errors=['ERROR:  role "other" does not exist'] * 3)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message
        assert "3 SQL error(s)" in result.message
        assert 'role "other" does not exist' in result.message

    def test_failed_swap_renames_previous_database_back(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, data_dir = self._setup(tmp_path, monkeypatch)
        real_rename = db_mod.rename_database_quoted

        def flaky(old, new, host, port, user):
            if old == "production__odoodev_new":
                return False
            return real_rename(old, new, host, port, user)

        monkeypatch.setattr("odoodev.core.database.rename_database_quoted", flaky)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "unchanged" in result.message
        assert self.databases == {"production"}
        assert (data_dir / "filestore" / "production" / "stale").read_text() == "old"
        assert sorted(p.name for p in (data_dir / "filestore").iterdir()) == ["production"]

    def test_failed_filestore_swap_rolls_everything_back(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, data_dir = self._setup(tmp_path, monkeypatch)
        real_os_rename = os.rename

        def failing(src, dst):
            if str(src).endswith(".odoodev_new"):
                raise OSError("disk says no")
            return real_os_rename(src, dst)

        monkeypatch.setattr("odoodev.core.server_automation.os.rename", failing)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "are unchanged" in result.message
        assert self.databases == {"production"}
        assert (data_dir / "filestore" / "production" / "stale").read_text() == "old"
        assert sorted(p.name for p in (data_dir / "filestore").iterdir()) == ["production"]

    def test_existing_database_without_drop_is_refused_untouched(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, drop=False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "drop: true" in result.message
        assert events == []

    def test_leftover_previous_database_stops_the_restore(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, existing=("production__odoodev_old",))
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "interrupted restore" in result.message
        assert events == []
        assert self.databases == {"production__odoodev_old"}

    def test_stale_staging_database_is_discarded(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, existing=("production", "production__odoodev_new"))
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message
        assert events.index("drop:production__odoodev_new") < events.index("create:production__odoodev_new")
        assert self.databases == {"production"}

    def test_unsupported_database_name(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch)
        args["db_name"] = 'prod"; DROP'
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "cannot be restored safely" in result.message
        assert events == []

    def test_hyphenated_database_name_is_supported(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, existing=())
        args["db_name"] = "acme-test.2026"
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message
        assert self.databases == {"acme-test.2026"}

    def test_pgvector_missing_stops_before_any_change(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, data_dir = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr("odoodev.core.database.dump_uses_pgvector", lambda sql_file: True)
        monkeypatch.setattr("odoodev.core.database.server_offers_pgvector", lambda host, port, user: False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "pgvector" in result.message
        assert events == ["extract"]
        assert self.databases == {"production"}
        assert (data_dir / "filestore" / "production" / "stale").exists()

    def test_pgvector_missing_can_be_overridden(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch, without_pgvector=True)
        monkeypatch.setattr("odoodev.core.database.dump_uses_pgvector", lambda sql_file: True)
        monkeypatch.setattr("odoodev.core.database.server_offers_pgvector", lambda host, port, user: False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message

    def test_pgvector_offered_passes(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr("odoodev.core.database.dump_uses_pgvector", lambda sql_file: True)
        monkeypatch.setattr("odoodev.core.database.server_offers_pgvector", lambda host, port, user: True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message
        assert result.details["notes"] == []

    def test_source_build_from_manifest_is_passed_on(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, _ = self._setup(tmp_path, monkeypatch)
        backup = tmp_path / "backups" / "production_live-db_dockerbackup_2026-07-12_02-00-00.tar.zst"
        (tmp_path / "backups" / (backup.name + ".manifest")).write_text("db_name=production\nodoo_build=26.09.29\n")
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok", result.message
        assert result.details["source_build"] == "26.09.29"

    def test_running_odoo_container_blocks_restore(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, running_odoo=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "still running" in result.message
        assert events == []

    def test_missing_filestore_is_hard_error_before_any_change(self, version_cfg, tmp_path, monkeypatch):
        args, events, _, _ = self._setup(tmp_path, monkeypatch, with_filestore=False)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "error"
        assert "no filestore" in result.message
        assert events == ["extract"]
        assert self.databases == {"production"}

    def test_missing_filestore_allowed_when_opted_in(self, version_cfg, tmp_path, monkeypatch):
        args, _, _, data_dir = self._setup(tmp_path, monkeypatch, with_filestore=False, allow_missing_filestore=True)
        result = sa.handle_server_restore(version_cfg, args)
        assert result.status == "ok"
        # an SQL-only backup replaces the database and leaves the filestore alone
        assert (data_dir / "filestore" / "production" / "stale").read_text() == "old"

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
# server.verify
# =============================================================================


class TestServerVerify:
    ARGS = {"odoo_container": "live-odoo", "db_container": "live-db", "db_name": "acme_prod", "timeout": 5}

    def _patch(
        self, monkeypatch, *, health="healthy", rows=(), psql_ok=True, port=("127.0.0.1", 11000), http=(200, "")
    ):
        seen: dict = {"urls": []}
        healths = list(health) if isinstance(health, list | tuple) else [health]

        def fake_health(name, cli="docker"):
            return healths.pop(0) if len(healths) > 1 else healths[0]

        def fake_tuples(query, db, host, port, user):
            seen["query_container"] = _current_container()
            seen["query_db"] = db
            return psql_ok, [list(r) for r in rows]

        def fake_http(url, timeout=20):
            seen["urls"].append(url)
            return http

        monkeypatch.setattr("odoodev.core.docker_exec.docker_health_status", fake_health)
        monkeypatch.setattr("odoodev.core.docker_exec.docker_published_port", lambda name, p, cli="docker": port)
        monkeypatch.setattr("odoodev.core.database._run_psql_tuples", fake_tuples)
        monkeypatch.setattr(sa, "_http_status", fake_http)
        monkeypatch.setattr(sa.time, "sleep", lambda seconds: None)
        return seen

    def test_all_checks_pass(self, version_cfg, monkeypatch):
        seen = self._patch(monkeypatch)
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "ok", result.message
        assert seen["query_container"] == "live-db"
        assert seen["query_db"] == "acme_prod"
        assert seen["urls"] == ["http://127.0.0.1:11000/web/login?db=acme_prod"]
        assert len(result.details["checks"]) == 3

    def test_waits_while_the_container_is_starting(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, health=["starting", "starting", "healthy"])
        assert sa.handle_server_verify(version_cfg, dict(self.ARGS)).status == "ok"

    @pytest.mark.parametrize(
        ("health", "expected"),
        [("unhealthy", "reports unhealthy"), ("stopped", "is not running"), ("missing", "does not exist")],
    )
    def test_container_state_is_an_error(self, version_cfg, monkeypatch, health, expected):
        self._patch(monkeypatch, health=health)
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "error"
        assert expected in result.message

    def test_image_without_healthcheck_passes_on_running(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, health="none")
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "ok"
        assert "no healthcheck" in result.message

    def test_pending_module_states_are_an_error(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, rows=[("base_setup", "to upgrade"), ("web", "to upgrade")])
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "error"
        assert "2 module(s)" in result.message
        assert "base_setup (to upgrade)" in result.message

    def test_unreadable_module_states_are_an_error_not_a_pass(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, psql_ok=False)
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "error"
        assert "Could not read the module states" in result.message

    def test_http_500_is_an_error(self, version_cfg, monkeypatch):
        # A healthy container whose registry cannot be built answers 500 on every page.
        self._patch(monkeypatch, http=(500, "INTERNAL SERVER ERROR"))
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "error"
        assert "HTTP 500" in result.message

    def test_redirect_or_client_error_is_odoo_answering(self, version_cfg, monkeypatch):
        self._patch(monkeypatch, http=(404, "NOT FOUND"))
        assert sa.handle_server_verify(version_cfg, dict(self.ARGS)).status == "ok"

    def test_unpublished_port_skips_http_and_says_so(self, version_cfg, monkeypatch):
        seen = self._patch(monkeypatch, port=None)
        result = sa.handle_server_verify(version_cfg, dict(self.ARGS))
        assert result.status == "ok"
        assert seen["urls"] == []
        assert "HTTP check skipped" in result.message

    def test_checks_can_be_switched_off(self, version_cfg, monkeypatch):
        seen = self._patch(monkeypatch, psql_ok=False, http=(500, ""))
        args = {**self.ARGS, "check_modules": False, "http_check": False}
        result = sa.handle_server_verify(version_cfg, args)
        assert result.status == "ok"
        assert seen["urls"] == []

    def test_kernel_older_than_the_backup_is_an_error(self, version_cfg, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(
            "odoodev.core.docker_exec.read_container_file",
            lambda name, path, cli="docker": "version_info = (19, 0, 0, FINAL, 0, '-26.03.10')\n",
        )
        args = {**self.ARGS, "_runtime": {"source_build": "26.09.29"}}
        result = sa.handle_server_verify(version_cfg, args)
        assert result.status == "error"
        assert "26.03.10" in result.message and "26.09.29" in result.message

    def test_kernel_as_new_as_the_backup_passes(self, version_cfg, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(
            "odoodev.core.docker_exec.read_container_file",
            lambda name, path, cli="docker": "version_info = (19, 0, 0, FINAL, 0, '-26.09.29')\n",
        )
        args = {**self.ARGS, "_runtime": {"source_build": "26.09.29"}}
        result = sa.handle_server_verify(version_cfg, args)
        assert result.status == "ok", result.message
        assert len(result.details["checks"]) == 4


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


# =============================================================================
# rename_database_quoted — the swap's only primitive
# =============================================================================


class TestRenameDatabaseQuoted:
    def _capture(self, monkeypatch, ok=True):
        queries: list[str] = []

        def fake_psql(command, db=None, host=None, port=None, user=None):
            queries.append(command)
            return ok, ""

        monkeypatch.setattr(db_mod, "_run_psql", fake_psql)
        return queries

    def test_hyphenated_names_are_quoted(self, monkeypatch):
        queries = self._capture(monkeypatch)
        assert db_mod.rename_database_quoted("acme-test", "acme-test__odoodev_old", "h", 0, "ownerp") is True
        # connections are closed first — ALTER DATABASE fails on a database in use
        assert "pg_terminate_backend" in queries[0] and "'acme-test'" in queries[0]
        assert queries[1] == 'ALTER DATABASE "acme-test" RENAME TO "acme-test__odoodev_old";'

    @pytest.mark.parametrize("name", ['a"b', "a'b", "a b", "a;b", "", "x" * 64])
    def test_names_that_could_leave_the_quotes_are_refused(self, monkeypatch, name):
        queries = self._capture(monkeypatch)
        assert db_mod.rename_database_quoted(name, "fine", "h", 0, "ownerp") is False
        assert db_mod.rename_database_quoted("fine", name, "h", 0, "ownerp") is False
        assert queries == []

    def test_failed_alter_is_reported(self, monkeypatch):
        self._capture(monkeypatch, ok=False)
        assert db_mod.rename_database_quoted("a", "b", "h", 0, "ownerp") is False


# =============================================================================
# restore_database_report — psql exits 0 on failed statements
# =============================================================================


class TestRestoreDatabaseReport:
    def _run(self, monkeypatch, tmp_path, stderr="", returncode=0):
        dump = tmp_path / "dump.sql"
        dump.write_text("-- sql")

        def fake_run(cmd, **kwargs):
            if returncode:
                import subprocess

                raise subprocess.CalledProcessError(returncode, cmd, stderr=stderr)
            return types.SimpleNamespace(returncode=0, stdout="", stderr=stderr)

        monkeypatch.setattr(db_mod.subprocess, "run", fake_run)
        return db_mod.restore_database_report("db", str(dump), host="localhost", port=18432, user="ownerp")

    def test_clean_restore(self, monkeypatch, tmp_path):
        assert self._run(monkeypatch, tmp_path) == (True, [])

    def test_harmless_errors_are_returned_and_do_not_fail(self, monkeypatch, tmp_path):
        ok, errors = self._run(monkeypatch, tmp_path, stderr='ERROR:  role "x" does not exist\nNOTICE: fine\n')
        assert ok is True
        assert errors == ['ERROR:  role "x" does not exist']

    @pytest.mark.parametrize(
        "line",
        [
            'ERROR:  could not extend file "base/16384/2619": No space left on device',
            "ERROR:  out of memory",
            "psql: error: FATAL:  server closed the connection unexpectedly",
            'ERROR:  invalid byte sequence for encoding "UTF8": 0xff',
        ],
    )
    def test_errors_that_mean_incomplete_data_fail(self, monkeypatch, tmp_path, line):
        ok, errors = self._run(monkeypatch, tmp_path, stderr=f'ERROR:  role "x" does not exist\n{line}\n')
        assert ok is False
        assert errors == [line]

    def test_psql_failure(self, monkeypatch, tmp_path):
        ok, errors = self._run(monkeypatch, tmp_path, stderr="psql: error: connection refused", returncode=2)
        assert ok is False
        assert errors == ["psql: error: connection refused"]

    def test_restore_database_keeps_its_bool_contract(self, monkeypatch, tmp_path):
        dump = tmp_path / "dump.sql"
        dump.write_text("-- sql")
        monkeypatch.setattr(
            db_mod.subprocess,
            "run",
            lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr='ERROR:  role "x" does not exist'),
        )
        assert db_mod.restore_database("db", str(dump), host="localhost", port=18432, user="ownerp") is True


def test_restore_uses_the_helper_when_the_data_directory_is_not_writable(version_cfg, tmp_path, monkeypatch):
    """An unprivileged account: every filestore change goes through the helper, none through the host."""
    helper_calls = []

    class FakeHelper:
        via_container = True

        def ensure_owned_dir(self, path, uid, gid):
            helper_calls.append("ensure")
            return True

        def place(self, src, dest, uid, gid):
            helper_calls.append("place")
            os.makedirs(dest)
            return ""

        def rename(self, old, new):
            helper_calls.append("rename")
            os.rename(old, new)

        def remove(self, path):
            helper_calls.append("remove")
            shutil.rmtree(path, ignore_errors=True)

    fixture = TestServerRestore()
    args, events, _created, data_dir = fixture._setup(tmp_path, monkeypatch)
    monkeypatch.setattr("odoodev.core.docker_exec.data_dir_ops", lambda data_dir, container: FakeHelper())

    result = sa.handle_server_restore(version_cfg, args)

    assert result.status == "ok", result.message
    assert "helper container" in result.message
    assert "place" in helper_calls and "rename" in helper_calls
    assert "chown" not in events and "own_root" not in events
    assert (data_dir / "filestore" / "production").is_dir()
