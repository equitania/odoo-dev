"""Tests for odoodev.core.docker_exec — server-mode Docker primitives."""

from __future__ import annotations

import os
import time

from odoodev.core import docker_exec as dx


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_run(monkeypatch, responder):
    """Install a fake subprocess.run inside docker_exec; responder(cmd, kwargs) -> FakeCompleted."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return responder(list(cmd), kwargs)

    monkeypatch.setattr(dx.subprocess, "run", fake_run)
    return calls


# --- docker_container_running / docker_container_exists ---


def test_container_running_true(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, "true\n"))
    assert dx.docker_container_running("live-db") is True


def test_container_running_false_when_stopped(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, "false\n"))
    assert dx.docker_container_running("live-db") is False


def test_container_running_false_when_missing(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "No such object"))
    assert dx.docker_container_running("nope") is False


def test_container_running_false_without_docker_binary(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(dx.subprocess, "run", fake_run)
    assert dx.docker_container_running("live-db") is False


def test_container_exists(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, "abc123\n"))
    assert dx.docker_container_exists("test-odoo") is True


# --- docker_start / docker_stop ---


def test_docker_start_idempotent_when_running(monkeypatch):
    calls = _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, "true\n"))
    ok, msg = dx.docker_start("test-odoo")
    assert ok is True
    assert "already running" in msg
    # Only the inspect call — no `docker start` issued
    assert all(c[1] == "inspect" for c in calls)


def test_docker_start_starts_stopped_container(monkeypatch):
    def responder(cmd, kw):
        if cmd[1] == "inspect":
            return FakeCompleted(0, "false\n")
        return FakeCompleted(0, "test-odoo\n")

    calls = _patch_run(monkeypatch, responder)
    ok, msg = dx.docker_start("test-odoo")
    assert ok is True
    assert ["docker", "start", "test-odoo"] in calls


def test_docker_start_failure(monkeypatch):
    def responder(cmd, kw):
        if cmd[1] == "inspect":
            return FakeCompleted(0, "false\n")
        return FakeCompleted(1, "", "boom")

    _patch_run(monkeypatch, responder)
    ok, msg = dx.docker_start("test-odoo")
    assert ok is False
    assert "boom" in msg


def test_docker_stop_missing_container_is_error(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "No such object"))
    ok, msg = dx.docker_stop("ghost")
    assert ok is False
    assert "not found" in msg


def test_docker_stop_idempotent_when_stopped(monkeypatch):
    def responder(cmd, kw):
        if "{{.Id}}" in cmd[3]:
            return FakeCompleted(0, "abc\n")
        return FakeCompleted(0, "false\n")

    calls = _patch_run(monkeypatch, responder)
    ok, msg = dx.docker_stop("test-odoo")
    assert ok is True
    assert "already stopped" in msg
    assert all(c[1] == "inspect" for c in calls)


def test_docker_stop_running_container_uses_timeout(monkeypatch):
    def responder(cmd, kw):
        if cmd[1] == "inspect":
            return FakeCompleted(0, "abc\n" if "{{.Id}}" in cmd[3] else "true\n")
        return FakeCompleted(0)

    calls = _patch_run(monkeypatch, responder)
    ok, _ = dx.docker_stop("test-odoo", timeout=60)
    assert ok is True
    assert ["docker", "stop", "-t", "60", "test-odoo"] in calls


# --- docker_exec ---


def test_docker_exec_builds_command_and_decodes(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["input"] = kwargs.get("input")
        return FakeCompleted(0, b"out", b"")

    monkeypatch.setattr(dx.subprocess, "run", fake_run)
    ok, stdout, stderr = dx.docker_exec("live-db", ["psql", "-U", "ownerp"], stdin_data="SELECT 1;")
    assert ok is True
    assert stdout == "out"
    assert captured["cmd"][:4] == ["docker", "exec", "-i", "live-db"]
    assert captured["input"] == b"SELECT 1;"


def test_docker_exec_failure_returns_stderr(monkeypatch):
    monkeypatch.setattr(dx.subprocess, "run", lambda cmd, **kw: FakeCompleted(1, b"", b"denied"))
    ok, _, stderr = dx.docker_exec("live-db", ["psql"])
    assert ok is False
    assert stderr == "denied"


# --- resolve_container_host_path ---

_MOUNTS_BIND = '[{"Destination": "/opt/odoo/data", "Source": "/opt/odoo/test"}]'
_MOUNTS_VOLUME = (
    '[{"Destination": "/opt/odoo/data", "Source": "/var/lib/docker/volumes/vol-odoo-test/_data"},'
    ' {"Destination": "/etc/other", "Source": "/srv/other"}]'
)


def test_resolve_host_path_bind_mount(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, _MOUNTS_BIND))
    assert dx.resolve_container_host_path("test-odoo", "/opt/odoo/data") == "/opt/odoo/test"


def test_resolve_host_path_subpath_remainder(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, _MOUNTS_BIND))
    result = dx.resolve_container_host_path("test-odoo", "/opt/odoo/data/filestore/prod")
    assert result == "/opt/odoo/test/filestore/prod"


def test_resolve_host_path_named_volume(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, _MOUNTS_VOLUME))
    result = dx.resolve_container_host_path("test-odoo", "/opt/odoo/data")
    assert result == "/var/lib/docker/volumes/vol-odoo-test/_data"


def test_resolve_host_path_no_matching_mount(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, _MOUNTS_BIND))
    assert dx.resolve_container_host_path("test-odoo", "/somewhere/else") is None


def test_resolve_host_path_inspect_failure(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "No such object"))
    assert dx.resolve_container_host_path("ghost", "/opt/odoo/data") is None


def test_resolve_host_path_longest_prefix_wins(monkeypatch):
    mounts = (
        '[{"Destination": "/opt/odoo", "Source": "/host/broad"},'
        ' {"Destination": "/opt/odoo/data", "Source": "/host/narrow"}]'
    )
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, mounts))
    assert dx.resolve_container_host_path("c", "/opt/odoo/data/filestore") == "/host/narrow/filestore"


# --- chown_recursive ---


def test_chown_recursive_success(monkeypatch):
    calls = _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0))
    assert dx.chown_recursive("/opt/odoo/test/filestore/db", uid=1000, gid=1000) is True
    assert calls[0] == ["chown", "-R", "1000:1000", "/opt/odoo/test/filestore/db"]


def test_chown_recursive_failure(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "Operation not permitted"))
    assert dx.chown_recursive("/opt/x") is False


# --- find_latest_backup ---


def _touch(path, mtime):
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def test_find_latest_backup_by_mtime(tmp_path):
    now = time.time()
    _touch(tmp_path / "prod_live-db_dockerbackup_2026-07-10_02-00-00.tar.zst", now - 200)
    _touch(tmp_path / "prod_live-db_dockerbackup_2026-07-11_02-00-00.tar.zst", now - 100)
    _touch(tmp_path / "other_db_dockerbackup_2026-07-12_02-00-00.tar.zst", now)

    result = dx.find_latest_backup(str(tmp_path), "prod_live-db_dockerbackup_*.tar.zst")
    assert result is not None
    assert result.endswith("2026-07-11_02-00-00.tar.zst")


def test_find_latest_backup_by_filename_timestamp(tmp_path):
    now = time.time()
    # mtime order deliberately contradicts the filename timestamps
    _touch(tmp_path / "prod_live-db_dockerbackup_2026-07-11_02-00-00.tar.zst", now)
    _touch(tmp_path / "prod_live-db_dockerbackup_2026-07-12_02-00-00.tar.zst", now - 500)

    result = dx.find_latest_backup(str(tmp_path), "prod_*.tar.zst", select_by="filename_timestamp")
    assert result is not None
    assert result.endswith("2026-07-12_02-00-00.tar.zst")


def test_find_latest_backup_filename_mode_ignores_unstamped(tmp_path):
    _touch(tmp_path / "prod_manual.tar.zst", time.time())
    assert dx.find_latest_backup(str(tmp_path), "prod_*.tar.zst", select_by="filename_timestamp") is None


def test_find_latest_backup_no_match(tmp_path):
    assert dx.find_latest_backup(str(tmp_path), "*.tar.zst") is None


def test_find_latest_backup_ignores_directories(tmp_path):
    (tmp_path / "prod_dir.tar.zst").mkdir()
    _touch(tmp_path / "prod_file.tar.zst", time.time())
    result = dx.find_latest_backup(str(tmp_path), "prod_*.tar.zst")
    assert result is not None
    assert result.endswith("prod_file.tar.zst")
