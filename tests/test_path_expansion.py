"""Tests for ``~`` (home directory) expansion in path inputs."""

import os

from odoodev.click_types import ExpandedPath
from odoodev.output import path_input


class _FakePrompt:
    """Minimal stand-in for a questionary prompt object."""

    def __init__(self, value: str) -> None:
        self._value = value

    def ask(self) -> str:
        return self._value


class TestPathInputExpansion:
    def test_path_input_expands_tilde(self, monkeypatch):
        monkeypatch.setattr("odoodev.output.questionary.path", lambda *a, **k: _FakePrompt("~/backup.7z"))
        result = path_input("Backup file:")
        assert result == os.path.join(os.path.expanduser("~"), "backup.7z")
        assert "~" not in result

    def test_path_input_passes_absolute_path_through(self, monkeypatch):
        monkeypatch.setattr("odoodev.output.questionary.path", lambda *a, **k: _FakePrompt("/tmp/x.7z"))
        assert path_input("Backup file:") == "/tmp/x.7z"

    def test_path_input_strips_surrounding_whitespace(self, monkeypatch):
        """Pasted paths / autocomplete results may carry a trailing space or
        newline — it must be stripped so os.path.exists does not spuriously fail."""
        monkeypatch.setattr(
            "odoodev.output.questionary.path",
            lambda *a, **k: _FakePrompt("  /tmp/backup.tar.zst \n"),
        )
        assert path_input("Backup file:") == "/tmp/backup.tar.zst"

    def test_path_input_strips_then_expands_tilde(self, monkeypatch):
        monkeypatch.setattr(
            "odoodev.output.questionary.path",
            lambda *a, **k: _FakePrompt(" ~/backup.tar.zst "),
        )
        result = path_input("Backup file:")
        assert result == os.path.join(os.path.expanduser("~"), "backup.tar.zst")
        assert not result.endswith(" ")


class TestExpandedPath:
    def test_convert_expands_tilde(self):
        result = ExpandedPath().convert("~/backup.7z", None, None)
        assert result == os.path.join(os.path.expanduser("~"), "backup.7z")
        assert "~" not in result

    def test_convert_leaves_plain_path_unchanged(self):
        assert ExpandedPath().convert("/tmp/x.7z", None, None) == "/tmp/x.7z"
