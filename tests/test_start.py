"""Tests for odoodev.commands.start module."""

from __future__ import annotations

import os
import stat
import subprocess
import types

import pytest

# Import cli first to resolve the circular import chain (cli → start → cli)
import odoodev.cli  # noqa: F401
from odoodev.commands.start import (
    _add_v19_log_handlers,
    _check_odoo_config,
    _check_services,
    _clean_sessions,
    _extract_db_from_args,
    _find_odoo_config,
    _get_config_value,
    _load_env_file,
    _resolve_tui_db_name,
    _select_runtime,
    _start_odoo,
    _write_pgpass,
)


class TestSelectRuntime:
    """Test runtime selection for starting PostgreSQL in `odoodev start`.

    The configured default is stubbed to ``docker`` so the persist-prompt logic
    (which fires only when the chosen runtime differs from the default) is
    deterministic and never touches the user's real ~/.config/odoodev.
    """

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        # configured default = "docker"; an explicit override is echoed back
        monkeypatch.setattr(
            "odoodev.core.container_backend.resolve_runtime",
            lambda override=None: override or "docker",
        )
        # pin the platform gate to "macOS" so the classic two-runtime picker
        # behavior stays deterministic regardless of the host running the suite
        monkeypatch.setattr("odoodev.core.container_backend.apple_runtime_supported", lambda: True)
        # record persistence without writing to disk
        from odoodev.core.global_config import GlobalConfig

        self.saved: list[str] = []
        monkeypatch.setattr("odoodev.core.global_config.load_global_config", lambda: GlobalConfig())
        monkeypatch.setattr(
            "odoodev.core.global_config.save_global_config",
            lambda cfg: self.saved.append(cfg.container_runtime),
        )
        # default: confirm says "yes" — individual tests override as needed
        monkeypatch.setattr("odoodev.commands.start.confirm", lambda *a, **k: True)

    def test_override_noconfirm_no_persist(self):
        # --runtime + non-interactive: honoured, no prompt, nothing saved.
        assert _select_runtime("apple", no_confirm=True) == "apple"
        assert self.saved == []

    def test_override_same_as_default_no_prompt(self, monkeypatch):
        # Override equals the stored default → no persist prompt at all.
        monkeypatch.setattr(
            "odoodev.commands.start.confirm",
            lambda *a, **k: pytest.fail("confirm must not be called when runtime == default"),
        )
        assert _select_runtime("docker", no_confirm=False) == "docker"
        assert self.saved == []

    def test_override_differs_persists_on_yes(self):
        assert _select_runtime("apple", no_confirm=False) == "apple"
        assert self.saved == ["apple"]

    def test_override_differs_declined(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.start.confirm", lambda *a, **k: False)
        assert _select_runtime("apple", no_confirm=False) == "apple"
        assert self.saved == []

    def test_non_interactive_uses_configured(self):
        assert _select_runtime(None, no_confirm=True) == "docker"
        assert self.saved == []

    def test_interactive_skip_returns_none(self, monkeypatch):
        monkeypatch.setattr("odoodev.output.select", lambda *a, **k: "skip")
        assert _select_runtime(None, no_confirm=False) is None
        assert self.saved == []

    def test_interactive_choice_persists_on_yes(self, monkeypatch):
        monkeypatch.setattr("odoodev.output.select", lambda *a, **k: "apple")
        assert _select_runtime(None, no_confirm=False) == "apple"
        assert self.saved == ["apple"]

    def test_interactive_choice_equals_default_no_prompt(self, monkeypatch):
        monkeypatch.setattr("odoodev.output.select", lambda *a, **k: "docker")
        monkeypatch.setattr(
            "odoodev.commands.start.confirm",
            lambda *a, **k: pytest.fail("confirm must not be called when runtime == default"),
        )
        assert _select_runtime(None, no_confirm=False) == "docker"
        assert self.saved == []


class TestSelectRuntimeNonMacos:
    """Runtime selection when Apple Container is not supported (non-macOS host)."""

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.container_backend.resolve_runtime",
            lambda override=None: override or "docker",
        )
        monkeypatch.setattr("odoodev.core.container_backend.apple_runtime_supported", lambda: False)
        from odoodev.core.global_config import GlobalConfig

        self.saved: list[str] = []
        monkeypatch.setattr("odoodev.core.global_config.load_global_config", lambda: GlobalConfig())
        monkeypatch.setattr(
            "odoodev.core.global_config.save_global_config",
            lambda cfg: self.saved.append(cfg.container_runtime),
        )
        # the interactive path must never reach the multi-runtime picker
        monkeypatch.setattr(
            "odoodev.output.select",
            lambda *a, **k: pytest.fail("select must not be called when Apple Container is unsupported"),
        )

    def test_interactive_confirm_accept_returns_docker(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.start.confirm", lambda *a, **k: True)
        assert _select_runtime(None, no_confirm=False) == "docker"
        assert self.saved == []  # docker == configured default → no persist prompt

    def test_interactive_confirm_decline_returns_none(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.start.confirm", lambda *a, **k: False)
        assert _select_runtime(None, no_confirm=False) is None
        assert self.saved == []

    def test_explicit_apple_override_errors(self):
        with pytest.raises(SystemExit) as exc:
            _select_runtime("apple", no_confirm=True)
        assert exc.value.code == 1

    def test_configured_apple_falls_back_to_docker(self, monkeypatch):
        monkeypatch.setattr(
            "odoodev.core.container_backend.resolve_runtime",
            lambda override=None: override or "apple",
        )
        assert _select_runtime(None, no_confirm=True) == "docker"

    def test_docker_override_still_works(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.start.confirm", lambda *a, **k: False)
        assert _select_runtime("docker", no_confirm=False) == "docker"


class TestExtractDbFromArgs:
    """Test recovering the database from raw Odoo extra args."""

    def test_space_separated_short(self):
        assert _extract_db_from_args(("-d", "v19_test")) == "v19_test"

    def test_space_separated_long(self):
        assert _extract_db_from_args(("--database", "v19_test")) == "v19_test"

    def test_equals_short(self):
        assert _extract_db_from_args(("-d=v19_test",)) == "v19_test"

    def test_equals_long(self):
        assert _extract_db_from_args(("--database=v19_test",)) == "v19_test"

    def test_among_other_args(self):
        assert _extract_db_from_args(("-u", "all", "-d", "realdb", "--dev=all")) == "realdb"

    def test_absent(self):
        assert _extract_db_from_args(("-u", "all")) is None

    def test_empty(self):
        assert _extract_db_from_args(()) is None

    def test_trailing_flag_without_value(self):
        assert _extract_db_from_args(("-u", "all", "-d")) is None


class TestResolveTuiDbName:
    """Test the TUI database-name priority chain (the bug fix)."""

    def test_explicit_database_wins(self, tmp_path):
        conf = tmp_path / "odoo.conf"
        conf.write_text("db_name = conf_db\n", encoding="utf-8")
        assert _resolve_tui_db_name("realdb", ("-d", "argdb"), str(conf), "19") == "realdb"

    def test_extra_args_over_conf_and_fallback(self, tmp_path):
        conf = tmp_path / "odoo.conf"
        conf.write_text("db_name = conf_db\n", encoding="utf-8")
        assert _resolve_tui_db_name(None, ("-d", "argdb"), str(conf), "19") == "argdb"

    def test_conf_over_fallback(self, tmp_path):
        conf = tmp_path / "odoo.conf"
        conf.write_text("db_name = conf_db\n", encoding="utf-8")
        assert _resolve_tui_db_name(None, (), str(conf), "19") == "conf_db"

    def test_fallback_when_nothing_known(self, tmp_path):
        missing = tmp_path / "nope.conf"
        assert _resolve_tui_db_name(None, (), str(missing), "19") == "v19_exam"

    def test_double_dash_form(self, tmp_path):
        """odoodev start 19 --tui -- -d v19_test must reach the TUI db name."""
        missing = tmp_path / "nope.conf"
        assert _resolve_tui_db_name(None, ("-d", "v19_test"), str(missing), "19") == "v19_test"


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


class TestCheckOdooConfigOverride:
    """_check_odoo_config(config_override=...) bypasses the glob selection."""

    def test_override_returns_path_directly(self, tmp_dir):
        """An explicit override path is returned as-is, bypassing glob."""
        custom = os.path.join(tmp_dir, "my_custom.conf")
        open(custom, "w").close()
        # Even though myconfs_dir has a newer odoo_*.conf, the override wins.
        myconfs = os.path.join(tmp_dir, "myconfs")
        os.makedirs(myconfs, exist_ok=True)
        open(os.path.join(myconfs, "odoo_990101.conf"), "w").close()
        result = _check_odoo_config(None, "18", myconfs, config_override=custom)
        assert result == custom

    def test_override_missing_errors(self, tmp_dir):
        """A non-existent override path exits with an error (no generate-prompt)."""
        with pytest.raises(SystemExit) as exc:
            _check_odoo_config(None, "18", tmp_dir, config_override="/nonexistent/odoo.conf")
        assert exc.value.code == 1

    def test_override_none_falls_back_to_glob(self, tmp_dir):
        """config_override=None keeps the legacy glob-based discovery."""
        myconfs = os.path.join(tmp_dir, "myconfs")
        os.makedirs(myconfs, exist_ok=True)
        path = os.path.join(myconfs, "odoo_250101.conf")
        open(path, "w").close()
        # ctx=None, no generate-prompt needed because a config exists.
        result = _check_odoo_config(None, "18", myconfs, config_override=None)
        assert result == path


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

    def test_escapes_colon_in_password(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "pass:word")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        with open(pgpass) as f:
            content = f.read()
        assert "localhost:18432:*:ownerp:pass\\:word" in content

    def test_escapes_backslash_in_password(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "pass\\word")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        with open(pgpass) as f:
            content = f.read()
        assert "localhost:18432:*:ownerp:pass\\\\word" in content

    def test_escapes_backslash_before_colon(self, tmp_dir, monkeypatch):
        from odoodev.commands.start import _pgpass_escape

        # backslash must be escaped FIRST, otherwise \: would double-escape
        assert _pgpass_escape("p\\a:s") == "p\\\\a\\:s"

    def test_updates_existing_escaped_entry(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("HOME", tmp_dir)
        _write_pgpass("localhost", "18432", "ownerp", "first:pass")
        _write_pgpass("localhost", "18432", "ownerp", "second:pass")
        pgpass = os.path.join(tmp_dir, ".pgpass")
        with open(pgpass) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 1
        assert lines[0] == "localhost:18432:*:ownerp:second\\:pass"

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

    def test_config_flag_in_help(self):
        """-c/--config flag is visible in start command help."""
        from click.testing import CliRunner

        from odoodev.commands.start import start

        runner = CliRunner()
        result = runner.invoke(start, ["--help"], catch_exceptions=False)
        assert "-c, --config" in result.output
        assert "bypasses the" in result.output  # help wraps across lines

    def test_start_with_c_flag_uses_override(self, monkeypatch, tmp_path):
        """`odoodev start 18 -c <path>` uses the explicit config, not the glob result."""
        from click.testing import CliRunner

        import odoodev.commands.start as start_cmd
        from odoodev.commands.start import start

        custom_conf = tmp_path / "custom.conf"
        custom_conf.write_text("[options]\n")
        glob_conf = tmp_path / "myconfs" / "odoo_990101.conf"
        glob_conf.parent.mkdir(parents=True)
        glob_conf.write_text("[options]\n")

        captured: dict[str, str] = {}

        def fake_check(ctx, version, myconfs_dir, config_override=None):
            captured["override"] = config_override
            return str(custom_conf)

        monkeypatch.setattr(start_cmd, "_check_odoo_config", fake_check)
        monkeypatch.setattr(start_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(start_cmd, "load_versions", lambda: {})
        monkeypatch.setattr(
            start_cmd,
            "get_version",
            lambda v, versions=None: types.SimpleNamespace(
                version="18",
                python="3.12",
                postgres="16",
                ports=types.SimpleNamespace(db=18432, odoo=8069, gevent=8072, mailpit=1025, smtp=1025),
                paths=types.SimpleNamespace(
                    native_dir=str(tmp_path),
                    server_dir=str(tmp_path),
                    myconfs_dir=str(glob_conf.parent),
                ),
            ),
        )
        monkeypatch.setattr(start_cmd, "_check_env_file", lambda ctx, v, d: {})
        monkeypatch.setattr(start_cmd, "_check_placeholder_password", lambda *a, **k: None)
        monkeypatch.setattr(start_cmd, "_set_environment", lambda env_vars, bind_host="", version="": {})
        monkeypatch.setattr(start_cmd, "_check_venv", lambda *a, **k: None)
        monkeypatch.setattr(start_cmd, "_check_odoo_source", lambda *a, **k: None)
        monkeypatch.setattr(start_cmd, "_clean_sessions", lambda *a, **k: None)
        monkeypatch.setattr(start_cmd, "_check_services", lambda *a, **k: None)
        monkeypatch.setattr(start_cmd, "_start_odoo", lambda *a, **k: None)

        runner = CliRunner()
        result = runner.invoke(start, ["18", "-c", str(custom_conf), "-y"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert captured["override"] == str(custom_conf)


class TestStartOdooProcessGroup:
    """Ctrl+C handling: server modes get their own session + group shutdown,
    while the interactive shell stays in the foreground process group."""

    def _patch_common(self, monkeypatch):
        monkeypatch.setattr("odoodev.commands.start.get_venv_python", lambda venv_dir: "python")
        # neutralise the v19 log-handler mutation (needs no real version data)
        monkeypatch.setattr("odoodev.commands.start._add_v19_log_handlers", lambda cmd, version: None)

    def test_shell_mode_uses_subprocess_run(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch)
        calls = {"run": 0, "popen": 0}

        class _Result:
            returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.__setitem__("run", calls["run"] + 1) or _Result())
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.__setitem__("popen", calls["popen"] + 1) or None)

        with pytest.raises(SystemExit) as exc:
            _start_odoo(str(tmp_path), "/tmp/odoo.conf", "shell", (), {}, str(tmp_path), version="18")
        assert exc.value.code == 0
        assert calls["run"] == 1
        assert calls["popen"] == 0

    def test_server_mode_uses_popen_new_session(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch)
        captured = {}

        class _FakeProc:
            pid = 4321
            returncode = 0

            def wait(self):
                return 0

        def _fake_popen(cmd, **kwargs):
            captured.update(kwargs)
            return _FakeProc()

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("server mode must not use subprocess.run"))

        with pytest.raises(SystemExit) as exc:
            _start_odoo(str(tmp_path), "/tmp/odoo.conf", "normal", (), {}, str(tmp_path), version="18")
        assert exc.value.code == 0
        assert captured.get("start_new_session") is True

    def test_server_mode_ctrl_c_stops_process_group(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch)
        stopped = {}

        class _FakeProc:
            pid = 4321
            returncode = 0

            def wait(self):
                raise KeyboardInterrupt

        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc())
        monkeypatch.setattr("odoodev.commands.start.os.getpgid", lambda pid: 9999)
        monkeypatch.setattr(
            "odoodev.core.process_manager.stop_process_group",
            lambda pgid, timeout=5, force=False: stopped.__setitem__("pgid", pgid) or True,
        )

        with pytest.raises(SystemExit) as exc:
            _start_odoo(str(tmp_path), "/tmp/odoo.conf", "normal", (), {}, str(tmp_path), version="18")
        assert exc.value.code == 0
        assert stopped.get("pgid") == 9999


class TestCheckServicesReadiness:
    """PostgreSQL readiness gating in _check_services (Apple Container boot race).

    The old implementation used a bare TCP check plus a flat ``time.sleep(5)``
    after ``service_up`` — on Apple Container the micro-VM's port forwarder
    accepts TCP before postgres is ready, so odoo-bin launched into 10-30s of
    silent DB-connection retries. These tests pin the protocol-level wait.
    """

    def _version_cfg(self, tmp_path):
        from types import SimpleNamespace

        return SimpleNamespace(
            ports=SimpleNamespace(db=18432, odoo=18069),
            paths=SimpleNamespace(native_dir=str(tmp_path)),
        )

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        # No active migration group, odoo port free, no requirements.txt checks.
        monkeypatch.setattr("odoodev.core.migration_config.get_active_group", lambda: None)
        monkeypatch.setattr("odoodev.commands.start.check_port", lambda host, port: False)
        monkeypatch.setattr("odoodev.commands.start.check_requirements_changed", lambda *a, **k: False)

    def test_no_bare_sleep_regression(self):
        """The flat time.sleep(5) must never come back — readiness is polled."""
        import inspect

        assert "time.sleep(" not in inspect.getsource(_check_services)

    def test_fast_path_skips_service_start(self, monkeypatch, tmp_path):
        """PostgreSQL ready at the initial gate → no runtime prompt, no service_up."""
        monkeypatch.setattr("odoodev.commands.start.wait_for_postgres_ready", lambda *a, **k: True)
        monkeypatch.setattr(
            "odoodev.commands.start._select_runtime",
            lambda *a, **k: pytest.fail("_select_runtime must not be called when PostgreSQL is ready"),
        )
        _check_services({}, self._version_cfg(tmp_path), "18", str(tmp_path), str(tmp_path), no_confirm=True)

    def test_initial_gate_uses_fail_fast(self, monkeypatch, tmp_path):
        """The initial gate must fail fast on a closed port (no 60s wait before the prompt)."""
        calls = []

        def fake_wait(host, port, timeout=60.0, poll_interval=1.0, fail_fast_if_closed=False):
            calls.append({"port": port, "timeout": timeout, "fail_fast_if_closed": fail_fast_if_closed})
            return True

        monkeypatch.setattr("odoodev.commands.start.wait_for_postgres_ready", fake_wait)
        _check_services({}, self._version_cfg(tmp_path), "18", str(tmp_path), str(tmp_path), no_confirm=True)
        assert calls[0]["port"] == 18432
        assert calls[0]["fail_fast_if_closed"] is True

    def _run_with_service_up(self, monkeypatch, tmp_path, wait_results):
        """Drive the 'PostgreSQL down → start service' branch with a mocked backend."""
        calls = []

        def fake_wait(host, port, timeout=60.0, poll_interval=1.0, fail_fast_if_closed=False):
            calls.append({"port": port, "timeout": timeout, "fail_fast_if_closed": fail_fast_if_closed})
            return wait_results[len(calls) - 1]

        monkeypatch.setattr("odoodev.commands.start.wait_for_postgres_ready", fake_wait)
        monkeypatch.setattr("odoodev.commands.start._select_runtime", lambda *a, **k: "docker")

        class _Backend:
            name = "Docker"

            def service_up(self, cfg, env):
                return 0

        monkeypatch.setattr("odoodev.core.container_backend.get_backend", lambda rt: _Backend())
        monkeypatch.setattr("odoodev.core.container_backend.read_env_file", lambda native_dir: {})
        _check_services({}, self._version_cfg(tmp_path), "18", str(tmp_path), str(tmp_path), no_confirm=True)
        return calls

    def test_waits_for_readiness_after_service_up(self, monkeypatch, tmp_path):
        calls = self._run_with_service_up(monkeypatch, tmp_path, wait_results=[False, True])
        assert len(calls) == 2
        # Post-service_up wait: full timeout, no fail-fast (container is booting).
        assert calls[1]["port"] == 18432
        assert calls[1]["timeout"] == 60
        assert calls[1]["fail_fast_if_closed"] is False

    def test_raises_when_wait_times_out_after_service_up(self, monkeypatch, tmp_path):
        with pytest.raises(SystemExit) as exc:
            self._run_with_service_up(monkeypatch, tmp_path, wait_results=[False, False])
        assert exc.value.code == 1


class TestRequirementsHashAfterStartUpdate:
    """Regression: the start-triggered requirements update must persist the hash.

    Previously ``_check_services`` called ``install_requirements`` after the
    user confirmed the update but never ``store_requirements_hash`` — so every
    subsequent ``odoodev start`` re-prompted for the same update. Only
    ``odoodev venv setup`` wrote the hash file.
    """

    def _version_cfg(self, tmp_path):
        from types import SimpleNamespace

        return SimpleNamespace(
            ports=SimpleNamespace(db=18432, odoo=18069),
            paths=SimpleNamespace(native_dir=str(tmp_path)),
        )

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch, tmp_path):
        monkeypatch.setattr("odoodev.core.migration_config.get_active_group", lambda: None)
        monkeypatch.setattr("odoodev.commands.start.check_port", lambda host, port: False)
        monkeypatch.setattr("odoodev.commands.start.wait_for_postgres_ready", lambda *a, **k: True)
        monkeypatch.setattr("odoodev.commands.start.check_requirements_changed", lambda *a, **k: True)
        monkeypatch.setattr("odoodev.commands.start.confirm", lambda *a, **k: True)
        (tmp_path / "requirements.txt").write_text("click\n")

    def test_hash_stored_after_successful_install(self, monkeypatch, tmp_path):
        stored = {}
        monkeypatch.setattr("odoodev.commands.start.install_requirements", lambda *a, **k: True)
        monkeypatch.setattr(
            "odoodev.commands.start.store_requirements_hash",
            lambda venv_dir, requirements: stored.update(venv_dir=venv_dir, requirements=requirements),
        )
        _check_services({}, self._version_cfg(tmp_path), "18", str(tmp_path), str(tmp_path), no_confirm=False)
        assert stored["venv_dir"] == str(tmp_path)
        assert stored["requirements"] == str(tmp_path / "requirements.txt")

    def test_hash_not_stored_when_install_fails(self, monkeypatch, tmp_path):
        monkeypatch.setattr("odoodev.commands.start.install_requirements", lambda *a, **k: False)
        monkeypatch.setattr(
            "odoodev.commands.start.store_requirements_hash",
            lambda *a, **k: pytest.fail("store_requirements_hash must not be called after a failed install"),
        )
        _check_services({}, self._version_cfg(tmp_path), "18", str(tmp_path), str(tmp_path), no_confirm=False)

    def test_no_confirm_skips_install_and_hash(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "odoodev.commands.start.install_requirements",
            lambda *a, **k: pytest.fail("install_requirements must not run under --no-confirm"),
        )
        monkeypatch.setattr(
            "odoodev.commands.start.store_requirements_hash",
            lambda *a, **k: pytest.fail("store_requirements_hash must not run under --no-confirm"),
        )
        _check_services({}, self._version_cfg(tmp_path), "18", str(tmp_path), str(tmp_path), no_confirm=True)


class TestReportRequirementsSync:
    """start regenerates requirements.txt before it compares hashes."""

    def _outcome(self, warnings=()):
        from odoodev.core.requirements_merge import MergeResult, Requirement
        from odoodev.core.requirements_sync import SyncOutcome

        base = Requirement(name="Werkzeug", key="werkzeug", extras=(), specifier="==3.1.3", marker="", comment="")
        local = Requirement(name="Werkzeug", key="werkzeug", extras=(), specifier="==3.0.6", marker="", comment="")
        return SyncOutcome(
            version="16",
            written=True,
            stale=True,
            path="/tmp/requirements.txt",
            result=MergeResult(body=(), replaced=((base, local),), added=(), added_passthrough=(), warnings=warnings),
            blocked_reason="",
        )

    def test_reports_regeneration_and_warnings(self, monkeypatch, capsys):
        from odoodev.commands.start import _report_requirements_sync

        outcome = self._outcome(warnings=("Werkzeug: overlay holds 3.0.6 back (base: 3.1.3)",))
        monkeypatch.setattr(
            "odoodev.commands.start.ensure_generated_requirements",
            lambda version, version_cfg: outcome,
        )

        assert _report_requirements_sync("16", object()) is True
        out = capsys.readouterr().out
        assert "regenerated" in out
        assert "holds 3.0.6 back" in out
        assert "overlay pins ==3.0.6" in out

    def test_stays_silent_when_nothing_changed(self, monkeypatch, capsys):
        from odoodev.commands.start import _report_requirements_sync

        monkeypatch.setattr(
            "odoodev.commands.start.ensure_generated_requirements",
            lambda version, version_cfg: None,
        )

        assert _report_requirements_sync("16", object()) is False
        assert capsys.readouterr().out == ""


from click.testing import CliRunner  # noqa: E402

from odoodev.commands.start import start  # noqa: E402


class TestStartInfoOrdering:
    """v0.59.0 flow: instance info → confirmation → preflight → launch.

    Declining the start must not trigger any side-effecting preflight check
    (no ~/.pgpass write, no container start, no setup prompts).
    """

    def _setup(self, monkeypatch, tmp_path, confirm_answers=None):
        import types

        import odoodev.commands.start as start_cmd

        calls: list[str] = []

        monkeypatch.setattr(start_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(start_cmd, "load_versions", lambda: {})
        monkeypatch.setattr(
            start_cmd,
            "get_version",
            lambda v, versions=None: types.SimpleNamespace(
                version="18",
                python="3.13",
                postgres="16",
                ports=types.SimpleNamespace(db=18432, odoo=18069, gevent=18072, mailpit=18025, smtp=1025),
                paths=types.SimpleNamespace(
                    native_dir=str(tmp_path),
                    server_dir=str(tmp_path),
                    myconfs_dir=str(tmp_path / "myconfs"),
                ),
            ),
        )
        monkeypatch.setattr(start_cmd, "_check_env_file", lambda ctx, v, d: calls.append("env") or {})
        monkeypatch.setattr(
            start_cmd,
            "_print_start_info",
            lambda *a, **k: calls.append("info"),
        )
        monkeypatch.setattr(
            start_cmd,
            "_run_preflight",
            lambda *a, **k: calls.append("preflight") or ("/tmp/odoo.conf", {}),
        )
        monkeypatch.setattr(start_cmd, "_start_odoo", lambda *a, **k: calls.append("start_odoo"))
        monkeypatch.setattr(start_cmd, "_start_interactive_shell", lambda *a, **k: calls.append("shell"))

        answers = list(confirm_answers or [])

        def fake_confirm(message, default=True):
            calls.append(f"confirm:{message}")
            return answers.pop(0) if answers else True

        monkeypatch.setattr(start_cmd, "confirm", fake_confirm)
        return calls

    def test_confirmed_start_order(self, monkeypatch, tmp_path):
        calls = self._setup(monkeypatch, tmp_path, confirm_answers=[True])
        result = CliRunner().invoke(start, ["18"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        confirm_idx = next(i for i, c in enumerate(calls) if c.startswith("confirm:"))
        assert calls.index("info") < confirm_idx < calls.index("preflight") < calls.index("start_odoo")

    def test_yes_skips_confirm_but_prints_info(self, monkeypatch, tmp_path):
        calls = self._setup(monkeypatch, tmp_path)
        result = CliRunner().invoke(start, ["18", "--yes"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "info" in calls
        assert not any(c.startswith("confirm:") for c in calls)
        assert calls.index("preflight") < calls.index("start_odoo")

    def test_declined_start_runs_no_preflight(self, monkeypatch, tmp_path):
        """No to start, no to the shell fallback → zero side effects."""
        calls = self._setup(monkeypatch, tmp_path, confirm_answers=[False, False])
        result = CliRunner().invoke(start, ["18"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "preflight" not in calls
        assert "start_odoo" not in calls
        assert "shell" not in calls

    def test_declined_start_accepted_shell_runs_preflight(self, monkeypatch, tmp_path):
        calls = self._setup(monkeypatch, tmp_path, confirm_answers=[False, True])
        result = CliRunner().invoke(start, ["18"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert calls.index("preflight") < calls.index("shell")
        assert "start_odoo" not in calls

    def test_prepare_skips_info_and_confirm(self, monkeypatch, tmp_path):
        calls = self._setup(monkeypatch, tmp_path)
        result = CliRunner().invoke(start, ["18", "--prepare"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "info" not in calls
        assert not any(c.startswith("confirm:") for c in calls)
        assert calls.index("preflight") < calls.index("shell")

    def test_yes_flag_visible_in_help(self):
        result = CliRunner().invoke(start, ["--help"])
        assert result.exit_code == 0
        assert "--yes" in result.output

    def test_print_start_info_shows_missing_config_hint(self, monkeypatch, tmp_path, capsys):
        import types

        from odoodev.commands.start import _print_start_info

        cfg = types.SimpleNamespace(
            ports=types.SimpleNamespace(db=18432, odoo=18069, gevent=18072, mailpit=18025),
        )
        monkeypatch.setattr("odoodev.core.migration_config.resolve_db_port", lambda v, d, e: d)
        _print_start_info(
            "18",
            cfg,
            {},
            "normal",
            None,
            (),
            str(tmp_path),
            str(tmp_path),
            str(tmp_path / "myconfs"),
            None,
        )
        out = capsys.readouterr().out
        assert "not generated yet" in out
        assert "18069" in out
        assert "18432" in out
