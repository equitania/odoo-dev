"""Tests for 'db restore --dry-run' — the GUI restore-wizard preflight contract.

Dry-run validates the restore (backup file, target DB, disk space) and reports
the planned post-restore steps WITHOUT touching anything: no drop, no create,
no extraction, no restore.
"""

from __future__ import annotations

import types

import pytest
from click.testing import CliRunner

from odoodev.cli import cli


@pytest.fixture()
def backup_file(tmp_path):
    f = tmp_path / "v18_prod_backup.zip"
    f.write_bytes(b"fake-zip-content")
    return f


def _forbidden(name):
    def _fail(*a, **k):
        raise AssertionError(f"{name} must not be called during --dry-run")

    return _fail


@pytest.fixture()
def patched(monkeypatch, tmp_path):
    """Patch the restore command's environment; forbid every mutating call."""
    from odoodev.commands import db as db_cmd

    cfg = types.SimpleNamespace(
        version="18",
        ports=types.SimpleNamespace(db=18432),
        paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
    )
    state = {"db_exists": False, "space": (True, "Disk space OK", 0), "cleanup": []}

    monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
    monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
    monkeypatch.setattr(db_cmd, "_load_env_vars", lambda vc: {})
    monkeypatch.setattr(db_cmd, "_get_db_params", lambda vc, ev: {"host": "localhost", "port": 18432, "user": "u"})
    monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda v, p: None)
    monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
    monkeypatch.setattr(db_cmd, "database_exists", lambda name, **k: state["db_exists"])
    monkeypatch.setattr(db_cmd, "get_filestore_path", lambda v, n: str(tmp_path / "filestore" / n))
    monkeypatch.setattr(db_cmd, "get_restore_temp_dir", lambda b: str(tmp_path))
    monkeypatch.setattr(db_cmd, "check_restore_space", lambda b, t, f: state["space"])
    monkeypatch.setattr(db_cmd, "cleanup_restore_temp", lambda p: state["cleanup"].append(p))

    for fn in ("drop_database", "create_database", "restore_database", "extract_backup", "detect_backup_type"):
        monkeypatch.setattr(db_cmd, fn, _forbidden(fn))

    return state


def _invoke(args):
    return CliRunner().invoke(cli, ["db", "restore", "18", *args])


class TestRestoreDryRun:
    def test_passes_and_touches_nothing(self, patched, backup_file):
        result = _invoke(["-n", "testdb", "-z", str(backup_file), "--dry-run", "-y"])
        assert result.exit_code == 0, result.output
        assert "Dry run passed" in result.output
        assert "nothing was changed" in result.output

    def test_reports_planned_steps(self, patched, backup_file):
        args = ["-n", "testdb", "-z", str(backup_file), "--anonymize", "--anonymize-users", "--dry-run", "-y"]
        result = _invoke(args)
        assert result.exit_code == 0, result.output
        assert "anonymize" in result.output
        assert "anonymize-users" in result.output
        # recompute auto-runs with anonymize
        assert "recompute" in result.output

    def test_no_steps_reports_untouched(self, patched, backup_file):
        result = _invoke(["-n", "testdb", "-z", str(backup_file), "--dry-run", "-y"])
        assert result.exit_code == 0, result.output
        assert "untouched" in result.output

    def test_missing_backup_fails(self, patched, tmp_path):
        result = _invoke(["-n", "testdb", "-z", str(tmp_path / "missing.zip"), "--dry-run", "-y"])
        assert result.exit_code == 1
        assert "Dry run failed" in result.output

    def test_existing_db_with_drop_warns_but_passes(self, patched, backup_file):
        patched["db_exists"] = True
        result = _invoke(["-n", "testdb", "-z", str(backup_file), "--drop", "--dry-run", "-y"])
        assert result.exit_code == 0, result.output
        assert "would be dropped" in result.output.lower()

    def test_existing_db_no_drop_fails(self, patched, backup_file):
        patched["db_exists"] = True
        result = _invoke(["-n", "testdb", "-z", str(backup_file), "--no-drop", "--dry-run", "-y"])
        assert result.exit_code == 1
        assert "Dry run failed" in result.output

    def test_insufficient_space_fails(self, patched, backup_file):
        patched["space"] = (False, "Not enough free disk space", 0)
        result = _invoke(["-n", "testdb", "-z", str(backup_file), "--dry-run", "-y"])
        assert result.exit_code == 1
        assert "Dry run failed" in result.output

    def test_space_check_temp_dir_cleaned_up(self, patched, backup_file):
        result = _invoke(["-n", "testdb", "-z", str(backup_file), "--dry-run", "-y"])
        assert result.exit_code == 0, result.output
        assert patched["cleanup"], "space-check temp dir must be cleaned up"
