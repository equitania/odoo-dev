"""Tests for the container runtime abstraction (Docker vs Apple Container)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from odoodev.core.container_backend import (
    RUNTIME_APPLE,
    RUNTIME_DOCKER,
    AppleContainerBackend,
    DockerBackend,
    PostgresSpec,
    _parse_apple_stats,
    _postgres_run_args,
    get_backend,
)


class TestParseAppleStats:
    def test_extracts_mem_and_cpu(self):
        raw = (
            "Container ID  Cpu %  Memory Usage  Net Rx/Tx  Block I/O  Pids\n"
            "odoodev-bench-pg-container  0.06%  186.79 MiB / 1.00 GiB  "
            "10.14 KiB / 1.75 KiB  80.70 MiB / 50.40 MiB  6\n"
        )
        assert _parse_apple_stats(raw) == "186.79 MiB / 1.00 GiB / CPU 0.06%"

    def test_returns_none_when_unparseable(self):
        assert _parse_apple_stats("no useful numbers here") is None


def _spec() -> PostgresSpec:
    return PostgresSpec(
        image="postgres:16.11-alpine",
        container_name="odoodev-bench-pg-docker",
        volume_name="odoodev-bench-vol-docker",
        host_port=55432,
        user="ownerp",
        password="secret",
        db_name="odoodev_bench",
    )


class TestPostgresRunArgs:
    def test_contains_core_flags(self):
        args = _postgres_run_args(_spec())
        assert args[0] == "run"
        assert "-d" in args
        assert "--name" in args and "odoodev-bench-pg-docker" in args
        # Port publish and volume mount.
        assert "55432:5432" in args
        assert "odoodev-bench-vol-docker:/var/lib/postgresql/data" in args
        # Env values.
        assert "POSTGRES_USER=ownerp" in args
        assert "POSTGRES_PASSWORD=secret" in args
        assert "POSTGRES_DB=odoodev_bench" in args
        # PGDATA points at a SUBDIRECTORY of the mount so Apple Container's
        # EXT4-backed volume (with its lost+found root) doesn't break initdb.
        assert "PGDATA=/var/lib/postgresql/data/pgdata" in args
        # shm-size matches the compose default.
        assert "--shm-size" in args and "1g" in args
        # Image is the final positional argument.
        assert args[-1] == "postgres:16.11-alpine"

    def test_run_args_identical_shape_for_both_runtimes(self):
        # The builder is runtime-agnostic; both backends prepend their own CLI.
        args = _postgres_run_args(_spec())
        assert isinstance(args, list)
        assert all(isinstance(a, str) for a in args)


class TestFactory:
    def test_docker(self):
        assert isinstance(get_backend(RUNTIME_DOCKER), DockerBackend)

    def test_apple(self):
        assert isinstance(get_backend(RUNTIME_APPLE), AppleContainerBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_backend("podman")


class TestDockerBackend:
    @patch("odoodev.core.container_backend.command_exists", return_value=True)
    @patch("odoodev.core.container_backend.subprocess.run")
    def test_is_available_true(self, mock_run, _cmd):
        mock_run.return_value = MagicMock(returncode=0)
        assert DockerBackend().is_available() is True

    @patch("odoodev.core.container_backend.command_exists", return_value=False)
    def test_is_available_no_cli(self, _cmd):
        assert DockerBackend().is_available() is False

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_run_postgres_invokes_docker_run(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        DockerBackend().run_postgres(_spec())
        argv = mock_run.call_args[0][0]
        assert argv[0] == "docker"
        assert argv[1] == "run"

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_stop_postgres_uses_rm_force(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        DockerBackend().stop_postgres("c1")
        argv = mock_run.call_args[0][0]
        assert argv == ["docker", "rm", "-f", "c1"]

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_remove_volume(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        DockerBackend().remove_volume("v1")
        argv = mock_run.call_args[0][0]
        assert argv == ["docker", "volume", "rm", "v1"]


class TestAppleContainerBackend:
    @patch("odoodev.core.container_backend.command_exists", return_value=True)
    @patch("odoodev.core.container_backend.subprocess.run")
    def test_is_available_true(self, mock_run, _cmd):
        mock_run.return_value = MagicMock(returncode=0)
        assert AppleContainerBackend().is_available() is True

    @patch("odoodev.core.container_backend.command_exists", return_value=False)
    def test_is_available_no_cli(self, _cmd):
        assert AppleContainerBackend().is_available() is False

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_run_postgres_invokes_container_run(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        AppleContainerBackend().run_postgres(_spec())
        argv = mock_run.call_args[0][0]
        assert argv[0] == "container"
        assert argv[1] == "run"

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_pull_image_uses_image_pull(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        AppleContainerBackend().pull_image("postgres:16")
        argv = mock_run.call_args[0][0]
        assert argv == ["container", "image", "pull", "postgres:16"]

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_stop_postgres_stops_then_deletes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        AppleContainerBackend().stop_postgres("c1")
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["container", "stop", "c1"] in calls
        assert ["container", "delete", "c1"] in calls
