"""Tests for venv Python patch-version freshness detection."""

from __future__ import annotations

from unittest.mock import patch

from odoodev.core.venv_manager import (
    _version_tuple,
    get_full_python_version,
    get_system_python_version,
)


class TestVersionTuple:
    """Tests for _version_tuple helper."""

    def test_three_parts(self):
        assert _version_tuple("3.13.2") == (3, 13, 2)

    def test_two_parts(self):
        assert _version_tuple("3.13") == (3, 13)

    def test_comparison(self):
        assert _version_tuple("3.13.12") > _version_tuple("3.13.2")

    def test_equal(self):
        assert _version_tuple("3.13.2") == _version_tuple("3.13.2")

    def test_major_difference(self):
        assert _version_tuple("4.0.0") > _version_tuple("3.99.99")


class TestGetFullPythonVersion:
    """Tests for get_full_python_version."""

    def test_returns_patch_version(self, tmp_path):
        venv_dir = str(tmp_path / ".venv")
        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python3").touch()

        mock_result = type("Result", (), {"returncode": 0, "stdout": "3.13.2\n"})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_full_python_version(venv_dir)
        assert result == "3.13.2"

    def test_returns_none_no_binary(self, tmp_path):
        venv_dir = str(tmp_path / ".venv")
        assert get_full_python_version(venv_dir) is None

    def test_returns_none_on_failure(self, tmp_path):
        venv_dir = str(tmp_path / ".venv")
        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python3").touch()

        mock_result = type("Result", (), {"returncode": 1, "stdout": ""})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_full_python_version(venv_dir)
        assert result is None


class TestGetSystemPythonVersion:
    """Tests for get_system_python_version."""

    UV_OUTPUT = """\
cpython-3.13.12-macos-aarch64-none    /opt/homebrew/bin/python3.13
cpython-3.13.2-macos-aarch64-none     /usr/local/bin/python3.13
cpython-3.12.9-macos-aarch64-none     /opt/homebrew/bin/python3.12
cpython-3.12.3-macos-aarch64-none     /usr/local/bin/python3.12
"""

    def test_finds_highest_patch(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": self.UV_OUTPUT})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_system_python_version("3.13")
        assert result == "3.13.12"

    def test_finds_different_major_minor(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": self.UV_OUTPUT})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_system_python_version("3.12")
        assert result == "3.12.9"

    def test_no_match(self):
        mock_result = type("Result", (), {"returncode": 0, "stdout": self.UV_OUTPUT})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_system_python_version("3.11")
        assert result is None

    def test_uv_not_found(self):
        with patch(
            "odoodev.core.venv_manager.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = get_system_python_version("3.13")
        assert result is None

    def test_uv_failure(self):
        mock_result = type("Result", (), {"returncode": 1, "stdout": ""})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_system_python_version("3.13")
        assert result is None

    def test_ignores_non_cpython(self):
        output = "pypy-3.13.1-macos-aarch64    /opt/pypy/bin/python3\n"
        mock_result = type("Result", (), {"returncode": 0, "stdout": output})()
        with patch("odoodev.core.venv_manager.subprocess.run", return_value=mock_result):
            result = get_system_python_version("3.13")
        assert result is None
