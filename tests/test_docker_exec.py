"""Tests for odoodev.core.docker_exec — server-mode Docker primitives."""

from __future__ import annotations

import os
import subprocess
import time

import pytest

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


# --- docker_health_status ---


def test_health_status_values(monkeypatch):
    for stdout, expected in (
        ("true|healthy\n", "healthy"),
        ("true|starting\n", "starting"),
        ("true|unhealthy\n", "unhealthy"),
        ("true|none\n", "none"),
        ("false|none\n", "stopped"),
    ):
        _patch_run(monkeypatch, lambda cmd, kw, out=stdout: FakeCompleted(0, out))
        assert dx.docker_health_status("live-odoo") == expected


def test_health_status_missing_container(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "No such object"))
    assert dx.docker_health_status("nope") == "missing"


# --- docker_published_port ---


def test_published_port_loopback(monkeypatch):
    calls = _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, "127.0.0.1:11000\n"))
    assert dx.docker_published_port("live-odoo", 8069) == ("127.0.0.1", 11000)
    assert calls[0] == ["docker", "port", "live-odoo", "8069"]


def test_published_port_wildcard_is_reached_via_loopback(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(0, "0.0.0.0:8080\n[::]:8080\n"))
    assert dx.docker_published_port("odoo", 8069) == ("127.0.0.1", 8080)


def test_published_port_not_published(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "no public port"))
    assert dx.docker_published_port("live-db", 5432) is None


# --- read_container_file ---


def test_read_file_from_running_container_uses_exec(monkeypatch):
    def responder(cmd, kw):
        if cmd[1] == "inspect":
            return FakeCompleted(0, "true\n")
        return FakeCompleted(0, "content")

    calls = _patch_run(monkeypatch, responder)
    assert dx.read_container_file("live-odoo", "/opt/odoo/x") == "content"
    assert calls[-1] == ["docker", "exec", "live-odoo", "cat", "/opt/odoo/x"]


def test_read_file_from_stopped_container_runs_its_image(monkeypatch):
    def responder(cmd, kw):
        if cmd[1] == "inspect" and "{{.State.Running}}" in cmd:
            return FakeCompleted(0, "false\n")
        if cmd[1] == "inspect":
            return FakeCompleted(0, "odoo/live:latest\n")
        return FakeCompleted(0, "content")

    calls = _patch_run(monkeypatch, responder)
    assert dx.read_container_file("live-odoo", "/opt/odoo/x") == "content"
    # throwaway run of the image: no network, no entrypoint script, removed afterwards
    assert calls[-1] == [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "cat",
        "odoo/live:latest",
        "/opt/odoo/x",
    ]


def test_read_file_unreadable_is_none(monkeypatch):
    _patch_run(monkeypatch, lambda cmd, kw: FakeCompleted(1, "", "boom"))
    assert dx.read_container_file("nope", "/x") is None


# --- ensure_dir_owner ---


def test_ensure_dir_owner_creates_and_chowns(tmp_path, monkeypatch):
    chowned = []
    monkeypatch.setattr(dx.os, "chown", lambda path, uid, gid: chowned.append((path, uid, gid)))
    target = tmp_path / "data" / "filestore"
    assert dx.ensure_dir_owner(str(target), 1000, 1000) is True
    assert target.is_dir()
    assert chowned == [(str(target), 1000, 1000)]


def test_ensure_dir_owner_leaves_a_correct_owner_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(dx.os, "chown", lambda *a: (_ for _ in ()).throw(AssertionError("must not chown")))
    stat = os.stat(tmp_path)
    assert dx.ensure_dir_owner(str(tmp_path), stat.st_uid, stat.st_gid) is True


def test_ensure_dir_owner_reports_failure(tmp_path, monkeypatch):
    def denied(path, uid, gid):
        raise PermissionError("not root")

    monkeypatch.setattr(dx.os, "chown", denied)
    assert dx.ensure_dir_owner(str(tmp_path / "filestore"), 1000, 1000) is False


# --- data directory operations without root ---


class _Recorder:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls = []
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def test_data_dir_ops_root_works_on_the_host(tmp_path, monkeypatch):
    monkeypatch.setattr(dx.os, "geteuid", lambda: 0)
    assert isinstance(dx.data_dir_ops(str(tmp_path), "live-db"), dx.HostDataDir)


def test_data_dir_ops_writable_directory_works_on_the_host(tmp_path, monkeypatch):
    monkeypatch.setattr(dx.os, "geteuid", lambda: 1001)
    (tmp_path / "filestore").mkdir()
    assert isinstance(dx.data_dir_ops(str(tmp_path), "live-db"), dx.HostDataDir)


def test_data_dir_ops_unprivileged_account_gets_the_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(dx.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(dx.os, "access", lambda path, mode: False)
    monkeypatch.setattr(dx, "docker_container_image", lambda name, cli="docker": "postgres:17.11")
    ops = dx.data_dir_ops(str(tmp_path), "live-db")
    assert isinstance(ops, dx.HelperDataDir)
    assert ops.image == "postgres:17.11"
    assert ops.via_container is True


def test_helper_place_runs_as_root_without_network_and_passes_paths_as_arguments(tmp_path, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(dx.subprocess, "run", recorder)
    data_dir = tmp_path / "live"
    src = tmp_path / "extract" / "filestore"
    data_dir.mkdir()
    src.mkdir(parents=True)
    ops = dx.HelperDataDir(str(data_dir), "postgres:17.11")

    assert ops.place(str(src), str(data_dir / "filestore" / "acme_prod.odoodev_new"), 1000, 1000) == ""

    cmd = recorder.calls[0]
    assert cmd[:9] == ["docker", "run", "--rm", "--user", "0:0", "--network", "none", "--entrypoint", "sh"]
    assert f"{data_dir.resolve()}:{dx.HELPER_DATA_MOUNT}" in cmd
    assert f"{src.resolve()}:{dx.HELPER_SOURCE_MOUNT}" in cmd
    script = cmd[cmd.index("-c") + 1]
    assert "acme_prod" not in script
    assert cmd[-3:] == [dx.HELPER_SOURCE_MOUNT, f"{dx.HELPER_DATA_MOUNT}/filestore/acme_prod.odoodev_new", "1000:1000"]


def test_helper_place_reports_the_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(dx.subprocess, "run", _Recorder(returncode=1, stderr="cp: no space left"))
    ops = dx.HelperDataDir(str(tmp_path), "postgres:17.11")
    assert "no space left" in ops.place(str(tmp_path / "src"), str(tmp_path / "filestore" / "db"), 1000, 1000)


def test_helper_rename_raises_oserror_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(dx.subprocess, "run", _Recorder(returncode=1, stderr="mv: cannot move"))
    ops = dx.HelperDataDir(str(tmp_path), "postgres:17.11")
    with pytest.raises(OSError, match="cannot move"):
        ops.rename(str(tmp_path / "filestore" / "a"), str(tmp_path / "filestore" / "b"))


def test_helper_refuses_a_path_outside_the_data_directory(tmp_path):
    ops = dx.HelperDataDir(str(tmp_path / "live"), "postgres:17.11")
    with pytest.raises(ValueError, match="outside"):
        ops._data(str(tmp_path / "elsewhere"))


def test_helper_remove_skips_a_missing_path(tmp_path, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(dx.subprocess, "run", recorder)
    dx.HelperDataDir(str(tmp_path), "postgres:17.11").remove(str(tmp_path / "sessions"))
    assert recorder.calls == []
