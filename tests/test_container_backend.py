"""Tests for the container runtime abstraction (Docker vs Apple Container)."""

from __future__ import annotations

from types import SimpleNamespace
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
    build_dev_spec,
    get_backend,
    read_env_file,
    resolve_runtime,
)


def _vcfg(native_dir: str):
    return SimpleNamespace(
        version="18",
        postgres="16.11-alpine",
        ports=SimpleNamespace(db=18432),
        paths=SimpleNamespace(native_dir=native_dir),
    )


class TestResolveRuntime:
    def test_override(self):
        assert resolve_runtime("apple") == "apple"

    def test_invalid_override(self):
        with pytest.raises(ValueError):
            resolve_runtime("podman")

    def test_default_from_config(self, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: SimpleNamespace(container_runtime="apple"),
        )
        assert resolve_runtime(None) == "apple"


class TestReadEnvFile:
    def test_parses_and_expands_user(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USER", "alice")
        (tmp_path / ".env").write_text('# comment\nDB_PORT=18432\nDEV_USER=${USER}\nPGUSER="ownerp"\n\n')
        env = read_env_file(str(tmp_path))
        assert env["DB_PORT"] == "18432"
        assert env["DEV_USER"] == "alice"
        assert env["PGUSER"] == "ownerp"

    def test_missing_returns_empty(self, tmp_path):
        assert read_env_file(str(tmp_path)) == {}


class TestBuildDevSpec:
    def test_mirrors_compose_naming(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: SimpleNamespace(database=SimpleNamespace(user="cfg", password="cfgpw")),
        )
        env = {
            "DEV_USER": "tester",
            "DB_PORT": "18432",
            "POSTGRES_VERSION": "16.11-alpine",
            "PGUSER": "ownerp",
            "PGPASSWORD": "pw",
        }
        spec = build_dev_spec(_vcfg(str(tmp_path)), env)
        assert spec.container_name == "tester-dev-db-18-native"
        assert spec.volume_name == "tester-vol-dev-db-18-native"
        assert spec.host_port == 18432
        assert spec.image == "postgres:16.11-alpine"
        assert spec.user == "ownerp"
        assert spec.password == "pw"
        assert spec.conf_path is None  # no postgresql.conf present

    def test_falls_back_to_config_creds_and_registry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: SimpleNamespace(database=SimpleNamespace(user="cfguser", password="cfgpw")),
        )
        spec = build_dev_spec(_vcfg(str(tmp_path)), {"DEV_USER": "t"})
        assert spec.user == "cfguser"
        assert spec.password == "cfgpw"
        assert spec.host_port == 18432  # from registry ports.db
        assert spec.image == "postgres:16.11-alpine"

    def test_conf_path_when_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: SimpleNamespace(database=SimpleNamespace(user="u", password="p")),
        )
        (tmp_path / "postgresql.conf").write_text("# tuning")
        spec = build_dev_spec(_vcfg(str(tmp_path)), {"DEV_USER": "t"})
        assert spec.conf_path == str(tmp_path / "postgresql.conf")
        args = _postgres_run_args(spec)
        assert f"{spec.conf_path}:/etc/postgresql/postgresql.conf" in args
        assert args[-3:] == ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]


class TestServiceDispatch:
    def test_docker_service_up_delegates_to_compose(self, monkeypatch):
        calls: dict = {}

        def fake_compose_up(compose_dir):
            calls["dir"] = compose_dir
            return 0

        monkeypatch.setattr("odoodev.core.docker_compose.compose_up", fake_compose_up)
        rc = DockerBackend().service_up(_vcfg("/native"), {})
        assert rc == 0
        assert calls["dir"] == "/native"

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_apple_service_up_runs_container(self, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.global_config.load_global_config",
            lambda: SimpleNamespace(database=SimpleNamespace(user="u", password="p")),
        )
        mock_run.return_value = MagicMock(returncode=0)
        rc = AppleContainerBackend().service_up(_vcfg(str(tmp_path)), {"DEV_USER": "t"})
        assert rc == 0
        argvs = [c.args[0] for c in mock_run.call_args_list]
        assert any(a[:2] == ["container", "run"] for a in argvs)
        run_argv = next(a for a in argvs if a[:2] == ["container", "run"])
        assert "PGDATA=/var/lib/postgresql/data/pgdata" in run_argv
        assert "t-dev-db-18-native" in run_argv


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

    def test_apple(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.container_backend.apple_runtime_supported", lambda: True)
        assert isinstance(get_backend(RUNTIME_APPLE), AppleContainerBackend)

    def test_apple_raises_when_unsupported(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.container_backend.apple_runtime_supported", lambda: False)
        with pytest.raises(SystemExit) as exc:
            get_backend(RUNTIME_APPLE)
        assert exc.value.code == 1

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


class TestFindContainerByPort:
    @patch("odoodev.core.container_backend.subprocess.run")
    def test_docker_matches_published_port(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "picard-dev-db-18-native\t0.0.0.0:18432->5432/tcp\n"
                "picard-dev-db-16-native\t0.0.0.0:16432->5432/tcp, [::]:16432->5432/tcp\n"
            ),
        )
        assert DockerBackend().find_container_by_port(16432) == "picard-dev-db-16-native"

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_docker_no_match_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="other\t0.0.0.0:8080->80/tcp\n")
        assert DockerBackend().find_container_by_port(16432) is None

    @patch("odoodev.core.container_backend.subprocess.run")
    def test_docker_ps_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert DockerBackend().find_container_by_port(16432) is None

    def test_apple_returns_none(self):
        # exec fallback is Docker-only for now — documents the current scope
        assert AppleContainerBackend().find_container_by_port(16432) is None
