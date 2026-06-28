"""Tests for odoodev config set / config edit."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core import global_config


def _isolate_config(monkeypatch, tmp_path) -> Path:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr("odoodev.core.global_config.get_config_path", lambda: config_path)
    monkeypatch.setattr("odoodev.core.global_config.get_config_dir", lambda: tmp_path)
    global_config.clear_config_cache()
    return config_path


class TestConfigSet:
    def test_set_base_dir(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "base_dir", "~/mybase"])
        assert result.exit_code == 0
        global_config.clear_config_cache()
        assert global_config.load_global_config().base_dir == "~/mybase"

    def test_set_language_valid(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "language", "de"])
        assert result.exit_code == 0
        global_config.clear_config_cache()
        assert global_config.load_global_config().cli.language == "de"

    def test_set_language_invalid(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "language", "fr"])
        assert result.exit_code != 0
        assert "Unsupported language" in result.output

    def test_set_db_user_and_password(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        assert CliRunner().invoke(cli, ["config", "set", "db.user", "devuser"]).exit_code == 0
        result = CliRunner().invoke(cli, ["config", "set", "db.password", "s3cret"])
        assert result.exit_code == 0
        assert "s3cret" not in result.output  # never echo the password
        global_config.clear_config_cache()
        cfg = global_config.load_global_config()
        assert cfg.database.user == "devuser"
        assert cfg.database.password == "s3cret"

    def test_set_active_versions(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "active_versions", "17,18"])
        assert result.exit_code == 0
        global_config.clear_config_cache()
        assert global_config.load_global_config().active_versions == ["17", "18"]

    def test_set_active_versions_unknown(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "active_versions", "18,99"])
        assert result.exit_code != 0
        assert "99" in result.output

    def test_set_container_runtime_valid(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "container_runtime", "apple"])
        assert result.exit_code == 0
        global_config.clear_config_cache()
        assert global_config.load_global_config().container_runtime == "apple"

    def test_set_container_runtime_invalid(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "container_runtime", "podman"])
        assert result.exit_code != 0
        assert "Invalid container_runtime" in result.output

    def test_set_unknown_key(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "bogus", "x"])
        assert result.exit_code != 0
        assert "Unknown key" in result.output

    def test_set_password_with_newline_rejected(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        result = CliRunner().invoke(cli, ["config", "set", "db.password", "a\nb"])
        assert result.exit_code != 0

    def test_other_values_preserved(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        CliRunner().invoke(cli, ["config", "set", "db.user", "keepme"])
        CliRunner().invoke(cli, ["config", "set", "language", "de"])
        global_config.clear_config_cache()
        cfg = global_config.load_global_config()
        assert cfg.database.user == "keepme"
        assert cfg.cli.language == "de"


class TestConfigEdit:
    def test_edit_creates_default_and_opens_editor(self, monkeypatch, tmp_path):
        config_path = _isolate_config(monkeypatch, tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.setenv("EDITOR", "myeditor")
        monkeypatch.setattr("odoodev.commands.config.subprocess.run", fake_run)
        result = CliRunner().invoke(cli, ["config", "edit"])
        assert result.exit_code == 0
        assert config_path.exists()
        assert calls == [["myeditor", str(config_path)]]

    def test_edit_falls_back_to_vi(self, monkeypatch, tmp_path):
        config_path = _isolate_config(monkeypatch, tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setattr("odoodev.commands.config.subprocess.run", fake_run)
        result = CliRunner().invoke(cli, ["config", "edit"])
        assert result.exit_code == 0
        assert calls[0][0] == "vi"
        assert calls[0][1] == str(config_path)
