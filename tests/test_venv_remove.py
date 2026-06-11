"""Tests for odoodev venv remove."""

from __future__ import annotations

import os
from types import SimpleNamespace

from click.testing import CliRunner

from odoodev.cli import cli


def _setup(monkeypatch, tmp_path, create_venv=True):
    version_cfg = SimpleNamespace(paths=SimpleNamespace(native_dir=str(tmp_path)))
    monkeypatch.setattr("odoodev.commands.venv.get_version", lambda v: version_cfg)
    venv_dir = os.path.join(str(tmp_path), ".venv")
    if create_venv:
        os.makedirs(venv_dir)
        with open(os.path.join(venv_dir, "pyvenv.cfg"), "w") as f:
            f.write("home = /usr\n")
    return venv_dir


class TestVenvRemove:
    def test_remove_with_yes(self, monkeypatch, tmp_path):
        venv_dir = _setup(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["venv", "remove", "18", "--yes"])
        assert result.exit_code == 0
        assert not os.path.exists(venv_dir)
        assert "Venv removed" in result.output

    def test_remove_short_flag(self, monkeypatch, tmp_path):
        venv_dir = _setup(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["venv", "remove", "18", "-y"])
        assert result.exit_code == 0
        assert not os.path.exists(venv_dir)

    def test_remove_nonexistent_is_idempotent(self, monkeypatch, tmp_path):
        _setup(monkeypatch, tmp_path, create_venv=False)
        result = CliRunner().invoke(cli, ["venv", "remove", "18", "--yes"])
        assert result.exit_code == 0
        assert "No venv found" in result.output

    def test_remove_requires_confirmation(self, monkeypatch, tmp_path):
        venv_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr("odoodev.commands.venv.confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["venv", "remove", "18"])
        assert result.exit_code == 0
        assert os.path.exists(venv_dir)
        assert "Aborted" in result.output

    def test_remove_confirmed_interactively(self, monkeypatch, tmp_path):
        venv_dir = _setup(monkeypatch, tmp_path)
        monkeypatch.setattr("odoodev.commands.venv.confirm", lambda *a, **k: True)
        result = CliRunner().invoke(cli, ["venv", "remove", "18"])
        assert result.exit_code == 0
        assert not os.path.exists(venv_dir)

    def test_remove_symlink(self, monkeypatch, tmp_path):
        version_cfg = SimpleNamespace(paths=SimpleNamespace(native_dir=str(tmp_path)))
        monkeypatch.setattr("odoodev.commands.venv.get_version", lambda v: version_cfg)
        real = tmp_path / "real-venv"
        real.mkdir()
        venv_dir = tmp_path / ".venv"
        venv_dir.symlink_to(real)
        result = CliRunner().invoke(cli, ["venv", "remove", "18", "--yes"])
        assert result.exit_code == 0
        assert not venv_dir.exists()
        assert real.exists()  # symlink target untouched

    def test_remove_oserror_exit_1(self, monkeypatch, tmp_path):
        _setup(monkeypatch, tmp_path)

        def raise_oserror(path):
            raise OSError("permission denied")

        monkeypatch.setattr("shutil.rmtree", raise_oserror)
        result = CliRunner().invoke(cli, ["venv", "remove", "18", "--yes"])
        assert result.exit_code == 1
        assert "Failed to remove" in result.output
