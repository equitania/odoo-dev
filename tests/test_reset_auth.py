"""v0.66.0: reset every user's password and/or 2FA after a restore.

Core helpers (``reset_all_passwords`` / ``reset_all_2fa``), the two ``db restore``
flags, the standalone ``db reset-auth`` command, the playbook args and the
visible wipe/recompute reporting that landed in the same release.
"""

from __future__ import annotations

import types

from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core.database import WipeResult, reset_all_2fa, reset_all_passwords
from tests import test_automation as _ta
from tests import test_database as _td
from tests.test_automation import mock_version_cfg  # noqa: F401 — fixture re-export

# Harness reuse by composition — binding the Test* classes here would make pytest
# collect (and re-run) every one of their tests under this module.
_CLI = _td.TestRestoreCliFlags()
_PB = _ta.TestDbRestoreHandler()


class TestResetAllPasswords:
    def test_hashes_once_and_targets_every_real_login_including_admin(self, monkeypatch):
        psql: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (psql.append(q), (True, "UPDATE 12\n"))[1],
        )
        ok, count = reset_all_passwords("db", "ownerp")
        assert ok is True
        assert count == 12
        assert len(psql) == 1
        stmt = psql[0]
        assert stmt.startswith("UPDATE res_users SET password = '$pbkdf2-sha512$")
        assert "'ownerp'" not in stmt
        # admin (id=1) IS included — unlike anonymize_users — technical logins are not.
        assert "id > 1" not in stmt
        for login in ("__system__", "default", "public", "portaltemplate"):
            assert f"'{login}'" in stmt

    def test_reports_failure(self, monkeypatch):
        monkeypatch.setattr("odoodev.core.database._run_psql", lambda q, **k: (False, "boom"))
        ok, count = reset_all_passwords("db", "x")
        assert ok is False
        assert count == 0


class TestResetAll2fa:
    def _capture(self, monkeypatch, columns):
        psql: list[str] = []
        monkeypatch.setattr(
            "odoodev.core.database._existing_columns",
            lambda table, *a, **k: columns.get(table, set()),
        )
        monkeypatch.setattr(
            "odoodev.core.database._run_psql",
            lambda q, **k: (psql.append(q), (True, "UPDATE 3\n" if q.startswith("UPDATE") else "DELETE 2\n"))[1],
        )
        return psql

    def test_noop_without_auth_totp(self, monkeypatch):
        psql = self._capture(monkeypatch, {"res_users": {"id", "login"}, "ir_config_parameter": {"key"}})
        ok, msg = reset_all_2fa("db")
        assert ok is True
        assert psql == []
        assert "auth_totp" in msg

    def test_clears_secrets_devices_and_enforcement_policy(self, monkeypatch):
        psql = self._capture(
            monkeypatch,
            {
                "res_users": {"id", "login", "totp_secret"},
                "auth_totp_device": {"id", "user_id"},
                "ir_config_parameter": {"key", "value"},
            },
        )
        ok, msg = reset_all_2fa("db")
        assert ok is True
        assert any("UPDATE res_users SET totp_secret = NULL" in q for q in psql)
        assert any(q.strip() == "DELETE FROM auth_totp_device;" for q in psql)
        # auth_totp_mail_enforce: an enforced policy would push every user into a
        # mail-OTP the neutralized DB never delivers → remove it.
        assert any("DELETE FROM ir_config_parameter WHERE key = 'auth_totp.policy'" in q for q in psql)
        assert "3" in msg  # users whose secret was cleared

    def test_skips_device_table_when_absent(self, monkeypatch):
        psql = self._capture(
            monkeypatch,
            {"res_users": {"id", "totp_secret"}, "ir_config_parameter": {"key"}},
        )
        ok, _ = reset_all_2fa("db")
        assert ok is True
        assert not any("auth_totp_device" in q for q in psql)


