"""Tests for odoodev.commands.start module."""

from __future__ import annotations

import os
import stat

# Import cli first to resolve the circular import chain (cli → start → cli)
import odoodev.cli  # noqa: F401
from odoodev.commands.start import (
    _add_v19_log_handlers,
    _clean_sessions,
    _find_odoo_config,
    _get_config_value,
    _load_env_file,
    _write_pgpass,
)


class TestFindOdooConfig:
    def test_finds_latest_config(self, tmp_dir):
        """Latest config by lexicographic sort (date suffix) is returned."""
        os.makedirs(tmp_dir, exist_ok=True)
        for name in ("odoo_240101.conf", "odoo_241231.conf", "odoo_240615.conf"):
            open(os.path.join(tmp_dir, name), "w").close()

        result = _find_odoo_config(tmp_dir)
        assert result is not None
        assert result.endswith("odoo_241231.conf")

    def test_returns_none_when_no_config(self, tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
        assert _find_odoo_config(tmp_dir) is None

    def test_returns_none_for_nonexistent_dir(self, tmp_dir):
        assert _find_odoo_config(os.path.join(tmp_dir, "nonexistent")) is None

    def test_ignores_non_matching_files(self, tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
        open(os.path.join(tmp_dir, "other.conf"), "w").close()
        assert _find_odoo_config(tmp_dir) is None

    def test_single_config(self, tmp_dir):
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, "odoo_250101.conf")
        open(path, "w").close()
        assert _find_odoo_config(tmp_dir) == path


class TestGetConfigValue:
    def test_extracts_simple_value(self, tmp_dir):
        conf = os.path.join(tmp_dir, "test.conf")
        with open(conf, "w") as f:
            f.write("db_host = localhost\n")
            f.write("db_port = 5432\n")
        assert _get_config_value(conf, "db_host") == "localhost"
        assert _get_config_value(conf, "db_port") == "5432"

    def test_returns_none_for_missing_key(self, tmp_dir):
        conf = os.path.join(tmp_dir, "test.conf")
        with open(conf, "w") as f:
            f.write("db_host = localhost\n")
        assert _get_config_value(conf, "db_name") is None

    def test_returns_none_for_false_value(self, tmp_dir):
        conf = os.path.join(tmp_dir, "test.conf")
        with open(conf, "w") as f:
            f.write("db_name = False\n")
        assert _get_config_value(conf, "db_name") is None

    def test_expands_home(self, tmp_dir):
        conf = os.path.join(tmp_dir, "test.conf")
        with open(conf, "w") as f:
            f.write("data_dir = $HOME/odoo-data\n")
        result = _get_config_value(conf, "data_dir")
        assert result is not None
        assert "$HOME" not in result
        assert os.path.expanduser("~") in result

    def test_returns_none_for_nonexistent_file(self):
        assert _get_config_value("/nonexistent/path.conf", "key") is None


class TestLoadEnvFile:
    def test_loads_key_value_pairs(self, tmp_dir):
        env_file = os.path.join(tmp_dir, ".env")
        with open(env_file, "w") as f:
            f.write("DB_PORT=18432\n")
            f.write("PGUSER=ownerp\n")
        result = _load_env_file(env_file)
        assert result == {"DB_PORT": "18432", "PGUSER": "ownerp"}

    def test_skips_comments_and_empty_lines(self, tmp_dir):
        env_file = os.path.join(tmp_dir, ".env")
        with open(env_file, "w") as f:
            f.write("# Comment\n")
            f.write("\n")
            f.write("KEY=value\n")
        result = _load_env_file(env_file)
        assert result == {"KEY": "value"}

    def test_returns_empty_for_missing_file(self, tmp_dir):
        result = _load_env_file(os.path.join(tmp_dir, "missing.env"))
        assert result == {}

    def test_expands_user_variable(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("USER", "testuser")
        env_file = os.path.join(tmp_dir, ".env")
        with open(env_file, "w") as f:
            f.write("DB_USER=${USER}\n")
        result = _load_env_file(env_file)
        assert result == {"DB_USER": "testuser"}

    def test_handles_values_with_equals(self, tmp_dir):
        env_file = os.path.join(tmp_dir, ".env")
        with open(env_file, "w") as f:
            f.write("OPTION=key=value\n")
        result = _load_env_file(env_file)
        assert result == {"OPTION": "key=value"}


class TestWritePgpass:
    def test_creates_new_pgpass(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "secret")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        assert os.path.exists(pgpass)
        with open(pgpass) as f:
            content = f.read()
        assert "localhost:18432:*:ownerp:secret" in content

    def test_file_permissions_are_0600(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "secret")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        mode = stat.S_IMODE(os.stat(pgpass).st_mode)
        assert mode == 0o600

    def test_updates_existing_entry(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        pgpass = os.path.join(tmp_dir, ".pgpass")
        with open(pgpass, "w") as f:
            f.write("localhost:18432:*:ownerp:oldpass\n")
            f.write("otherhost:5432:*:admin:pass\n")
        os.chmod(pgpass, 0o600)

        _write_pgpass("localhost", "18432", "ownerp", "newpass")
        with open(pgpass) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert "localhost:18432:*:ownerp:newpass" in lines
        assert "otherhost:5432:*:admin:pass" in lines
        assert len(lines) == 2

    def test_appends_new_entry(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        pgpass = os.path.join(tmp_dir, ".pgpass")
        with open(pgpass, "w") as f:
            f.write("otherhost:5432:*:admin:pass\n")
        os.chmod(pgpass, 0o600)

        _write_pgpass("localhost", "18432", "ownerp", "secret")
        with open(pgpass) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2
        assert "localhost:18432:*:ownerp:secret" in lines

    def test_rejects_password_with_colon(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "pass:word")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        assert not os.path.exists(pgpass)

    def test_rejects_password_with_newline(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "pass\nword")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        assert not os.path.exists(pgpass)

    def test_atomic_write_preserves_existing_on_success(self, tmp_dir, monkeypatch):
        """Verify that existing entries survive a successful write."""
        monkeypatch.setenv("HOME", tmp_dir)
        pgpass = os.path.join(tmp_dir, ".pgpass")
        with open(pgpass, "w") as f:
            f.write("host1:5432:*:user1:pass1\n")
            f.write("host2:5432:*:user2:pass2\n")
        os.chmod(pgpass, 0o600)

        _write_pgpass("host3", "5432", "user3", "pass3")
        with open(pgpass) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3
        assert "host1:5432:*:user1:pass1" in lines
        assert "host2:5432:*:user2:pass2" in lines
        assert "host3:5432:*:user3:pass3" in lines


class TestAddV19LogHandlers:
    def test_adds_handler_for_v19(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "19")
        assert any("jsonrpc:ERROR" in arg for arg in cmd)

    def test_adds_handler_for_v20(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "20")
        assert any("jsonrpc:ERROR" in arg for arg in cmd)

    def test_no_handler_for_v18(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "18")
        assert len(cmd) == 2

    def test_no_handler_for_v16(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "16")
        assert len(cmd) == 2

    def test_handles_invalid_version(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "invalid")
        assert len(cmd) == 2

    def test_handles_empty_version(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "")
        assert len(cmd) == 2


class TestCleanSessions:
    """Tests for _clean_sessions() helper."""

    def _write_config(self, tmp_dir, data_dir):
        """Create a minimal odoo.conf with a data_dir setting."""
        conf = os.path.join(tmp_dir, "odoo.conf")
        with open(conf, "w", encoding="utf-8") as f:
            f.write(f"[options]\ndata_dir = {data_dir}\n")
        return conf

    def test_no_data_dir(self, tmp_dir):
        """No data_dir in config → no action."""
        conf = os.path.join(tmp_dir, "odoo.conf")
        with open(conf, "w", encoding="utf-8") as f:
            f.write("[options]\ndb_host = localhost\n")
        _clean_sessions(conf, "18", force=True, no_confirm=False)

    def test_no_sessions_dir(self, tmp_dir):
        """data_dir exists but no sessions/ subdirectory → no action."""
        data_dir = os.path.join(tmp_dir, "odoo-share")
        os.makedirs(data_dir, exist_ok=True)
        conf = self._write_config(tmp_dir, data_dir)
        _clean_sessions(conf, "18", force=True, no_confirm=False)
        # sessions/ should not have been created
        assert not os.path.exists(os.path.join(data_dir, "sessions"))

    def test_empty_sessions(self, tmp_dir):
        """sessions/ exists but is empty → no action, no prompt."""
        data_dir = os.path.join(tmp_dir, "odoo-share")
        sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        conf = self._write_config(tmp_dir, data_dir)
        _clean_sessions(conf, "18", force=True, no_confirm=False)
        # Directory should still exist untouched
        assert os.path.isdir(sessions_dir)

    def test_force_flag_cleans_without_prompt(self, tmp_dir):
        """--clean-sessions flag removes sessions without asking."""
        data_dir = os.path.join(tmp_dir, "odoo-share")
        sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        for i in range(3):
            open(os.path.join(sessions_dir, f"sess_{i}"), "w").close()
        conf = self._write_config(tmp_dir, data_dir)

        _clean_sessions(conf, "18", force=True, no_confirm=False)

        # Directory recreated but empty
        assert os.path.isdir(sessions_dir)
        assert len(os.listdir(sessions_dir)) == 0

    def test_interactive_yes(self, tmp_dir, monkeypatch):
        """User confirms → sessions cleaned."""
        data_dir = os.path.join(tmp_dir, "odoo-share")
        sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        open(os.path.join(sessions_dir, "sess_1"), "w").close()
        conf = self._write_config(tmp_dir, data_dir)

        monkeypatch.setattr("odoodev.commands.start.confirm", lambda msg, default=True: True)
        _clean_sessions(conf, "18", force=False, no_confirm=False)

        assert os.path.isdir(sessions_dir)
        assert len(os.listdir(sessions_dir)) == 0

    def test_interactive_no(self, tmp_dir, monkeypatch):
        """User declines → sessions preserved."""
        data_dir = os.path.join(tmp_dir, "odoo-share")
        sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        open(os.path.join(sessions_dir, "sess_1"), "w").close()
        conf = self._write_config(tmp_dir, data_dir)

        monkeypatch.setattr("odoodev.commands.start.confirm", lambda msg, default=True: False)
        _clean_sessions(conf, "18", force=False, no_confirm=False)

        assert len(os.listdir(sessions_dir)) == 1

    def test_no_confirm_skips_prompt(self, tmp_dir):
        """--no-confirm without --clean-sessions → no cleanup, no prompt."""
        data_dir = os.path.join(tmp_dir, "odoo-share")
        sessions_dir = os.path.join(data_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        open(os.path.join(sessions_dir, "sess_1"), "w").close()
        conf = self._write_config(tmp_dir, data_dir)

        _clean_sessions(conf, "18", force=False, no_confirm=True)

        # Session file should still exist
        assert len(os.listdir(sessions_dir)) == 1

    def test_cli_flag_exists(self):
        """--clean-sessions flag is visible in start command."""
        from click.testing import CliRunner

        from odoodev.commands.start import start

        runner = CliRunner()
        result = runner.invoke(start, ["--help"], catch_exceptions=False)
        assert "--clean-sessions" in result.output
