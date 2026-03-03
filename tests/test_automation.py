"""Tests for odoodev.core.automation — command handler functions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from odoodev.core.automation import (
    COMMAND_HANDLERS,
    handle_db_drop,
    handle_db_list,
    handle_docker_down,
    handle_docker_status,
    handle_docker_up,
    handle_env_check,
    handle_pull,
    handle_stop,
    handle_venv_check,
)


@pytest.fixture
def mock_version_cfg():
    """Create a mock VersionConfig for testing."""
    cfg = MagicMock()
    cfg.version = "18"
    cfg.ports.db = 18432
    cfg.ports.odoo = 18069
    cfg.paths.native_dir = "/tmp/test_native"
    cfg.paths.server_dir = "/tmp/test_server"
    cfg.paths.myconfs_dir = "/tmp/test_myconfs"
    cfg.paths.base_expanded = "/tmp/test_base"
    cfg.paths.server_subdir = "v18-server"
    cfg.paths.dev_dir = "/tmp/test_dev"
    cfg.git.server_url = "git@example.com:v18/v18-server.git"
    cfg.python = "3.13"
    return cfg


# =============================================================================
# Handler registry tests
# =============================================================================


class TestCommandHandlers:
    def test_all_commands_registered(self):
        expected = {
            "docker.up",
            "docker.down",
            "docker.status",
            "pull",
            "repos",
            "start",
            "stop",
            "db.list",
            "db.backup",
            "db.restore",
            "db.drop",
            "env.check",
            "venv.check",
            "venv.setup",
        }
        assert set(COMMAND_HANDLERS.keys()) == expected

    def test_all_handlers_callable(self):
        for name, handler in COMMAND_HANDLERS.items():
            assert callable(handler), f"Handler '{name}' is not callable"


# =============================================================================
# Docker handler tests
# =============================================================================


class TestDockerHandlers:
    @patch("odoodev.core.docker_compose.compose_up", return_value=0)
    def test_docker_up_success(self, mock_compose, mock_version_cfg):
        result = handle_docker_up(mock_version_cfg, {})
        assert result.status == "ok"
        mock_compose.assert_called_once_with("/tmp/test_native", detach=True)

    @patch("odoodev.core.docker_compose.compose_up", return_value=1)
    def test_docker_up_failure(self, mock_compose, mock_version_cfg):
        result = handle_docker_up(mock_version_cfg, {})
        assert result.status == "error"
        assert result.exit_code == 1

    @patch("odoodev.core.docker_compose.compose_down", return_value=0)
    def test_docker_down_success(self, mock_compose, mock_version_cfg):
        result = handle_docker_down(mock_version_cfg, {})
        assert result.status == "ok"

    @patch("odoodev.core.docker_compose.compose_ps", return_value=0)
    def test_docker_status_success(self, mock_compose, mock_version_cfg):
        result = handle_docker_status(mock_version_cfg, {})
        assert result.status == "ok"


# =============================================================================
# Database handler tests
# =============================================================================


class TestDbHandlers:
    @patch("odoodev.core.database.list_databases", return_value=["db1", "db2"])
    @patch("odoodev.core.automation._load_env_vars", return_value={})
    def test_db_list(self, mock_env, mock_list, mock_version_cfg):
        result = handle_db_list(mock_version_cfg, {})
        assert result.status == "ok"
        assert result.details["databases"] == ["db1", "db2"]
        assert "2 database" in result.message

    @patch("odoodev.core.database.drop_database", return_value=True)
    @patch("odoodev.core.automation._load_env_vars", return_value={})
    def test_db_drop_success(self, mock_env, mock_drop, mock_version_cfg):
        result = handle_db_drop(mock_version_cfg, {"name": "testdb"})
        assert result.status == "ok"
        mock_drop.assert_called_once()

    @patch("odoodev.core.database.drop_database", return_value=False)
    @patch("odoodev.core.automation._load_env_vars", return_value={})
    def test_db_drop_failure(self, mock_env, mock_drop, mock_version_cfg):
        result = handle_db_drop(mock_version_cfg, {"name": "testdb"})
        assert result.status == "error"

    def test_db_drop_missing_name(self, mock_version_cfg):
        result = handle_db_drop(mock_version_cfg, {})
        assert result.status == "error"
        assert "name" in result.message.lower()


# =============================================================================
# Stop handler tests
# =============================================================================


class TestStopHandler:
    @patch("odoodev.core.docker_compose.compose_down", return_value=0)
    @patch("odoodev.core.process_manager.stop_process", return_value=True)
    @patch("odoodev.core.process_manager.find_odoo_process", return_value=[1234])
    def test_stop_with_process(self, mock_find, mock_stop, mock_compose, mock_version_cfg):
        result = handle_stop(mock_version_cfg, {})
        assert result.status == "ok"
        mock_stop.assert_called_once_with(1234, timeout=5, force=False)
        mock_compose.assert_called_once()

    @patch("odoodev.core.docker_compose.compose_down", return_value=0)
    @patch("odoodev.core.process_manager.find_odoo_process", return_value=[])
    def test_stop_no_process(self, mock_find, mock_compose, mock_version_cfg):
        result = handle_stop(mock_version_cfg, {})
        assert result.status == "ok"
        assert "No Odoo process" in result.message

    @patch("odoodev.core.process_manager.find_odoo_process", return_value=[1234])
    @patch("odoodev.core.process_manager.stop_process", return_value=True)
    def test_stop_keep_docker(self, mock_stop, mock_find, mock_version_cfg):
        result = handle_stop(mock_version_cfg, {"keep-docker": True})
        assert result.status == "ok"
        assert "Docker" not in result.message


# =============================================================================
# Environment / venv handler tests
# =============================================================================


class TestEnvVenvHandlers:
    def test_env_check_no_file(self, mock_version_cfg):
        result = handle_env_check(mock_version_cfg, {})
        assert result.status == "error"
        assert ".env" in result.message

    @patch("dotenv.dotenv_values")
    def test_env_check_complete(self, mock_dotenv, mock_version_cfg, tmp_dir):
        mock_version_cfg.paths.native_dir = tmp_dir
        env_file = os.path.join(tmp_dir, ".env")
        with open(env_file, "w") as f:
            f.write("ENV_NAME=test\n")

        mock_dotenv.return_value = {
            "ENV_NAME": "test",
            "ODOO_VERSION": "18",
            "PLATFORM": "macos",
            "DEV_USER": "test",
            "DB_PORT": "18432",
            "PGUSER": "ownerp",
            "PGPASSWORD": "test",
            "ODOO_PORT": "18069",
            "GEVENT_PORT": "18072",
            "POSTGRES_VERSION": "16",
            "DOCKER_PLATFORM": "linux/arm64",
        }

        result = handle_env_check(mock_version_cfg, {})
        assert result.status == "ok"

    @patch("dotenv.dotenv_values")
    def test_env_check_missing_vars(self, mock_dotenv, mock_version_cfg, tmp_dir):
        mock_version_cfg.paths.native_dir = tmp_dir
        env_file = os.path.join(tmp_dir, ".env")
        with open(env_file, "w") as f:
            f.write("ENV_NAME=test\n")

        mock_dotenv.return_value = {"ENV_NAME": "test"}

        result = handle_env_check(mock_version_cfg, {})
        assert result.status == "error"
        assert "Missing" in result.message

    def test_venv_check_no_venv(self, mock_version_cfg):
        result = handle_venv_check(mock_version_cfg, {})
        assert result.status == "error"
        assert "venv" in result.message.lower()

    def test_venv_check_exists(self, mock_version_cfg, tmp_dir):
        mock_version_cfg.paths.native_dir = tmp_dir
        venv_dir = os.path.join(tmp_dir, ".venv")
        os.makedirs(os.path.join(venv_dir, "bin"))
        # Create a fake python3 binary
        python_bin = os.path.join(venv_dir, "bin", "python3")
        with open(python_bin, "w") as f:
            f.write("#!/bin/bash\n")

        result = handle_venv_check(mock_version_cfg, {})
        assert result.status == "ok"


# =============================================================================
# Pull handler tests
# =============================================================================


class TestPullHandler:
    @patch("odoodev.commands.repos._find_repos_config", return_value=None)
    def test_pull_no_repos_config(self, mock_find, mock_version_cfg):
        result = handle_pull(mock_version_cfg, {})
        assert result.status == "error"
        assert "repos.yaml" in result.message
