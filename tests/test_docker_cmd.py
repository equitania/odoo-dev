"""Tests for odoodev.commands.docker — PostgreSQL readiness gating in `docker up`."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

# Import cli first to resolve the circular import chain (cli → commands → cli)
import odoodev.cli  # noqa: F401
from odoodev.commands.docker import docker


class _Backend:
    name = "Docker"

    def __init__(self, up_rc: int = 0):
        self._up_rc = up_rc

    def service_up(self, cfg, env):
        return self._up_rc


class TestDockerUpReadiness:
    """`docker up` must wait for real PostgreSQL readiness, not just container start."""

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.docker.resolve_runtime", lambda override=None: "docker")
        monkeypatch.setattr("odoodev.commands.docker._has_compose_file", lambda cfg: True)
        monkeypatch.setattr("odoodev.commands.docker.read_env_file", lambda native_dir: {})
        monkeypatch.setattr("odoodev.commands.docker.get_backend", lambda rt: _Backend())
        monkeypatch.setattr("odoodev.core.migration_config.get_active_group", lambda: None)

    def test_up_succeeds_when_postgres_becomes_ready(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.prerequisites.wait_for_postgres_ready", lambda *a, **k: True)
        result = CliRunner().invoke(docker, ["up", "18"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "started" in result.output

    def test_up_fails_when_postgres_never_ready(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.prerequisites.wait_for_postgres_ready", lambda *a, **k: False)
        result = CliRunner().invoke(docker, ["up", "18"])
        assert result.exit_code == 1
        assert "did not become ready" in result.output


class TestDockerStatusRuntimeDiagnosis:
    """`docker status` reports a non-ready runtime with its remedy instead of a raw CLI error."""

    def test_status_reports_stopped_apple_api_server(self, monkeypatch):
        from odoodev.core.container_backend import RuntimeDiagnosis

        monkeypatch.setattr("odoodev.commands.docker.resolve_runtime", lambda override=None: "apple")
        monkeypatch.setattr(
            "odoodev.commands.docker.diagnose_runtime",
            lambda version=None, runtime=None: RuntimeDiagnosis(
                runtime="apple",
                backend_name="Apple Container",
                cli_installed=True,
                daemon_running=False,
                problem="Apple Container API server (container-apiserver) is not running",
                hints=("Start it: container system start",),
            ),
        )
        result = CliRunner().invoke(docker, ["status", "18"])
        assert result.exit_code == 1
        assert "container system start" in result.output
