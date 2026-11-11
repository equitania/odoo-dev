"""`odoodev env setup` must leave the .env owner-only even when it overwrites a loose file."""

from __future__ import annotations

import os
import stat
from types import SimpleNamespace

from click.testing import CliRunner

import odoodev.cli  # noqa: F401  # resolves the cli <-> commands import cycle
from odoodev.commands import env as env_cmd


def test_existing_env_file_is_tightened_to_0600(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PGPASSWORD=old\n")
    os.chmod(env_file, 0o644)
    cfg = SimpleNamespace(
        version="18", paths=SimpleNamespace(native_dir=str(tmp_path)), ports=SimpleNamespace(db=1, odoo=2, gevent=3)
    )
    monkeypatch.setattr(env_cmd, "resolve_version", lambda ctx, v: "18")
    monkeypatch.setattr(env_cmd, "load_versions", lambda: {})
    monkeypatch.setattr(env_cmd, "get_version", lambda v, versions=None: cfg)
    monkeypatch.setattr(env_cmd, "_render_env_template", lambda *a, **k: "PGPASSWORD=new\n")
    result = CliRunner().invoke(env_cmd.env, ["setup", "18", "--non-interactive"], catch_exceptions=False)
    assert result.exit_code == 0
    assert env_file.read_text() == "PGPASSWORD=new\n"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
