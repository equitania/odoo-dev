"""Tests for --json output on db list, config versions, venv check."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from click.testing import CliRunner

from odoodev.cli import cli


def _fake_version_cfg(tmp_path):
    return SimpleNamespace(
        version="18",
        paths=SimpleNamespace(native_dir=str(tmp_path)),
        ports=SimpleNamespace(db=18432),
        python="3.13",
    )


class TestDbListJson:
    def test_emits_single_json_object(self, monkeypatch, tmp_path):
        import odoodev.commands.db as db_cmd

        monkeypatch.setattr(db_cmd, "get_version", lambda v: _fake_version_cfg(tmp_path))
        monkeypatch.setattr(db_cmd, "list_databases", lambda **k: ["v18_demo", "v18_exam"])
        result = CliRunner().invoke(cli, ["db", "list", "18", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data["databases"] == ["v18_demo", "v18_exam"]
        assert data["version"] == "18"
        assert data["port"] == 18432


class TestConfigVersionsJson:
    def test_emits_versions_object(self):
        result = CliRunner().invoke(cli, ["config", "versions", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert "18" in data
        assert data["18"]["ports"]["db"] == 18432
        assert data["18"]["python"]

    def test_plain_and_json_mutually_exclusive(self):
        result = CliRunner().invoke(cli, ["config", "versions", "--plain", "--json"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_payload_contains_effective_ports(self):
        result = CliRunner().invoke(cli, ["config", "versions", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert set(data["18"]["effective_ports"]) == {"db", "odoo", "gevent", "mailpit"}


class TestEffectivePorts:
    """Multi-user hosts override registry ports per user via the version's .env."""

    def _cfg(self, native_dir):
        return SimpleNamespace(
            paths=SimpleNamespace(native_dir=str(native_dir)),
            ports=SimpleNamespace(db=18432, odoo=18069, gevent=18072, mailpit=18025),
        )

    def test_env_overrides_registry_defaults(self, tmp_path):
        from odoodev.commands.config import _effective_ports

        (tmp_path / ".env").write_text("DB_PORT=28432\nODOO_PORT=28069\n# comment\nGEVENT_PORT=\n")
        assert _effective_ports(self._cfg(tmp_path)) == {
            "db": 28432,
            "odoo": 28069,
            "gevent": 18072,
            "mailpit": 18025,
        }

    def test_missing_env_falls_back_to_defaults(self, tmp_path):
        from odoodev.commands.config import _effective_ports

        assert _effective_ports(self._cfg(tmp_path)) == {
            "db": 18432,
            "odoo": 18069,
            "gevent": 18072,
            "mailpit": 18025,
        }

    def test_non_numeric_value_is_ignored(self, tmp_path):
        from odoodev.commands.config import _effective_ports

        (tmp_path / ".env").write_text("ODOO_PORT=not-a-port\n")
        assert _effective_ports(self._cfg(tmp_path))["odoo"] == 18069


class TestVenvCheckJson:
    def test_missing_venv_exits_1_with_json(self, monkeypatch, tmp_path):
        import odoodev.commands.venv as venv_cmd

        monkeypatch.setattr(venv_cmd, "get_version", lambda v: _fake_version_cfg(tmp_path))
        result = CliRunner().invoke(cli, ["venv", "check", "18", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output.strip())
        assert data["exists"] is False
        assert data["python_version"] is None

    def test_existing_venv_reports_status(self, monkeypatch, tmp_path):
        import odoodev.commands.venv as venv_cmd

        monkeypatch.setattr(venv_cmd, "get_version", lambda v: _fake_version_cfg(tmp_path))
        venv_dir = tmp_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)
        monkeypatch.setattr("odoodev.core.venv_manager.get_full_python_version", lambda d: "3.13.2")
        result = CliRunner().invoke(cli, ["venv", "check", "18", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data["exists"] is True
        assert data["python_version"] == "3.13.2"
        assert data["venv_dir"] == str(venv_dir)
        # no python3 binary → match status unknown
        assert data["python_matches"] is None

    def test_requirements_freshness_flag(self, monkeypatch, tmp_path):
        import odoodev.commands.venv as venv_cmd

        cfg = _fake_version_cfg(tmp_path)
        monkeypatch.setattr(venv_cmd, "get_version", lambda v: cfg)
        venv_dir = tmp_path / ".venv"
        (venv_dir / "bin").mkdir(parents=True)
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("click\n")
        monkeypatch.setattr(venv_cmd, "_get_requirements_path", lambda c: str(requirements))
        from odoodev.core.venv_manager import hash_requirements

        (venv_dir / ".requirements.sha256").write_text(hash_requirements(str(requirements)))
        monkeypatch.setattr("odoodev.core.venv_manager.get_full_python_version", lambda d: "3.13.2")
        result = CliRunner().invoke(cli, ["venv", "check", "18", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data["requirements_current"] is True
        assert os.path.basename(data["venv_dir"]) == ".venv"
