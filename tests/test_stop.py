"""Tests for odoodev stop command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from odoodev.cli import cli


class TestStopHelp:
    def test_stop_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["stop", "--help"])
        assert result.exit_code == 0
        assert "Stop Odoo server" in result.output
        assert "--keep-docker" in result.output
        assert "--force" in result.output


class TestStopNoRunningOdoo:
    def test_stop_no_running_odoo_shows_warning(self):
        runner = CliRunner()
        with (
            patch("odoodev.commands.stop.find_odoo_process", return_value=[]),
            patch("odoodev.commands.stop.subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = runner.invoke(cli, ["stop", "18"])
        assert result.exit_code == 0
        assert "No Odoo process found" in result.output


class TestStopDockerBehavior:
    def test_stop_calls_docker_down_by_default(self):
        runner = CliRunner()
        docker_mock = MagicMock(returncode=0)
        with (
            patch("odoodev.commands.stop.find_odoo_process", return_value=[]),
            patch("odoodev.commands.stop.subprocess.run", return_value=docker_mock) as mock_run,
        ):
            result = runner.invoke(cli, ["stop", "18"])
        assert result.exit_code == 0
        # docker compose down should have been called
        assert mock_run.called
        call_args = mock_run.call_args
        assert "docker" in call_args[0][0]
        assert "down" in call_args[0][0]

    def test_stop_keep_docker_skips_docker_down(self):
        runner = CliRunner()
        with (
            patch("odoodev.commands.stop.find_odoo_process", return_value=[]),
            patch("odoodev.commands.stop.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["stop", "18", "--keep-docker"])
        assert result.exit_code == 0
        assert "Keeping Docker" in result.output
        # subprocess.run should NOT have been called (no docker down)
        mock_run.assert_not_called()


class TestStopWithRunningProcess:
    def test_stop_kills_found_pids(self):
        runner = CliRunner()
        with (
            patch("odoodev.commands.stop.find_odoo_process", return_value=[12345]),
            patch("odoodev.commands.stop.stop_process", return_value=True) as mock_stop,
            patch("odoodev.commands.stop.subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = runner.invoke(cli, ["stop", "18"])
        assert result.exit_code == 0
        mock_stop.assert_called_once_with(12345, timeout=5, force=False)
        assert "stopped" in result.output

    def test_stop_force_flag_passed_through(self):
        runner = CliRunner()
        with (
            patch("odoodev.commands.stop.find_odoo_process", return_value=[12345]),
            patch("odoodev.commands.stop.stop_process", return_value=True) as mock_stop,
            patch("odoodev.commands.stop.subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = runner.invoke(cli, ["stop", "18", "--force"])
        assert result.exit_code == 0
        mock_stop.assert_called_once_with(12345, timeout=5, force=True)

    def test_stop_failed_process_exits_nonzero(self):
        runner = CliRunner()
        with (
            patch("odoodev.commands.stop.find_odoo_process", return_value=[12345]),
            patch("odoodev.commands.stop.stop_process", return_value=False),
            patch("odoodev.commands.stop.subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = runner.invoke(cli, ["stop", "18"])
        assert result.exit_code != 0
