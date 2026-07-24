"""Tests for `odoodev db cleanup` — filestore <-> database consistency check."""

from __future__ import annotations

import json

from click.testing import CliRunner

from odoodev.cli import cli


def _stub(monkeypatch, tmp_path, dbs):
    from odoodev.commands import db as db_cmd

    monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "18")
    monkeypatch.setattr(db_cmd, "get_version", lambda v: object())
    monkeypatch.setattr(db_cmd, "_load_env_vars", lambda cfg: {})
    monkeypatch.setattr(
        db_cmd, "_get_db_params", lambda cfg, env: {"host": "localhost", "port": 18432, "user": "ownerp"}
    )
    monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda v, p: None)
    monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
    monkeypatch.setattr(db_cmd, "list_databases", lambda **k: dbs)
    monkeypatch.setattr(db_cmd, "get_filestore_path", lambda ver, db: str(tmp_path / "filestore" / db))
    return db_cmd


def _make_filestore(tmp_path, name: str, size: int = 0):
    d = tmp_path / "filestore" / name
    d.mkdir(parents=True)
    if size:
        (d / "blob").write_bytes(b"x" * size)
    return d


class TestDbCleanupReport:
    def test_consistent_state(self, monkeypatch, tmp_path):
        _stub(monkeypatch, tmp_path, ["v18_a", "v18_b"])
        _make_filestore(tmp_path, "v18_a")
        _make_filestore(tmp_path, "v18_b")
        result = CliRunner().invoke(cli, ["db", "cleanup", "18"])
        assert result.exit_code == 0
        assert "consistent" in result.output

    def test_reports_orphans_and_missing(self, monkeypatch, tmp_path):
        _stub(monkeypatch, tmp_path, ["v18_a", "v18_new"])
        _make_filestore(tmp_path, "v18_a")
        orphan = _make_filestore(tmp_path, "v18_gone", size=10)
        result = CliRunner().invoke(cli, ["db", "cleanup", "18"])
        assert result.exit_code == 0
        assert "Orphaned filestores" in result.output
        assert "v18_gone" in result.output
        assert "without a filestore" in result.output
        assert "v18_new" in result.output
        # Report-only: nothing deleted, remediation hint shown.
        assert orphan.exists()
        assert "--delete-orphans" in result.output

    def test_missing_filestore_root_means_all_dbs_missing(self, monkeypatch, tmp_path):
        _stub(monkeypatch, tmp_path, ["v18_a"])
        result = CliRunner().invoke(cli, ["db", "cleanup", "18"])
        assert result.exit_code == 0
        assert "v18_a" in result.output
        assert "Orphaned" not in result.output


class TestDbCleanupJson:
    def test_json_contract(self, monkeypatch, tmp_path):
        _stub(monkeypatch, tmp_path, ["v18_a", "v18_new"])
        _make_filestore(tmp_path, "v18_a")
        _make_filestore(tmp_path, "v18_gone", size=7)
        result = CliRunner().invoke(cli, ["db", "cleanup", "18", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert data["version"] == "18"
        assert data["filestore_root"] == str(tmp_path / "filestore")
        assert data["databases_without_filestore"] == ["v18_new"]
        (orphan,) = data["orphaned_filestores"]
        assert orphan["name"] == "v18_gone"
        assert orphan["size_bytes"] == 7

    def test_json_refuses_delete_orphans(self, monkeypatch, tmp_path):
        _stub(monkeypatch, tmp_path, [])
        result = CliRunner().invoke(cli, ["db", "cleanup", "18", "--json", "--delete-orphans"])
        assert result.exit_code != 0
        assert "report-only" in result.output


class TestDbCleanupDelete:
    def test_delete_orphans_with_yes(self, monkeypatch, tmp_path):
        _stub(monkeypatch, tmp_path, ["v18_a"])
        kept = _make_filestore(tmp_path, "v18_a")
        orphan = _make_filestore(tmp_path, "v18_gone", size=5)
        result = CliRunner().invoke(cli, ["db", "cleanup", "18", "--delete-orphans", "-y"])
        assert result.exit_code == 0
        assert not orphan.exists()
        assert kept.exists()
        assert "Freed" in result.output

    def test_delete_orphans_confirm_declined(self, monkeypatch, tmp_path):
        db_cmd = _stub(monkeypatch, tmp_path, ["v18_a"])
        orphan = _make_filestore(tmp_path, "v18_gone")
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = CliRunner().invoke(cli, ["db", "cleanup", "18", "--delete-orphans"])
        assert result.exit_code == 0
        assert orphan.exists()
        assert "Nothing deleted" in result.output

    def test_delete_orphans_confirm_accepted(self, monkeypatch, tmp_path):
        db_cmd = _stub(monkeypatch, tmp_path, ["v18_a"])
        orphan = _make_filestore(tmp_path, "v18_gone")
        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: True)
        result = CliRunner().invoke(cli, ["db", "cleanup", "18", "--delete-orphans"])
        assert result.exit_code == 0
        assert not orphan.exists()
