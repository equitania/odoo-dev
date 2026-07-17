"""Tests for the `odoodev export modules` CLI command (GUI-reusable export)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.commands import export as export_cmd


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Isolate version resolution, ports and stored credentials."""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        version="18",
        ports=SimpleNamespace(db=18432, odoo=18069, gevent=18072, mailpit=18025),
        paths=SimpleNamespace(native_dir=str(tmp_path)),
    )
    monkeypatch.setattr("odoodev.core.version_registry.get_version", lambda v, versions=None: cfg)
    monkeypatch.setattr("odoodev.core.global_config.get_odoo_login_credentials", lambda: ("stored_user", "stored_pw"))
    monkeypatch.delenv(export_cmd.ENV_USER, raising=False)
    monkeypatch.delenv(export_cmd.ENV_PASSWORD, raising=False)


@pytest.fixture()
def mock_client(monkeypatch):
    """Replace OdooXmlRpcClient with a recording mock."""
    instance = MagicMock()
    instance.list_modules.return_value = [
        {"id": 1, "name": "base", "installed_version": "18.0", "display_name": "Base"},
        {"id": 2, "name": "sale", "installed_version": "18.0", "display_name": "Sales"},
    ]
    instance.update_module_list.return_value = 3
    instance.cleanup_uninstalled_modules.return_value = 5
    cls = MagicMock(return_value=instance)
    monkeypatch.setattr("odoodev.core.xmlrpc_client.OdooXmlRpcClient", cls)
    return cls, instance