class TestRestoreResetFlags:
    """The two new opt-in flags on ``db restore`` (reuse the flow harness)."""

    def _patch_reset(self, monkeypatch, calls):
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(
            db_cmd,
            "reset_all_passwords",
            lambda name, pw, **k: (calls.setdefault("reset_pw", []).append((name, pw)), (True, 5))[1],
        )
        monkeypatch.setattr(
            db_cmd,
            "reset_all_2fa",
            lambda name, **k: (calls.setdefault("reset_2fa", []).append(name), (True, "2FA cleared for 2 user(s)"))[1],
        )

    def _run(self, monkeypatch, tmp_path, *flags):
        calls: dict = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        _CLI._patch_flow(monkeypatch, tmp_path, calls)
        self._patch_reset(monkeypatch, calls)
        result = _CLI._restore(backup, *flags)
        assert result.exit_code == 0, result.output
        return calls, result

    def test_help_lists_reset_flags(self):
        result = CliRunner().invoke(cli, ["db", "restore", "--help"])
        assert "--reset-passwords" in result.output
        assert "--reset-2fa" in result.output

    def test_off_by_default_and_not_in_sanitize(self, monkeypatch, tmp_path):
        calls, _ = self._run(monkeypatch, tmp_path, "--sanitize", "-y")
        assert "reset_pw" not in calls
        assert "reset_2fa" not in calls

    def test_reset_passwords_uses_user_password(self, monkeypatch, tmp_path):
        calls, result = self._run(monkeypatch, tmp_path, "--reset-passwords", "--user-password", "secret1", "-y")
        assert calls.get("reset_pw") == [("testdb", "secret1")]
        assert "reset_2fa" not in calls
        assert "5" in result.output  # count reported

    def test_reset_2fa_alone(self, monkeypatch, tmp_path):
        calls, result = self._run(monkeypatch, tmp_path, "--reset-2fa", "-y")
        assert calls.get("reset_2fa") == ["testdb"]
        assert "reset_pw" not in calls
        assert "2FA cleared" in result.output

    def test_runs_after_anonymize_users(self, monkeypatch, tmp_path):
        """anonymize-users renames + sets ONE password; reset-passwords must win afterwards."""
        order: list[str] = []
        calls: dict = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        _CLI._patch_flow(monkeypatch, tmp_path, calls)
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "anonymize_users", lambda name, **k: (order.append("anon_users"), True)[1])
        monkeypatch.setattr(db_cmd, "reset_all_passwords", lambda name, pw, **k: (order.append("reset"), (True, 1))[1])
        result = _CLI._restore(backup, "--anonymize-users", "--reset-passwords", "-y")
        assert result.exit_code == 0, result.output
        assert order == ["anon_users", "reset"]

    def test_wipe_reports_row_and_file_counts(self, monkeypatch, tmp_path):
        calls: dict = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        _CLI._patch_flow(monkeypatch, tmp_path, calls)
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(
            db_cmd, "wipe_database", lambda name, **k: WipeResult(True, attachments_deleted=1655, files_removed=1650)
        )
        result = _CLI._restore(backup, "--wipe", "-y")
        assert result.exit_code == 0, result.output
        assert "1655" in result.output
        assert "1650" in result.output

    def test_recompute_skipped_records_are_shown_as_warnings(self, monkeypatch, tmp_path):
        calls: dict = {}
        backup = tmp_path / "b.zip"
        backup.write_text("x")
        _CLI._patch_flow(monkeypatch, tmp_path, calls, inv={})
        from odoodev.commands import db as db_cmd

        out = (
            "odoodev-recompute: skipped res.partner id=42: Der Peppol-Endpunkt ist nicht gültig\n"
            "odoodev-recompute: done (1 skipped)\n"
        )
        monkeypatch.setattr(db_cmd, "run_recompute", lambda name, **k: (True, out))
        result = _CLI._restore(backup, "--anonymize", "-y")
        assert result.exit_code == 0, result.output
        assert "res.partner id=42" in result.output
        assert "1 skipped" in result.output


class TestResetAuthCommand:
    def _patch(self, monkeypatch, tmp_path, calls):
        from odoodev.commands import db as db_cmd

        cfg = types.SimpleNamespace(
            version="18",
            ports=types.SimpleNamespace(db=18432),
            paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
        )
        monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
        monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
        monkeypatch.setattr(db_cmd, "_load_env_vars", lambda vc: {})
        monkeypatch.setattr(db_cmd, "_get_db_params", lambda vc, ev: {"host": "h", "port": 18432, "user": "u"})
        monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda v, p: None)
        monkeypatch.setattr(
            db_cmd,
            "reset_all_passwords",
            lambda name, pw, **k: (calls.setdefault("pw", []).append((name, pw)), (True, 7))[1],
        )
        monkeypatch.setattr(
            db_cmd, "reset_all_2fa", lambda name, **k: (calls.setdefault("2fa", []).append(name), (True, "ok"))[1]
        )
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: calls.setdefault("confirm", True))

    def test_help(self):
        result = CliRunner().invoke(cli, ["db", "reset-auth", "--help"])
        assert result.exit_code == 0
        for flag in ("--passwords", "--2fa", "--user-password", "-y"):
            assert flag in result.output

    def test_requires_a_selection(self, monkeypatch, tmp_path):
        calls: dict = {}
        self._patch(monkeypatch, tmp_path, calls)
        result = CliRunner().invoke(cli, ["db", "reset-auth", "18", "-n", "testdb", "-y"])
        assert result.exit_code == 1
        assert "pw" not in calls and "2fa" not in calls

    def test_both_with_yes(self, monkeypatch, tmp_path):
        calls: dict = {}
        self._patch(monkeypatch, tmp_path, calls)
        result = CliRunner().invoke(
            cli, ["db", "reset-auth", "18", "-n", "testdb", "--passwords", "--2fa", "--user-password", "pw1", "-y"]
        )
        assert result.exit_code == 0, result.output
        assert calls["pw"] == [("testdb", "pw1")]
        assert calls["2fa"] == ["testdb"]
        assert "confirm" not in calls

    def test_declined_confirmation_changes_nothing(self, monkeypatch, tmp_path):
        calls: dict = {}
        self._patch(monkeypatch, tmp_path, calls)
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "reset-auth", "18", "-n", "testdb", "--passwords"])
        assert result.exit_code == 1
        assert "pw" not in calls

    def test_failure_exits_nonzero(self, monkeypatch, tmp_path):
        calls: dict = {}
        self._patch(monkeypatch, tmp_path, calls)
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "reset_all_2fa", lambda name, **k: (False, "psql exploded"))
        result = CliRunner().invoke(cli, ["db", "reset-auth", "18", "-n", "testdb", "--2fa", "-y"])
        assert result.exit_code == 1
        assert "psql exploded" in result.output


