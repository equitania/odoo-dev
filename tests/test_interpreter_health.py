"""Tests for interpreter health checks."""

from __future__ import annotations

import os
from unittest.mock import patch

from odoodev.core.prerequisites import (
    _resolve_symlink_chain,
    check_interpreter_health,
    check_venv_interpreter,
)

# ---------------------------------------------------------------------------
# _resolve_symlink_chain
# ---------------------------------------------------------------------------


class TestResolveSymlinkChain:
    """Tests for _resolve_symlink_chain()."""

    def test_regular_file(self, tmp_path):
        f = tmp_path / "python"
        f.write_text("binary")
        final, chain = _resolve_symlink_chain(str(f))
        assert final == str(f)
        assert chain == [str(f)]

    def test_single_symlink(self, tmp_path):
        target = tmp_path / "python3.12"
        target.write_text("binary")
        link = tmp_path / "python3"
        link.symlink_to(target)
        final, chain = _resolve_symlink_chain(str(link))
        assert final == str(target)
        assert len(chain) == 2

    def test_multi_level_symlink(self, tmp_path):
        """python3 → python → /path/to/cpython (real UV tool chain)."""
        real = tmp_path / "cpython-3.12" / "bin" / "python3.12"
        real.parent.mkdir(parents=True)
        real.write_text("binary")
        python = tmp_path / "python"
        python.symlink_to(real)
        python3 = tmp_path / "python3"
        python3.symlink_to("python")  # relative symlink
        final, chain = _resolve_symlink_chain(str(python3))
        assert final == str(real)
        assert len(chain) == 3

    def test_broken_symlink(self, tmp_path):
        link = tmp_path / "python3"
        link.symlink_to("/nonexistent/python3.13")
        final, chain = _resolve_symlink_chain(str(link))
        assert final == "/nonexistent/python3.13"
        assert not os.path.exists(final)

    def test_circular_symlink(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.symlink_to(b)
        b.symlink_to(a)
        # Should not infinite loop
        final, chain = _resolve_symlink_chain(str(a))
        assert len(chain) <= 4  # bounded by seen set


# ---------------------------------------------------------------------------
# check_interpreter_health
# ---------------------------------------------------------------------------


class TestCheckInterpreterHealth:
    """Tests for check_interpreter_health()."""

    @patch("odoodev.core.prerequisites.sys")
    @patch("odoodev.core.prerequisites._resolve_symlink_chain")
    def test_healthy_interpreter(self, mock_chain, mock_sys, tmp_path):
        python = tmp_path / "python3"
        python.write_text("binary")
        mock_sys.executable = str(python)
        mock_chain.return_value = (str(python), [str(python)])
        assert check_interpreter_health() is True

    @patch("odoodev.core.prerequisites.sys")
    @patch("odoodev.core.prerequisites._resolve_symlink_chain")
    def test_broken_interpreter(self, mock_chain, mock_sys):
        mock_sys.executable = "/fake/bin/python3"
        broken = "/nonexistent/cpython/python3.13"
        mock_chain.return_value = (broken, ["/fake/bin/python3", broken])
        assert check_interpreter_health() is False

    @patch("odoodev.core.prerequisites.sys")
    def test_empty_executable(self, mock_sys):
        mock_sys.executable = ""
        assert check_interpreter_health() is True  # cannot determine, assume OK

    @patch("odoodev.core.prerequisites.sys")
    @patch("odoodev.core.prerequisites._resolve_symlink_chain")
    @patch("os.path.islink", return_value=True)
    @patch("os.path.dirname")
    def test_uv_tool_dir_degraded_python_link(self, mock_dirname, mock_islink, mock_chain, mock_sys, tmp_path):
        """Test detection of degraded python link in UV tool directory."""
        tool_dir = tmp_path / ".local" / "share" / "uv" / "tools" / "odoodev" / "bin"
        tool_dir.mkdir(parents=True)
        python3 = tool_dir / "python3"
        python3.write_text("binary")

        mock_sys.executable = str(python3)
        # First call: main executable is OK
        # Second call within function: python link is broken
        mock_chain.side_effect = [
            (str(python3), [str(python3)]),
            ("/nonexistent/python3.12", [str(tool_dir / "python"), "/nonexistent/python3.12"]),
        ]
        mock_dirname.return_value = str(tool_dir)

        assert check_interpreter_health() is False


# ---------------------------------------------------------------------------
# check_venv_interpreter
# ---------------------------------------------------------------------------


class TestCheckVenvInterpreter:
    """Tests for check_venv_interpreter()."""

    def test_healthy_venv(self, tmp_path):
        """Venv with valid python3 → real binary."""
        venv = tmp_path / "venv"
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        real_python = tmp_path / "real_python"
        real_python.write_text("binary")
        (bin_dir / "python3").symlink_to(real_python)
        assert check_venv_interpreter(str(venv)) is True

    def test_broken_venv(self, tmp_path):
        """Venv with broken python3 symlink (target deleted)."""
        venv = tmp_path / "venv"
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python3").symlink_to("/nonexistent/cpython-3.13.2/bin/python3.13")
        assert check_venv_interpreter(str(venv)) is False

    def test_no_python_at_all(self, tmp_path):
        """Venv directory exists but no python3 binary."""
        venv = tmp_path / "venv"
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        assert check_venv_interpreter(str(venv)) is False

    def test_multi_level_broken(self, tmp_path):
        """python3 → python → deleted target (actual UV pattern)."""
        venv = tmp_path / "venv"
        bin_dir = venv / "bin"
        bin_dir.mkdir(parents=True)
        python = bin_dir / "python"
        python.symlink_to("/nonexistent/cpython-3.13.2/bin/python3.13")
        (bin_dir / "python3").symlink_to("python")
        assert check_venv_interpreter(str(venv)) is False

    def test_nonexistent_venv_dir(self, tmp_path):
        """Venv directory doesn't exist at all."""
        assert check_venv_interpreter(str(tmp_path / "nonexistent")) is False
