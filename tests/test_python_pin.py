"""Tests for the .python-version pin (v0.67.0).

The registry only carries major.minor ("3.13"), which uv resolves to whatever
3.13 it happens to prefer. A `.python-version` file next to the venv pins the
exact interpreter for one environment; these tests cover reading it, the
fallback when it is unusable, and the four places that consume the pin.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.venv_manager import PYTHON_VERSION_FILENAME, resolve_python_pin


def _write_pin(tmp_path, content: str) -> str:
    path = tmp_path / PYTHON_VERSION_FILENAME
    path.write_text(content)
    return str(path)


class TestResolvePythonPin:
    """Reading and validating .python-version."""

    def test_no_file_falls_back_to_registry(self, tmp_path):
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "3.13"
        assert pin.source == "registry"
        assert pin.path is None
        assert pin.warning is None
        assert pin.is_exact is False

    def test_exact_patch_version(self, tmp_path):
        path = _write_pin(tmp_path, "3.13.15\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "3.13.15"
        assert pin.source == "file"
        assert pin.path == path
        assert pin.warning is None
        assert pin.is_exact is True
        assert pin.major_minor == "3.13"

    def test_major_minor_pin_is_not_exact(self, tmp_path):
        _write_pin(tmp_path, "3.13")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "3.13"
        assert pin.source == "file"
        assert pin.is_exact is False

    def test_comments_and_blank_lines_are_skipped(self, tmp_path):
        _write_pin(tmp_path, "# pinned after the 3.13.12 regression\n\n3.13.15\n3.12.9\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "3.13.15"

    def test_windows_line_ending(self, tmp_path):
        _write_pin(tmp_path, "3.13.15\r\n")
        assert resolve_python_pin(str(tmp_path), "3.13").version == "3.13.15"

    def test_uv_implementation_syntax_is_accepted(self, tmp_path):
        _write_pin(tmp_path, "cpython@3.13.15\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "cpython@3.13.15"
        assert pin.source == "file"
        assert pin.warning is None

    def test_uv_full_key_is_accepted(self, tmp_path):
        _write_pin(tmp_path, "cpython-3.13.15-macos-aarch64-none\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.source == "file"
        assert pin.warning is None

    def test_empty_file_falls_back_with_warning(self, tmp_path):
        _write_pin(tmp_path, "\n#only a comment\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "3.13"
        assert pin.source == "registry"
        assert pin.warning is not None
        assert PYTHON_VERSION_FILENAME in pin.warning

    def test_leading_dash_is_rejected(self, tmp_path):
        """A value starting with '-' would reach uv's argv as a flag."""
        _write_pin(tmp_path, "--python 3.13\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.source == "registry"
        assert pin.version == "3.13"
        assert pin.warning is not None

    def test_interpreter_path_is_rejected(self, tmp_path):
        _write_pin(tmp_path, "/usr/local/bin/python3.13\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.source == "registry"
        assert pin.warning is not None

    def test_value_with_inner_whitespace_is_rejected(self, tmp_path):
        _write_pin(tmp_path, "3.13 15\n")
        assert resolve_python_pin(str(tmp_path), "3.13").source == "registry"

    def test_unreadable_file_falls_back(self, tmp_path):
        _write_pin(tmp_path, "3.13.15\n")
        with patch("odoodev.core.venv_manager.open", side_effect=OSError("boom")):
            pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.source == "registry"
        assert pin.warning is not None

    def test_pin_wins_over_registry_but_warns_on_series_mismatch(self, tmp_path):
        _write_pin(tmp_path, "3.14.7\n")
        pin = resolve_python_pin(str(tmp_path), "3.13")
        assert pin.version == "3.14.7"
        assert pin.source == "file"
        assert pin.warning is not None
        assert "3.13" in pin.warning and "3.14" in pin.warning

    def test_no_series_warning_when_matching(self, tmp_path):
        _write_pin(tmp_path, "3.13.15\n")
        assert resolve_python_pin(str(tmp_path), "3.13").warning is None

    def test_major_minor_of_uv_key(self, tmp_path):
        _write_pin(tmp_path, "cpython@3.13.15\n")
        assert resolve_python_pin(str(tmp_path), "3.13").major_minor == "3.13"


def _cfg(tmp_path, python="3.13"):
    return SimpleNamespace(
        version="19",
        python=python,
        env_name="dev19_native",
        paths=SimpleNamespace(native_dir=str(tmp_path)),
    )


class TestVenvSetupUsesPin:
    """`venv setup` hands the pinned interpreter to uv."""

    def _patch(self, monkeypatch, tmp_path, calls, python="3.13"):
        monkeypatch.setattr("odoodev.commands.venv.get_version", lambda v: _cfg(tmp_path, python))

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            os.makedirs(os.path.join(str(tmp_path), ".venv"), exist_ok=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("odoodev.commands.venv.subprocess.run", fake_run)

    def test_pin_is_passed_to_uv(self, monkeypatch, tmp_path):
        _write_pin(tmp_path, "3.13.15\n")
        calls: list[list[str]] = []
        self._patch(monkeypatch, tmp_path, calls)
        result = CliRunner().invoke(cli, ["venv", "setup", "19", "--force"])
        assert result.exit_code == 0
        assert calls and "3.13.15" in calls[0]
        assert PYTHON_VERSION_FILENAME in result.output

    def test_registry_used_without_pin(self, monkeypatch, tmp_path):
        calls: list[list[str]] = []
        self._patch(monkeypatch, tmp_path, calls)
        result = CliRunner().invoke(cli, ["venv", "setup", "19", "--force"])
        assert result.exit_code == 0
        assert "3.13" in calls[0]

    def test_explicit_option_beats_pin(self, monkeypatch, tmp_path):
        _write_pin(tmp_path, "3.13.15\n")
        calls: list[list[str]] = []
        self._patch(monkeypatch, tmp_path, calls)
        result = CliRunner().invoke(cli, ["venv", "setup", "19", "--force", "--python-version", "3.13.9"])
        assert result.exit_code == 0
        assert "3.13.9" in calls[0]
        assert "3.13.15" not in calls[0]


class TestVenvCheckWithPin:
    """`venv check` measures the venv against the pin, not against uv's pick."""

    def _patch(self, monkeypatch, tmp_path, venv_full, system_full="3.13.15"):
        monkeypatch.setattr("odoodev.commands.venv.get_version", lambda v: _cfg(tmp_path))
        venv_dir = os.path.join(str(tmp_path), ".venv", "bin")
        os.makedirs(venv_dir, exist_ok=True)
        open(os.path.join(venv_dir, "python3"), "w").close()
        monkeypatch.setattr(
            "odoodev.commands.venv.subprocess.run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=f"Python {venv_full}", stderr=""),
        )
        monkeypatch.setattr("odoodev.core.venv_manager.get_full_python_version", lambda d: venv_full)
        monkeypatch.setattr("odoodev.core.venv_manager.get_system_python_version", lambda mm: system_full)
        monkeypatch.setattr(
            "odoodev.core.venv_manager.get_venv_python_version",
            lambda d: ".".join(venv_full.split(".")[:2]),
        )

    def test_exact_pin_silences_newer_python_advisory(self, monkeypatch, tmp_path):
        _write_pin(tmp_path, "3.13.12\n")
        self._patch(monkeypatch, tmp_path, venv_full="3.13.12", system_full="3.13.15")
        result = CliRunner().invoke(cli, ["venv", "check", "19"])
        assert result.exit_code == 0
        assert "Newer Python available" not in result.output
        assert "3.13.12" in result.output

    def test_advisory_still_fires_without_pin(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path, venv_full="3.13.12", system_full="3.13.15")
        result = CliRunner().invoke(cli, ["venv", "check", "19"], input="n\n")
        assert "Newer Python available" in result.output

    def test_venv_deviating_from_pin_is_reported(self, monkeypatch, tmp_path):
        _write_pin(tmp_path, "3.13.15\n")
        self._patch(monkeypatch, tmp_path, venv_full="3.13.12", system_full="3.13.15")
        result = CliRunner().invoke(cli, ["venv", "check", "19"], input="n\n")
        assert "3.13.15" in result.output
        assert "does not match" in result.output.lower() or "pinned" in result.output.lower()

    def test_json_reports_the_pin(self, monkeypatch, tmp_path):
        _write_pin(tmp_path, "3.13.15\n")
        self._patch(monkeypatch, tmp_path, venv_full="3.13.15")
        result = CliRunner().invoke(cli, ["venv", "check", "19", "--json"])
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["python_pin"] == "3.13.15"
        assert payload["python_pin_source"] == "file"
        assert payload["python_matches"] is True

    def test_json_without_pin(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path, venv_full="3.13.12")
        result = CliRunner().invoke(cli, ["venv", "check", "19", "--json"])
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["python_pin"] == "3.13"
        assert payload["python_pin_source"] == "registry"


class TestStartPreflightWithPin:
    """start's advisory must not nag about a deliberately pinned interpreter."""

    def _invoke(self, monkeypatch, tmp_path, venv_full, system_full="3.13.15"):
        from odoodev.commands import start as start_mod

        venv_dir = os.path.join(str(tmp_path), ".venv")
        os.makedirs(venv_dir, exist_ok=True)
        monkeypatch.setattr("odoodev.core.prerequisites.check_venv_interpreter", lambda d: True)
        monkeypatch.setattr("odoodev.core.venv_manager.get_full_python_version", lambda d: venv_full)
        monkeypatch.setattr("odoodev.core.venv_manager.get_system_python_version", lambda mm: system_full)
        monkeypatch.setattr(
            "odoodev.core.venv_manager.get_venv_python_version",
            lambda d: ".".join(venv_full.split(".")[:2]),
        )
        start_mod._check_venv(None, "19", _cfg(tmp_path), venv_dir)

    def test_pinned_venv_produces_no_advisory(self, monkeypatch, tmp_path, capsys):
        _write_pin(tmp_path, "3.13.12\n")
        self._invoke(monkeypatch, tmp_path, venv_full="3.13.12")
        assert "Newer Python available" not in capsys.readouterr().out

    def test_unpinned_venv_still_gets_the_advisory(self, monkeypatch, tmp_path, capsys):
        self._invoke(monkeypatch, tmp_path, venv_full="3.13.12")
        assert "Newer Python available" in capsys.readouterr().out

    def test_deviation_from_pin_is_reported(self, monkeypatch, tmp_path, capsys):
        _write_pin(tmp_path, "3.13.15\n")
        self._invoke(monkeypatch, tmp_path, venv_full="3.13.12")
        out = capsys.readouterr().out
        assert "3.13.15" in out