class TestPlaybookRestoreArgs:
    def _patch_user_steps(self, monkeypatch, calls):
        import odoodev.core.database as dbmod

        monkeypatch.setattr(
            dbmod,
            "anonymize_users",
            lambda name, dev_password="ownerp", **k: (calls.setdefault("anon_users", []).append(dev_password), True)[1],
        )
        monkeypatch.setattr(
            dbmod,
            "reset_all_passwords",
            lambda name, pw, **k: (calls.setdefault("reset_pw", []).append(pw), (True, 1))[1],
        )
        monkeypatch.setattr(
            dbmod, "reset_all_2fa", lambda name, **k: (calls.setdefault("reset_2fa", []).append(name), (True, "ok"))[1]
        )

    def test_anonymize_users_and_password_args(self, monkeypatch, tmp_path, mock_version_cfg):  # noqa: F811
        from odoodev.core.automation import handle_db_restore

        calls: dict = {}
        _PB._patch_restore_flow(monkeypatch, tmp_path, calls)
        self._patch_user_steps(monkeypatch, calls)
        args = _PB._restore_args(tmp_path, **{"anonymize-users": True, "user-password": "devpw"})
        result = handle_db_restore(mock_version_cfg, args)
        assert result.status == "ok"
        assert calls.get("anon_users") == ["devpw"]
        assert "reset_pw" not in calls

    def test_reset_args(self, monkeypatch, tmp_path, mock_version_cfg):  # noqa: F811
        from odoodev.core.automation import handle_db_restore

        calls: dict = {}
        _PB._patch_restore_flow(monkeypatch, tmp_path, calls)
        self._patch_user_steps(monkeypatch, calls)
        args = _PB._restore_args(tmp_path, **{"reset-passwords": True, "reset_2fa": True, "user_password": "pw2"})
        result = handle_db_restore(mock_version_cfg, args)
        assert result.status == "ok"
        assert calls.get("reset_pw") == ["pw2"]
        assert calls.get("reset_2fa") == ["testdb"]

    def test_sanitize_does_not_imply_reset(self, monkeypatch, tmp_path, mock_version_cfg):  # noqa: F811
        from odoodev.core.automation import handle_db_restore

        calls: dict = {}
        _PB._patch_restore_flow(monkeypatch, tmp_path, calls)
        self._patch_user_steps(monkeypatch, calls)
        import odoodev.core.database as dbmod

        monkeypatch.setattr(dbmod, "anonymize_database", lambda name, **k: True)
        monkeypatch.setattr(dbmod, "wipe_database", lambda name, **k: WipeResult(True))
        monkeypatch.setattr(dbmod, "run_neutralize", lambda name, **k: (True, ""))
        monkeypatch.setattr(dbmod, "run_recompute", lambda name, **k: (True, ""))
        result = handle_db_restore(mock_version_cfg, _PB._restore_args(tmp_path, sanitize=True))
        assert result.status == "ok"
        assert "reset_pw" not in calls and "reset_2fa" not in calls and "anon_users" not in calls


class TestPlaybookSchema:
    def test_db_restore_offers_user_args(self):
        from odoodev.core.playbook_schema import STEP_ARG_SPECS

        names = {a.name for a in STEP_ARG_SPECS["db.restore"].args}
        for name in ("anonymize-users", "user-password", "reset-passwords", "reset-2fa"):
            assert name in names
