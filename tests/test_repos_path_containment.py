"""A repos.yaml ``path`` must not leave the base directory."""

from __future__ import annotations

import odoodev.cli  # noqa: F401  # resolves the cli <-> commands import cycle
from odoodev.commands import repos as repos_cmd


def test_escaping_path_is_skipped_with_an_error(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_switch(full_path, git_url, branch, base, is_oca=False):
        calls.append(full_path)
        return [], ""

    monkeypatch.setattr(repos_cmd, "switch_branch_and_update", fake_switch)
    config = {
        "addons": [
            {"key": "good", "path": "OCA/web", "git_url": "git@gitlab.ownerp.io:g/web.git"},
            {"key": "evil", "path": "../../outside", "git_url": "git@gitlab.ownerp.io:g/evil.git"},
            {"key": "abs", "path": "/etc/evil", "git_url": "git@gitlab.ownerp.io:g/abs.git"},
        ]
    }
    base = tmp_path / "base"
    base.mkdir()
    _paths, _meta, summary = repos_cmd._process_repos(config, str(base), "18.0", set())
    assert calls == [str(base / "OCA" / "web")]
    assert sorted(key for key, _ in summary.failed) == ["abs", "evil"]
