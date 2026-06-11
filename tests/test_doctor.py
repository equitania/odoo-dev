"""Tests for the odoodev doctor command."""

from __future__ import annotations

import urllib.error
from types import SimpleNamespace

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.commands.doctor import _pypi_status_row, _version_tuple


def _fake_version_cfg(tmp_path):
    return SimpleNamespace(
        ports=SimpleNamespace(db=18432),
        paths=SimpleNamespace(native_dir=str(tmp_path)),
    )


ALL_PASS = {
    "uv": True,
    "docker": True,
    "docker_compose": True,
    "wkhtmltopdf": True,
    "pg_tools": True,
    "postgres": True,
    "node": True,
    "node_packages": True,
    "system_libs": True,
    "python_packages": True,
}


def _invoke_doctor(monkeypatch, tmp_path, results, pypi=("1.0.0", None), args=("doctor", "18")):
    monkeypatch.setattr("odoodev.commands.doctor.get_version", lambda v: _fake_version_cfg(tmp_path))
    monkeypatch.setattr("odoodev.commands.doctor.run_all_checks", lambda db_port, venv_dir=None: dict(results))
    monkeypatch.setattr("odoodev.commands.doctor._check_pypi_freshness", lambda: pypi)
    return CliRunner().invoke(cli, list(args))


class TestDoctorCommand:
    def test_all_pass_exit_0(self, monkeypatch, tmp_path):
        result = _invoke_doctor(monkeypatch, tmp_path, ALL_PASS, pypi=("0.0.1", None))
        assert result.exit_code == 0
        assert "Summary" in result.output

    def test_hard_fail_exit_1(self, monkeypatch, tmp_path):
        results = {**ALL_PASS, "docker": False}
        result = _invoke_doctor(monkeypatch, tmp_path, results, pypi=("0.0.1", None))
        assert result.exit_code == 1
        assert "docker" in result.output

    def test_soft_fail_exit_0(self, monkeypatch, tmp_path):
        results = {**ALL_PASS, "wkhtmltopdf": False, "node": False}
        result = _invoke_doctor(monkeypatch, tmp_path, results, pypi=("0.0.1", None))
        assert result.exit_code == 0

    def test_pypi_update_available_shown(self, monkeypatch, tmp_path):
        result = _invoke_doctor(monkeypatch, tmp_path, ALL_PASS, pypi=("99.0.0", None))
        assert result.exit_code == 0
        assert "99.0.0" in result.output

    def test_pypi_offline_graceful(self, monkeypatch, tmp_path):
        result = _invoke_doctor(monkeypatch, tmp_path, ALL_PASS, pypi=(None, "offline"))
        assert result.exit_code == 0
        assert "skipped" in result.output

    def test_no_version_skips_postgres(self, monkeypatch, tmp_path):
        captured: dict = {}

        def fake_checks(db_port, venv_dir=None):
            captured["db_port"] = db_port
            captured["venv_dir"] = venv_dir
            return {k: v for k, v in ALL_PASS.items() if k != "python_packages"}

        monkeypatch.setattr("odoodev.commands.doctor.run_all_checks", fake_checks)
        monkeypatch.setattr("odoodev.commands.doctor._check_pypi_freshness", lambda: ("0.0.1", None))
        monkeypatch.setattr("odoodev.cli.detect_version_from_cwd", lambda: None)
        result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert captured["db_port"] == 0
        assert captured["venv_dir"] is None
        assert "skipping PostgreSQL port" in result.output

    def test_version_passes_db_port(self, monkeypatch, tmp_path):
        captured: dict = {}

        def fake_checks(db_port, venv_dir=None):
            captured["db_port"] = db_port
            return dict(ALL_PASS)

        monkeypatch.setattr("odoodev.commands.doctor.get_version", lambda v: _fake_version_cfg(tmp_path))
        monkeypatch.setattr("odoodev.commands.doctor.run_all_checks", fake_checks)
        monkeypatch.setattr("odoodev.commands.doctor._check_pypi_freshness", lambda: ("0.0.1", None))
        result = CliRunner().invoke(cli, ["doctor", "18"])
        assert result.exit_code == 0
        assert captured["db_port"] == 18432


class TestPypiHelpers:
    def test_version_tuple(self):
        assert _version_tuple("0.8.0") == (0, 8, 0)
        assert _version_tuple("1.2.3rc1") > (1, 2, 2)

    def test_status_up_to_date(self):
        status, note = _pypi_status_row("0.0.1", None)
        assert "✓" in status
        assert "Up to date" in note

    def test_status_update_available(self):
        status, note = _pypi_status_row("99.0.0", None)
        assert "~" in status
        assert "Update available: 99.0.0" in note

    def test_status_offline(self):
        status, note = _pypi_status_row(None, "timed out")
        assert "skipped" in note

    def test_check_pypi_freshness_offline(self, monkeypatch):
        from odoodev.commands import doctor as doctor_mod

        def raise_urlerror(*a, **k):
            raise urllib.error.URLError("no network")

        monkeypatch.setattr("urllib.request.urlopen", raise_urlerror)
        latest, error = doctor_mod._check_pypi_freshness()
        assert latest is None
        assert error
