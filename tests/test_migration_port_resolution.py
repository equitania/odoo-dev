"""Tests for migration-aware DB port resolution (resolve_db_port).

Regression for the migration-server bug: the target version's .env still
contains its regular DB_PORT (e.g. 18432), which silently overrode the active
migration's shared port (e.g. 16432) — `db backup 18` / `start 18` then tried
the wrong port while `db backup 16` worked.
"""

from __future__ import annotations

from types import SimpleNamespace

import odoodev.cli  # noqa: F401 — import the CLI first to resolve the commands<->cli import cycle
from odoodev.core.migration_config import MigrationGroup, migration_target_port, resolve_db_port

GROUP_16_TO_18 = MigrationGroup(
    name="16-to-18",
    from_version="16",
    to_version="18",
    pg_version="16.11-alpine",
    shared_db_port=16432,
    shared_filestore_base="~/odoo-share/migration/16-to-18",
    created_at="2026-07-03T10:00:00+00:00",
)


def _activate_group(monkeypatch, group=GROUP_16_TO_18):
    monkeypatch.setattr("odoodev.core.migration_config.get_active_group", lambda: group)


def _no_group(monkeypatch):
    monkeypatch.setattr("odoodev.core.migration_config.get_active_group", lambda: None)


# --- migration_target_port ---


def test_target_port_for_migration_target(monkeypatch):
    _activate_group(monkeypatch)
    assert migration_target_port("18") == 16432


def test_target_port_none_for_source_version(monkeypatch):
    _activate_group(monkeypatch)
    assert migration_target_port("16") is None


def test_target_port_none_without_group(monkeypatch):
    _no_group(monkeypatch)
    assert migration_target_port("18") is None


def test_target_port_none_for_none_version(monkeypatch):
    _activate_group(monkeypatch)
    assert migration_target_port(None) is None


# --- resolve_db_port ---


def test_resolve_env_wins_without_migration(monkeypatch):
    _no_group(monkeypatch)
    assert resolve_db_port("18", 18432, {"DB_PORT": "15555"}) == 15555


def test_resolve_default_without_env(monkeypatch):
    _no_group(monkeypatch)
    assert resolve_db_port("18", 18432, {}) == 18432
    assert resolve_db_port("18", 18432, None) == 18432


def test_resolve_invalid_env_falls_back_to_default(monkeypatch):
    _no_group(monkeypatch)
    assert resolve_db_port("18", 18432, {"DB_PORT": "not-a-port"}) == 18432


def test_resolve_migration_target_overrides_stale_env(monkeypatch):
    """The core regression: target's .env DB_PORT must NOT win during a migration."""
    _activate_group(monkeypatch)
    assert resolve_db_port("18", 16432, {"DB_PORT": "18432"}) == 16432


def test_resolve_source_env_still_wins_during_migration(monkeypatch):
    _activate_group(monkeypatch)
    assert resolve_db_port("16", 16432, {"DB_PORT": "16432"}) == 16432


# --- consumer: db.py _get_db_params ---


def _vcfg(version: str, db_port: int):
    return SimpleNamespace(version=version, ports=SimpleNamespace(db=db_port))


def test_db_params_use_shared_port_for_target(monkeypatch):
    from odoodev.commands.db import _get_db_params

    _activate_group(monkeypatch)
    # Registry already redirects the target's port; the stale .env says 18432.
    params = _get_db_params(_vcfg("18", 16432), {"DB_PORT": "18432"})
    assert params["port"] == 16432


def test_db_params_env_wins_without_migration(monkeypatch):
    from odoodev.commands.db import _get_db_params

    _no_group(monkeypatch)
    params = _get_db_params(_vcfg("18", 18432), {"DB_PORT": "15555"})
    assert params["port"] == 15555


def test_automation_db_params_use_shared_port_for_target(monkeypatch):
    from odoodev.core.automation import _get_db_params

    _activate_group(monkeypatch)
    params = _get_db_params(_vcfg("18", 16432), {"DB_PORT": "18432"})
    assert params["port"] == 16432


# --- consumer: start.py _set_environment (PGPORT for odoo-bin) ---


def test_set_environment_pgport_uses_shared_port(monkeypatch, tmp_path):
    from odoodev.commands import start as start_mod

    _activate_group(monkeypatch)
    monkeypatch.setattr(start_mod, "_write_pgpass", lambda *a, **k: None)
    env = start_mod._set_environment({"DB_PORT": "18432"}, version="18")
    assert env["PGPORT"] == "16432"


def test_set_environment_pgport_env_without_migration(monkeypatch):
    from odoodev.commands import start as start_mod

    _no_group(monkeypatch)
    monkeypatch.setattr(start_mod, "_write_pgpass", lambda *a, **k: None)
    env = start_mod._set_environment({"DB_PORT": "18432"}, version="18")
    assert env["PGPORT"] == "18432"
