"""Tests for venv_manager Python version validation functions."""

import os
import subprocess
from unittest.mock import patch

from odoodev.core.venv_manager import (
    check_venv_python_matches,
    get_venv_python_version,
    install_requirements,
)


def _completed(returncode: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr="")


class TestInstallRequirements:
    """Tests for install_requirements() including the --refresh retry fallback."""

    def test_success_first_try_no_retry(self, tmp_dir):
        """Should run uv once and not refresh when the install succeeds."""
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=_completed(0)) as mock_run:
            result = install_requirements(tmp_dir, "/path/requirements.txt")

        assert result is True
        mock_run.assert_called_once()
        assert "--refresh" not in mock_run.call_args.args[0]

    def test_retries_with_refresh_on_failure(self, tmp_dir):
        """Should retry once with --refresh when the first install fails."""
        with (
            patch(
                "odoodev.core.venv_manager.subprocess.run",
                side_effect=[_completed(1), _completed(0)],
            ) as mock_run,
            patch("odoodev.core.venv_manager.print_warning"),
        ):
            result = install_requirements(tmp_dir, "/path/requirements.txt")

        assert result is True
        assert mock_run.call_count == 2
        # First call without --refresh, retry with --refresh
        assert "--refresh" not in mock_run.call_args_list[0].args[0]
        assert "--refresh" in mock_run.call_args_list[1].args[0]

    def test_returns_false_when_refresh_also_fails(self, tmp_dir):
        """Should return False when both the install and the refresh retry fail."""
        with (
            patch(
                "odoodev.core.venv_manager.subprocess.run",
                side_effect=[_completed(1), _completed(1)],
            ) as mock_run,
            patch("odoodev.core.venv_manager.print_warning"),
        ):
            result = install_requirements(tmp_dir, "/path/requirements.txt")

        assert result is False
        assert mock_run.call_count == 2

    def test_capture_false_streams_output(self, tmp_dir):
        """Should pass capture_output=False so uv output streams to the console."""
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=_completed(0)) as mock_run:
            install_requirements(tmp_dir, "/path/requirements.txt", capture=False)

        assert mock_run.call_args.kwargs["capture_output"] is False

    def test_cwd_is_passed_through(self, tmp_dir):
        """Should forward the cwd argument to the uv subprocess."""
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=_completed(0)) as mock_run:
            install_requirements(tmp_dir, "/path/requirements.txt", cwd="/work/dir")

        assert mock_run.call_args.kwargs["cwd"] == "/work/dir"


class TestGetVenvPythonVersion:
    """Tests for get_venv_python_version()."""

    def test_returns_version_string(self, tmp_dir):
        """Should return major.minor version when python3 binary works."""
        python_bin = os.path.join(tmp_dir, "bin", "python3")
        os.makedirs(os.path.dirname(python_bin))
        # Create a dummy file so exists() passes
        with open(python_bin, "w") as f:
            f.write("")

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="3.13\n", stderr="")
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result) as mock_run:
            result = get_venv_python_version(tmp_dir)

        assert result == "3.13"
        mock_run.assert_called_once()

    def test_returns_none_when_no_binary(self, tmp_dir):
        """Should return None when python3 binary does not exist."""
        result = get_venv_python_version(tmp_dir)
        assert result is None

    def test_returns_none_on_nonzero_exit(self, tmp_dir):
        """Should return None when python3 returns non-zero exit code."""
        python_bin = os.path.join(tmp_dir, "bin", "python3")
        os.makedirs(os.path.dirname(python_bin))
        with open(python_bin, "w") as f:
            f.write("")

        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_venv_python_version(tmp_dir)

        assert result is None

    def test_returns_none_on_timeout(self, tmp_dir):
        """Should return None when subprocess times out."""
        python_bin = os.path.join(tmp_dir, "bin", "python3")
        os.makedirs(os.path.dirname(python_bin))
        with open(python_bin, "w") as f:
            f.write("")

        with patch(
            "odoodev.core.venv_manager.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="python3", timeout=5),
        ):
            result = get_venv_python_version(tmp_dir)

        assert result is None

    def test_returns_none_on_os_error(self, tmp_dir):
        """Should return None when OSError occurs."""
        python_bin = os.path.join(tmp_dir, "bin", "python3")
        os.makedirs(os.path.dirname(python_bin))
        with open(python_bin, "w") as f:
            f.write("")

        with patch("odoodev.core.venv_manager.subprocess.run", side_effect=OSError("broken")):
            result = get_venv_python_version(tmp_dir)

        assert result is None


class TestCheckVenvPythonMatches:
    """Tests for check_venv_python_matches()."""

    def test_matching_version_returns_true(self, tmp_dir):
        """Should return True when versions match."""
        with patch("odoodev.core.venv_manager.get_venv_python_version", return_value="3.13"):
            assert check_venv_python_matches(tmp_dir, "3.13") is True

    def test_mismatched_version_returns_false(self, tmp_dir):
        """Should return False when versions differ."""
        with patch("odoodev.core.venv_manager.get_venv_python_version", return_value="3.12"):
            assert check_venv_python_matches(tmp_dir, "3.13") is False

    def test_none_version_returns_false(self, tmp_dir):
        """Should return False when version is not determinable."""
        with patch("odoodev.core.venv_manager.get_venv_python_version", return_value=None):
            assert check_venv_python_matches(tmp_dir, "3.13") is False