class TestExportModulesCli:
    def test_help_lists_flags(self):
        result = CliRunner().invoke(cli, ["export", "modules", "--help"])
        assert result.exit_code == 0
        for flag in ("--database", "--user", "--password", "--scope", "--json", "--output", "--update-list"):
            assert flag in result.output

    def test_database_required_non_interactive(self, mock_client):
        result = CliRunner().invoke(cli, ["export", "modules", "18", "--yes"])
        assert result.exit_code != 0
        assert "--database is required" in result.output

    def test_json_output_contract(self, mock_client, tmp_path):
        out_file = tmp_path / "modules.csv"
        result = CliRunner().invoke(
            cli,
            ["export", "modules", "18", "-d", "v18_exam", "--json", "--output", str(out_file)],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output.strip())
        assert data == {
            "version": "18",
            "database": "v18_exam",
            "scope": "all",
            "path": str(out_file),
            "count": 2,
            "updated": None,
            "cleaned": None,
        }
        content = out_file.read_text(encoding="utf-8")
        assert content.splitlines()[0] == ".id,name,installed_version,display_name"
        assert "sale" in content

    def test_scope_mapping(self, mock_client, tmp_path):
        _cls, instance = mock_client
        result = CliRunner().invoke(
            cli,
            [
                "export",
                "modules",
                "18",
                "-d",
                "v18_exam",
                "--scope",
                "installed",
                "--json",
                "--output",
                str(tmp_path / "x.csv"),
            ],
        )
        assert result.exit_code == 0, result.output
        instance.list_modules.assert_called_once_with(installed_only=True, exclude_enterprise=False)

    def test_scope_no_enterprise(self, mock_client, tmp_path):
        _cls, instance = mock_client
        result = CliRunner().invoke(
            cli,
            [
                "export",
                "modules",
                "18",
                "-d",
                "v18_exam",
                "--scope",
                "no-enterprise",
                "--json",
                "--output",
                str(tmp_path / "x.csv"),
            ],
        )
        assert result.exit_code == 0, result.output
        instance.list_modules.assert_called_once_with(installed_only=False, exclude_enterprise=True)

    def test_cleanup_before_update(self, mock_client, tmp_path):
        _cls, instance = mock_client
        manager = MagicMock()
        manager.attach_mock(instance.cleanup_uninstalled_modules, "cleanup")
        manager.attach_mock(instance.update_module_list, "update")
        result = CliRunner().invoke(
            cli,
            [
                "export",
                "modules",
                "18",
                "-d",
                "v18_exam",
                "--cleanup",
                "--update-list",
                "--json",
                "--output",
                str(tmp_path / "x.csv"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert [c[0] for c in manager.mock_calls] == ["cleanup", "update"]
        data = json.loads(result.output.strip())
        assert data["cleaned"] == 5
        assert data["updated"] == 3

    def test_empty_result_soft_outcome(self, mock_client):
        _cls, instance = mock_client
        instance.list_modules.return_value = []
        result = CliRunner().invoke(cli, ["export", "modules", "18", "-d", "v18_exam", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output.strip())
        assert data["count"] == 0
        assert data["path"] is None

    def test_connection_error_exits_1(self, mock_client):
        _cls, instance = mock_client
        instance.list_modules.side_effect = ConnectionError("no Odoo on port 18069")
        result = CliRunner().invoke(cli, ["export", "modules", "18", "-d", "v18_exam", "--yes"])
        assert result.exit_code == 1
        assert "odoodev start" in result.output


class TestCredentialPrecedence:
    def _invoke(self, mock_client, tmp_path, extra_args=()):
        return CliRunner().invoke(
            cli,
            ["export", "modules", "18", "-d", "db", "--json", "--output", str(tmp_path / "x.csv"), *extra_args],
        )

    def test_cli_flags_win(self, mock_client, tmp_path, monkeypatch):
        cls, _instance = mock_client
        monkeypatch.setenv(export_cmd.ENV_USER, "env_user")
        monkeypatch.setenv(export_cmd.ENV_PASSWORD, "env_pw")
        result = self._invoke(mock_client, tmp_path, ["--user", "cli_user", "--password", "cli_pw"])
        assert result.exit_code == 0, result.output
        kwargs = cls.call_args.kwargs
        assert kwargs["username"] == "cli_user"
        assert kwargs["password"] == "cli_pw"

    def test_env_vars_beat_stored(self, mock_client, tmp_path, monkeypatch):
        cls, _instance = mock_client
        monkeypatch.setenv(export_cmd.ENV_USER, "env_user")
        monkeypatch.setenv(export_cmd.ENV_PASSWORD, "env_pw")
        result = self._invoke(mock_client, tmp_path)
        assert result.exit_code == 0, result.output
        kwargs = cls.call_args.kwargs
        assert kwargs["username"] == "env_user"
        assert kwargs["password"] == "env_pw"

    def test_stored_config_fallback(self, mock_client, tmp_path):
        cls, _instance = mock_client
        result = self._invoke(mock_client, tmp_path)
        assert result.exit_code == 0, result.output
        kwargs = cls.call_args.kwargs
        assert kwargs["username"] == "stored_user"
        assert kwargs["password"] == "stored_pw"

    def test_partial_cli_flag_mixes_with_stored(self, mock_client, tmp_path):
        cls, _instance = mock_client
        result = self._invoke(mock_client, tmp_path, ["--user", "only_user"])
        assert result.exit_code == 0, result.output
        kwargs = cls.call_args.kwargs
        assert kwargs["username"] == "only_user"
        assert kwargs["password"] == "stored_pw"


class TestPortResolution:
    def test_effective_odoo_port_from_env_file(self, mock_client, tmp_path):
        """A .env ODOO_PORT override must win over the registry default."""
        (tmp_path / ".env").write_text("ODOO_PORT=28069\n")
        cls, _instance = mock_client
        result = CliRunner().invoke(
            cli,
            ["export", "modules", "18", "-d", "db", "--json", "--output", str(tmp_path / "x.csv")],
        )
        assert result.exit_code == 0, result.output
        assert cls.call_args.kwargs["port"] == 28069

    def test_port_flag_wins(self, mock_client, tmp_path):
        cls, _instance = mock_client
        result = CliRunner().invoke(
            cli,
            [
                "export",
                "modules",
                "18",
                "-d",
                "db",
                "--port",
                "9999",
                "--json",
                "--output",
                str(tmp_path / "x.csv"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert cls.call_args.kwargs["port"] == 9999
